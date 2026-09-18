import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class User:
    id: int
    email: str
    password_hash: str
    openrouter_key_encrypted: str | None


class Database:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    openrouter_key_encrypted TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    label TEXT NOT NULL,
                    key_prefix TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
                """
            )
            # Version 0.2 changes revocation into physical deletion. Purge legacy rows
            # so hashes and metadata from previously revoked keys are not retained.
            connection.execute("DELETE FROM api_keys WHERE revoked_at IS NOT NULL")
        if self.path != ":memory:" and os.path.exists(self.path):
            os.chmod(self.path, 0o600)

    @staticmethod
    def _user(row: sqlite3.Row | None) -> User | None:
        return User(row["id"], row["email"], row["password_hash"], row["openrouter_key_encrypted"]) if row else None

    def create_user(self, email: str, password_hash: str) -> User:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
                (email, password_hash, now),
            )
            row = connection.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._user(row)  # type: ignore[return-value]

    def get_user_by_email(self, email: str) -> User | None:
        with self._lock, self._connect() as connection:
            return self._user(connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone())

    def get_user(self, user_id: int) -> User | None:
        with self._lock, self._connect() as connection:
            return self._user(connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

    def set_openrouter_key(self, user_id: int, encrypted_key: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("UPDATE users SET openrouter_key_encrypted = ? WHERE id = ?", (encrypted_key, user_id))

    def delete_openrouter_key(self, user_id: int) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE users SET openrouter_key_encrypted = NULL WHERE id = ? AND openrouter_key_encrypted IS NOT NULL",
                (user_id,),
            )
            return cursor.rowcount == 1

    def create_api_key(self, user_id: int, label: str, prefix: str, key_hash: str) -> int:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO api_keys(user_id, label, key_prefix, key_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, label, prefix, key_hash, datetime.now(UTC).isoformat()),
            )
            return int(cursor.lastrowid)

    def list_api_keys(self, user_id: int) -> list[sqlite3.Row]:
        with self._lock, self._connect() as connection:
            return connection.execute(
                "SELECT id, label, key_prefix, created_at, last_used_at, revoked_at FROM api_keys WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            ).fetchall()

    def get_api_key(self, user_id: int, key_id: int) -> sqlite3.Row | None:
        with self._lock, self._connect() as connection:
            return connection.execute(
                "SELECT id, label, key_prefix, created_at, last_used_at FROM api_keys WHERE id = ? AND user_id = ?",
                (key_id, user_id),
            ).fetchone()

    def delete_api_key(self, user_id: int, key_id: int) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM api_keys WHERE id = ? AND user_id = ?", (key_id, user_id))
            return cursor.rowcount == 1

    def find_user_by_api_hash(self, key_hash: str) -> User | None:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT u.* FROM api_keys k JOIN users u ON u.id = k.user_id WHERE k.key_hash = ? AND k.revoked_at IS NULL",
                (key_hash,),
            ).fetchone()
            if row:
                connection.execute("UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?", (now, key_hash))
        return self._user(row)
