import asyncio
import time
from typing import Any

from app.core.errors import RouteMindError


class ModelCatalog:
    def __init__(self, client: Any, ttl_seconds: int, max_stale_seconds: int):
        self.client = client
        self.ttl_seconds = ttl_seconds
        self.max_stale_seconds = max_stale_seconds
        self._cache: dict[int, tuple[list[dict[str, Any]], float]] = {}
        self._unavailable_until: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def invalidate(self, user_id: int) -> None:
        self._cache.pop(user_id, None)

    def mark_temporarily_unavailable(self, model_id: str, seconds: int = 900) -> None:
        self._unavailable_until[model_id] = time.monotonic() + seconds

    def _available(self, models: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
        self._unavailable_until = {
            model_id: until for model_id, until in self._unavailable_until.items() if until > now
        }
        return [model for model in models if self._unavailable_until.get(model.get("id", ""), 0) <= now]

    async def get_models(self, user_id: int, api_key: str) -> list[dict[str, Any]]:
        now = time.monotonic()
        models, updated_at = self._cache.get(user_id, ([], 0.0))
        if models and now - updated_at < self.ttl_seconds:
            return self._available(models, now)
        async with self._lock:
            now = time.monotonic()
            models, updated_at = self._cache.get(user_id, ([], 0.0))
            if models and now - updated_at < self.ttl_seconds:
                return self._available(models, now)
            try:
                models = await self.client.list_models(api_key)
            except Exception as exc:
                if models and now - updated_at <= self.max_stale_seconds:
                    return self._available(models, now)
                raise RouteMindError(503, "Model catalog is unavailable or too stale", "catalog_unavailable") from exc
            self._cache[user_id] = (models, time.monotonic())
            return self._available(models, now)
