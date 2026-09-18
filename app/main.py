import asyncio
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import RouteMindError, error_response
from app.services.model_catalog import ModelCatalog
from app.services.openrouter_client import OpenRouterClient
from app.services.auth import AuthService
from app.services.database import Database
from app.web import router as web_router


class SlidingWindowLimiter:
    def __init__(self, limit: int):
        self.limit = limit
        self.buckets: dict[str, deque[float]] = defaultdict(deque)
        self.lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        cutoff = time.monotonic() - 60
        async with self.lock:
            bucket = self.buckets[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(time.monotonic())
            return True


def create_app(openrouter_client=None, database=None) -> FastAPI:
    settings = get_settings()
    secret = settings.secret_key.get_secret_value()
    if settings.environment.casefold() == "production":
        if len(secret) < 32 or secret.startswith("development-"):
            raise RuntimeError("ROUTEMIND_SECRET_KEY must be a random value of at least 32 characters in production")
        if not settings.secure_cookies:
            raise RuntimeError("ROUTEMIND_SECURE_COOKIES must be true in production")
    client = openrouter_client or OpenRouterClient(settings)
    database = database or Database(settings.database_path)
    auth = AuthService(database, secret)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.initialize()
        yield
        await client.close()

    app = FastAPI(title="RouteMind", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie="routemind_session",
        max_age=3600,
        same_site="strict",
        https_only=settings.secure_cookies,
    )
    app.state.settings = settings
    app.state.openrouter = client
    app.state.database = database
    app.state.auth = auth
    app.state.catalog = ModelCatalog(client, settings.catalog_ttl_seconds, settings.catalog_max_stale_seconds)
    limiter = SlidingWindowLimiter(settings.rate_limit_per_minute)

    @app.middleware("http")
    async def authentication_and_rate_limit(request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        identity = request.client.host if request.client else "unknown"
        if request.url.path.startswith("/api/v1/"):
            authorization = request.headers.get("authorization", "")
            token = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
            user = auth.authenticate_api_key(token)
            if not user:
                return JSONResponse(status_code=401, content={"error": {"message": "Invalid RouteMind API key", "code": "invalid_api_key"}})
            openrouter_key = auth.decrypt_openrouter_key(user)
            if not openrouter_key:
                return JSONResponse(status_code=403, content={"error": {"message": "No valid OpenRouter key is configured for this account", "code": "openrouter_key_missing"}})
            request.state.user = user
            request.state.openrouter_key = openrouter_key
            identity = f"user:{user.id}"
        if not await limiter.allow(identity):
            return JSONResponse(status_code=429, content={"error": {"message": "Rate limit exceeded", "code": "rate_limit_exceeded"}})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        return response

    @app.exception_handler(RouteMindError)
    async def handle_routemind_error(_: Request, exc: RouteMindError):
        return error_response(exc)

    app.include_router(web_router)
    app.include_router(router)
    return app


app = create_app()
