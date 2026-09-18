from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import Settings


class OpenRouterClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.http = httpx.AsyncClient(
            base_url=settings.openrouter_base_url,
            timeout=httpx.Timeout(settings.request_timeout_seconds),
            transport=transport,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.settings.openrouter_api_key.get_secret_value()}"}
        if self.settings.app_url:
            headers["HTTP-Referer"] = self.settings.app_url
            headers["X-OpenRouter-Title"] = self.settings.app_name
        return headers

    async def list_models(self) -> list[dict[str, Any]]:
        response = await self.http.get("/models", headers=self._headers())
        response.raise_for_status()
        return response.json()["data"]

    async def complete(self, payload: dict[str, Any]) -> httpx.Response:
        return await self.http.post("/chat/completions", headers=self._headers(), json=payload)

    async def stream(self, payload: dict[str, Any]) -> tuple[httpx.Response, AsyncIterator[bytes]]:
        request = self.http.build_request("POST", "/chat/completions", headers=self._headers(), json=payload)
        response = await self.http.send(request, stream=True)
        return response, response.aiter_raw()

    async def close(self) -> None:
        await self.http.aclose()
