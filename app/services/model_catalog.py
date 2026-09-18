import asyncio
import time
from typing import Any

from app.core.errors import RouteMindError


class ModelCatalog:
    def __init__(self, client: Any, ttl_seconds: int, max_stale_seconds: int):
        self.client = client
        self.ttl_seconds = ttl_seconds
        self.max_stale_seconds = max_stale_seconds
        self._models: list[dict[str, Any]] = []
        self._updated_at = 0.0
        self._lock = asyncio.Lock()

    async def get_models(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._models and now - self._updated_at < self.ttl_seconds:
            return self._models
        async with self._lock:
            now = time.monotonic()
            if self._models and now - self._updated_at < self.ttl_seconds:
                return self._models
            try:
                models = await self.client.list_models()
            except Exception as exc:
                if self._models and now - self._updated_at <= self.max_stale_seconds:
                    return self._models
                raise RouteMindError(503, "Model catalog is unavailable or too stale", "catalog_unavailable") from exc
            self._models = models
            self._updated_at = time.monotonic()
            return models
