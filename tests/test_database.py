from app.core.config import get_settings
from app.services.database import Database
from sqlalchemy.pool import NullPool


def test_postgres_urls_use_psycopg_driver_without_connecting():
    database = Database("postgresql://user:password@example.invalid/routemind?sslmode=require")
    try:
        assert database.engine.url.drivername == "postgresql+psycopg"
        assert database.engine.pool.size() == 2
    finally:
        database.close()


def test_unprefixed_database_url_is_supported(monkeypatch):
    monkeypatch.delenv("ROUTEMIND_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@example.invalid/routemind")
    get_settings.cache_clear()
    try:
        assert get_settings().database_connection.startswith("postgresql://")
    finally:
        get_settings.cache_clear()


def test_supabase_transaction_pooler_uses_safe_connection_settings():
    database = Database(
        "postgresql://postgres.project:password@aws-0-us-west-2.pooler.supabase.com:6543/postgres"
    )
    try:
        assert database.transaction_pooler is True
        assert isinstance(database.engine.pool, NullPool)
        assert database.engine.url.query["sslmode"] == "require"
        assert database._connect_args["prepare_threshold"] is None
    finally:
        database.close()


def test_transaction_pooler_preserves_explicit_ssl_mode():
    database = Database(
        "postgresql://postgres.project:password@aws-0-us-west-2.pooler.supabase.com:6543/postgres?sslmode=verify-full"
    )
    try:
        assert database.engine.url.query["sslmode"] == "verify-full"
    finally:
        database.close()
