import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, ForeignKey, Index, Integer, MetaData, String, Table, Text, create_engine, delete, insert, select, update
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool


metadata = MetaData()
users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String(254), nullable=False, unique=True),
    Column("password_hash", Text, nullable=False),
    Column("openrouter_key_encrypted", Text),
    Column("created_at", String(40), nullable=False),
)
api_keys = Table(
    "api_keys",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("label", String(80), nullable=False),
    Column("key_prefix", String(32), nullable=False),
    Column("key_hash", String(64), nullable=False, unique=True),
    Column("created_at", String(40), nullable=False),
    Column("last_used_at", String(40)),
    # Kept only for automatic cleanup of databases created before physical deletion.
    Column("revoked_at", String(40)),
)
Index("idx_api_keys_hash", api_keys.c.key_hash)


class DuplicateUserError(Exception):
    pass


@dataclass(frozen=True)
class User:
    id: int
    email: str
    password_hash: str
    openrouter_key_encrypted: str | None


def _normalize_url(value: str) -> str:
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value.removeprefix("postgres://")
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value.removeprefix("postgresql://")
    if value.startswith("postgresql+psycopg://"):
        return value
    raise ValueError("RouteMind requires a PostgreSQL connection URL")


def _configure_postgres_url(database_url: str) -> tuple[URL, bool]:
    url = make_url(database_url)
    # Supabase exposes its transaction pooler on port 6543. Connections are
    # short-lived and must not use client-side prepared statements.
    transaction_pooler = url.get_backend_name() == "postgresql" and url.port == 6543
    if transaction_pooler and "sslmode" not in url.query:
        url = url.update_query_dict({"sslmode": "require"})
    return url, transaction_pooler


class Database:
    """Synchronous PostgreSQL repository."""

    def __init__(self, url_or_path: str):
        database_url = _normalize_url(url_or_path)
        self.transaction_pooler = False
        self._connect_args: dict[str, Any] = {}
        self._lock = threading.RLock()
        engine_options: dict[str, Any] = {"pool_pre_ping": True}
        engine_target, self.transaction_pooler = _configure_postgres_url(database_url)
        if self.transaction_pooler:
            self._connect_args = {"prepare_threshold": None}
            engine_options["poolclass"] = NullPool
        else:
            engine_options.update({"pool_size": 2, "max_overflow": 1, "pool_recycle": 300})
        if self._connect_args:
            engine_options["connect_args"] = self._connect_args
        self.engine: Engine = create_engine(engine_target, **engine_options)

    def initialize(self) -> None:
        with self._lock:
            metadata.create_all(self.engine)
            with self.engine.begin() as connection:
                connection.execute(delete(api_keys).where(api_keys.c.revoked_at.is_not(None)))

    def close(self) -> None:
        self.engine.dispose()

    @staticmethod
    def _user(row: Mapping[str, Any] | None) -> User | None:
        return User(row["id"], row["email"], row["password_hash"], row["openrouter_key_encrypted"]) if row else None

    def create_user(self, email: str, password_hash: str) -> User:
        try:
            with self._lock, self.engine.begin() as connection:
                user_id = connection.execute(
                    insert(users).values(email=email, password_hash=password_hash, created_at=datetime.now(UTC).isoformat()).returning(users.c.id)
                ).scalar_one()
                row = connection.execute(select(users).where(users.c.id == user_id)).mappings().first()
        except IntegrityError as exc:
            raise DuplicateUserError from exc
        return self._user(row)  # type: ignore[return-value]

    def get_user_by_email(self, email: str) -> User | None:
        with self._lock, self.engine.connect() as connection:
            row = connection.execute(select(users).where(users.c.email == email)).mappings().first()
        return self._user(row)

    def get_user(self, user_id: int) -> User | None:
        with self._lock, self.engine.connect() as connection:
            row = connection.execute(select(users).where(users.c.id == user_id)).mappings().first()
        return self._user(row)

    def set_openrouter_key(self, user_id: int, encrypted_key: str) -> None:
        with self._lock, self.engine.begin() as connection:
            connection.execute(update(users).where(users.c.id == user_id).values(openrouter_key_encrypted=encrypted_key))

    def delete_openrouter_key(self, user_id: int) -> bool:
        with self._lock, self.engine.begin() as connection:
            result = connection.execute(
                update(users)
                .where(users.c.id == user_id, users.c.openrouter_key_encrypted.is_not(None))
                .values(openrouter_key_encrypted=None)
            )
            return result.rowcount == 1

    def create_api_key(self, user_id: int, label: str, prefix: str, key_hash: str) -> int:
        with self._lock, self.engine.begin() as connection:
            return int(
                connection.execute(
                    insert(api_keys)
                    .values(user_id=user_id, label=label, key_prefix=prefix, key_hash=key_hash, created_at=datetime.now(UTC).isoformat())
                    .returning(api_keys.c.id)
                ).scalar_one()
            )

    def list_api_keys(self, user_id: int) -> list[Mapping[str, Any]]:
        statement = (
            select(api_keys.c.id, api_keys.c.label, api_keys.c.key_prefix, api_keys.c.created_at, api_keys.c.last_used_at, api_keys.c.revoked_at)
            .where(api_keys.c.user_id == user_id)
            .order_by(api_keys.c.id.desc())
        )
        with self._lock, self.engine.connect() as connection:
            return list(connection.execute(statement).mappings().all())

    def get_api_key(self, user_id: int, key_id: int) -> Mapping[str, Any] | None:
        statement = select(
            api_keys.c.id, api_keys.c.label, api_keys.c.key_prefix, api_keys.c.created_at, api_keys.c.last_used_at
        ).where(api_keys.c.id == key_id, api_keys.c.user_id == user_id)
        with self._lock, self.engine.connect() as connection:
            return connection.execute(statement).mappings().first()

    def delete_api_key(self, user_id: int, key_id: int) -> bool:
        with self._lock, self.engine.begin() as connection:
            result = connection.execute(delete(api_keys).where(api_keys.c.id == key_id, api_keys.c.user_id == user_id))
            return result.rowcount == 1

    def find_user_by_api_hash(self, key_hash: str) -> User | None:
        statement = (
            select(users)
            .select_from(api_keys.join(users, users.c.id == api_keys.c.user_id))
            .where(api_keys.c.key_hash == key_hash, api_keys.c.revoked_at.is_(None))
        )
        with self._lock, self.engine.begin() as connection:
            row = connection.execute(statement).mappings().first()
            if row:
                connection.execute(
                    update(api_keys).where(api_keys.c.key_hash == key_hash).values(last_used_at=datetime.now(UTC).isoformat())
                )
        return self._user(row)
