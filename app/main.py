import asyncio
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import RouteMindError, error_response
from app.services.model_catalog import ModelCatalog
from app.services.openrouter_client import OpenRouterClient


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


def create_app(openrouter_client=None) -> FastAPI:
    settings = get_settings()
    client = openrouter_client or OpenRouterClient(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await client.close()

    app = FastAPI(title="RouteMind", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.openrouter = client
    app.state.catalog = ModelCatalog(client, settings.catalog_ttl_seconds, settings.catalog_max_stale_seconds)
    limiter = SlidingWindowLimiter(settings.rate_limit_per_minute)

    @app.middleware("http")
    async def authentication_and_rate_limit(request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
        accepted = settings.accepted_api_keys
        if accepted and token not in accepted:
            return JSONResponse(status_code=401, content={"error": {"message": "Invalid API key", "code": "invalid_api_key"}})
        identity = token or (request.client.host if request.client else "unknown")
        if not await limiter.allow(identity):
            return JSONResponse(status_code=429, content={"error": {"message": "Rate limit exceeded", "code": "rate_limit_exceeded"}})
        return await call_next(request)

    @app.exception_handler(RouteMindError)
    async def handle_routemind_error(_: Request, exc: RouteMindError):
        return error_response(exc)

    app.include_router(router)
    return app


app = create_app()
