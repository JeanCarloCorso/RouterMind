import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, MetaData, Numeric, String, Table, Text, case, create_engine, delete, func, insert, select, text, update
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool


metadata = MetaData()
users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(120), nullable=False),
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
    Column("revoked_at", String(40)),
    Column("expires_at", String(40)),
)
Index("idx_api_keys_hash", api_keys.c.key_hash)
request_logs = Table(
    "request_logs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("api_key_id", Integer, ForeignKey("api_keys.id", ondelete="SET NULL")),
    Column("created_at", String(40), nullable=False),
    Column("success", Boolean, nullable=False),
    Column("status_code", Integer, nullable=False),
    Column("model", String(255)),
    Column("prompt_tokens", Integer),
    Column("completion_tokens", Integer),
    Column("total_tokens", Integer),
    Column("cost_usd", Numeric(18, 10)),
    Column("response_time_ms", Integer, nullable=False),
)
Index("idx_request_logs_user_created", request_logs.c.user_id, request_logs.c.created_at)
Index("idx_request_logs_api_key", request_logs.c.api_key_id)


class DuplicateUserError(Exception):
    pass


@dataclass(frozen=True)
class User:
    id: int
    name: str
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
                connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS name VARCHAR(120)"))
                connection.execute(
                    text("UPDATE users SET name = split_part(email, '@', 1) WHERE name IS NULL OR name = ''")
                )
                connection.execute(text("ALTER TABLE users ALTER COLUMN name SET NOT NULL"))
                connection.execute(
                    text("ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS cost_usd NUMERIC(18, 10)")
                )
                connection.execute(text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS expires_at VARCHAR(40)"))
                connection.execute(text("ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS api_key_id INTEGER"))
                connection.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_request_logs_api_key ON request_logs (api_key_id)"
                ))
                connection.execute(text(
                    "DO $$ BEGIN ALTER TABLE request_logs ADD CONSTRAINT request_logs_api_key_id_fkey "
                    "FOREIGN KEY (api_key_id) REFERENCES api_keys(id) ON DELETE SET NULL; "
                    "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
                ))

    def close(self) -> None:
        self.engine.dispose()

    @staticmethod
    def _user(row: Mapping[str, Any] | None) -> User | None:
        return User(row["id"], row["name"], row["email"], row["password_hash"], row["openrouter_key_encrypted"]) if row else None

    def create_user(self, name: str, email: str, password_hash: str) -> User:
        try:
            with self._lock, self.engine.begin() as connection:
                user_id = connection.execute(
                    insert(users).values(name=name, email=email, password_hash=password_hash, created_at=datetime.now(UTC).isoformat()).returning(users.c.id)
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

    def create_api_key(self, user_id: int, label: str, prefix: str, key_hash: str, expires_at: str | None = None) -> int:
        with self._lock, self.engine.begin() as connection:
            return int(
                connection.execute(
                    insert(api_keys)
                    .values(user_id=user_id, label=label, key_prefix=prefix, key_hash=key_hash,
                            created_at=datetime.now(UTC).isoformat(), expires_at=expires_at)
                    .returning(api_keys.c.id)
                ).scalar_one()
            )

    def list_api_keys(self, user_id: int) -> list[Mapping[str, Any]]:
        statement = (
            select(api_keys.c.id, api_keys.c.label, api_keys.c.key_prefix, api_keys.c.created_at,
                   api_keys.c.last_used_at, api_keys.c.revoked_at, api_keys.c.expires_at)
            .where(api_keys.c.user_id == user_id)
            .order_by(api_keys.c.id.desc())
        )
        with self._lock, self.engine.connect() as connection:
            return list(connection.execute(statement).mappings().all())

    def get_api_key(self, user_id: int, key_id: int) -> Mapping[str, Any] | None:
        statement = select(
            api_keys.c.id, api_keys.c.label, api_keys.c.key_prefix, api_keys.c.created_at,
            api_keys.c.last_used_at, api_keys.c.revoked_at, api_keys.c.expires_at
        ).where(api_keys.c.id == key_id, api_keys.c.user_id == user_id)
        with self._lock, self.engine.connect() as connection:
            return connection.execute(statement).mappings().first()

    def delete_api_key(self, user_id: int, key_id: int) -> bool:
        with self._lock, self.engine.begin() as connection:
            result = connection.execute(
                update(api_keys)
                .where(api_keys.c.id == key_id, api_keys.c.user_id == user_id, api_keys.c.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC).isoformat())
            )
            return result.rowcount == 1

    def extend_expired_api_key(self, user_id: int, key_id: int, expires_at: str | None) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._lock, self.engine.begin() as connection:
            result = connection.execute(
                update(api_keys)
                .where(api_keys.c.id == key_id, api_keys.c.user_id == user_id,
                       api_keys.c.revoked_at.is_(None), api_keys.c.expires_at.is_not(None),
                       api_keys.c.expires_at <= now)
                .values(expires_at=expires_at)
            )
            return result.rowcount == 1

    def remove_expired_api_key(self, user_id: int, key_id: int) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._lock, self.engine.begin() as connection:
            result = connection.execute(
                delete(api_keys).where(
                    api_keys.c.id == key_id, api_keys.c.user_id == user_id,
                    api_keys.c.revoked_at.is_(None), api_keys.c.expires_at.is_not(None),
                    api_keys.c.expires_at <= now,
                )
            )
            return result.rowcount == 1

    def find_api_key_identity(self, key_hash: str) -> tuple[User, int] | None:
        now = datetime.now(UTC).isoformat()
        statement = (
            select(*users.c, api_keys.c.id.label("api_key_id"))
            .select_from(api_keys.join(users, users.c.id == api_keys.c.user_id))
            .where(api_keys.c.key_hash == key_hash, api_keys.c.revoked_at.is_(None),
                   (api_keys.c.expires_at.is_(None) | (api_keys.c.expires_at > now)))
        )
        with self._lock, self.engine.begin() as connection:
            row = connection.execute(statement).mappings().first()
            if row:
                connection.execute(
                    update(api_keys).where(api_keys.c.key_hash == key_hash).values(last_used_at=datetime.now(UTC).isoformat())
                )
        user = self._user(row)
        return (user, int(row["api_key_id"])) if user and row else None

    def find_user_by_api_hash(self, key_hash: str) -> User | None:
        identity = self.find_api_key_identity(key_hash)
        return identity[0] if identity else None

    def record_request(
        self, user_id: int, *, api_key_id: int | None = None, success: bool, status_code: int, model: str | None,
        prompt_tokens: int | None, completion_tokens: int | None,
        total_tokens: int | None, cost_usd: Any, response_time_ms: int,
    ) -> None:
        with self._lock, self.engine.begin() as connection:
            connection.execute(
                insert(request_logs).values(
                    user_id=user_id,
                    api_key_id=api_key_id,
                    created_at=datetime.now(UTC).isoformat(),
                    success=success,
                    status_code=status_code,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cost_usd=cost_usd,
                    response_time_ms=response_time_ms,
                )
            )

    def request_summary(self, user_id: int) -> Mapping[str, Any]:
        statement = select(
            func.count(request_logs.c.id).label("total"),
            func.coalesce(func.sum(case((request_logs.c.success.is_(True), 1), else_=0)), 0).label("successful"),
            func.coalesce(func.sum(case((request_logs.c.success.is_(False), 1), else_=0)), 0).label("failed"),
            func.coalesce(func.sum(request_logs.c.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(request_logs.c.cost_usd), 0).label("total_cost_usd"),
            func.coalesce(func.avg(request_logs.c.response_time_ms), 0).label("average_response_time_ms"),
        ).where(request_logs.c.user_id == user_id)
        with self._lock, self.engine.connect() as connection:
            return connection.execute(statement).mappings().one()

    def list_request_logs(self, user_id: int, limit: int = 50) -> list[Mapping[str, Any]]:
        statement = (
            select(*request_logs.c, api_keys.c.label.label("api_key_label"),
                   api_keys.c.key_prefix.label("api_key_prefix"))
            .select_from(request_logs.outerjoin(api_keys, request_logs.c.api_key_id == api_keys.c.id))
            .where(request_logs.c.user_id == user_id)
            .order_by(request_logs.c.id.desc())
            .limit(limit)
        )
        with self._lock, self.engine.connect() as connection:
            return list(connection.execute(statement).mappings().all())

    def dashboard_charts(self, user_id: int) -> dict[str, list[Mapping[str, Any]]]:
        # Reuse the exact same SQL expression so PostgreSQL sees identical bind
        # parameters in SELECT, GROUP BY and ORDER BY.
        day = func.substr(request_logs.c.created_at, 1, 10)
        by_day = (
            select(day.label("label"),
                   func.count(request_logs.c.id).label("requests"),
                   func.coalesce(func.sum(request_logs.c.total_tokens), 0).label("tokens"),
                   func.coalesce(func.sum(request_logs.c.cost_usd), 0).label("cost_usd"))
            .where(request_logs.c.user_id == user_id)
            .group_by(day)
            .order_by(day.desc()).limit(14)
        )
        by_key = (
            select(api_keys.c.label.label("label"), func.count(request_logs.c.id).label("requests"),
                   func.coalesce(func.sum(request_logs.c.total_tokens), 0).label("tokens"),
                   func.coalesce(func.sum(request_logs.c.cost_usd), 0).label("cost_usd"))
            .select_from(api_keys.outerjoin(request_logs, request_logs.c.api_key_id == api_keys.c.id))
            .where(api_keys.c.user_id == user_id)
            .group_by(api_keys.c.id, api_keys.c.label).order_by(func.count(request_logs.c.id).desc())
        )
        with self._lock, self.engine.connect() as connection:
            days = list(reversed(connection.execute(by_day).mappings().all()))
            keys = list(connection.execute(by_key).mappings().all())
        return {"by_day": days, "by_key": keys}
