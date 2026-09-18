from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio

from app.main import create_app


def model(model_id: str, prompt: str = "0", completion: str = "0", supported=None, inputs=None) -> dict[str, Any]:
    return {
        "id": model_id, "name": model_id,
        "description": "general coding and reasoning assistant", "context_length": 128000,
        "architecture": {"input_modalities": inputs or ["text"], "output_modalities": ["text"]},
        "supported_parameters": supported or ["temperature", "tools", "tool_choice", "response_format", "reasoning"],
        "pricing": {"prompt": prompt, "completion": completion, "request": "0", "image": "0", "audio": "0"},
    }


class FakeOpenRouter:
    def __init__(self, models, responses=None):
        self.models, self.responses, self.payloads = models, responses or [], []

    async def list_models(self):
        return self.models

    async def complete(self, payload):
        self.payloads.append(payload)
        if self.responses:
            return self.responses.pop(0)
        return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 1, "model": payload["model"], "choices": [], "usage": {}})

    async def stream(self, payload) -> tuple[httpx.Response, AsyncIterator[bytes]]:
        self.payloads.append(payload)
        response = httpx.Response(200, headers={"content-type": "text/event-stream"})
        async def chunks():
            yield b'data: {"id":"x","object":"chat.completion.chunk"}\n\n'
            yield b"data: [DONE]\n\n"
        return response, chunks()

    async def close(self):
        pass


@pytest_asyncio.fixture
async def make_client(monkeypatch):
    monkeypatch.setenv("ROUTEMIND_API_KEYS", "test-key")
    from app.core.config import get_settings
    get_settings.cache_clear()
    clients = []
    def factory(models, responses=None):
        fake = FakeOpenRouter(models, responses)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(fake)), base_url="http://test")
        clients.append(client)
        return client, fake
    yield factory
    for client in clients:
        await client.aclose()
    get_settings.cache_clear()
