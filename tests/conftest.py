from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio

from app.main import create_app
from app.services.auth import AuthService
from app.services.database import Database

TEST_ROUTE_KEY = "rm_live_test_key_with_more_than_32_characters"
TEST_OPENROUTER_KEY = "sk-or-v1-user-specific-test-key"


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
        self.models, self.responses, self.payloads, self.upstream_keys = models, responses or [], [], []

    async def list_models(self, api_key):
        self.upstream_keys.append(api_key)
        return self.models

    async def complete(self, payload, api_key):
        self.payloads.append(payload)
        self.upstream_keys.append(api_key)
        if self.responses:
            return self.responses.pop(0)
        return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 1, "model": payload["model"], "choices": [], "usage": {}})

    async def stream(self, payload, api_key) -> tuple[httpx.Response, AsyncIterator[bytes]]:
        self.payloads.append(payload)
        self.upstream_keys.append(api_key)
        response = httpx.Response(200, headers={"content-type": "text/event-stream"})
        async def chunks():
            yield b'data: {"id":"x","object":"chat.completion.chunk"}\n\n'
            yield b"data: [DONE]\n\n"
        return response, chunks()

    async def close(self):
        pass


@pytest_asyncio.fixture
async def make_client(monkeypatch, tmp_path):
    secret = "test-secret-key-with-at-least-32-characters"
    monkeypatch.setenv("ROUTEMIND_SECRET_KEY", secret)
    from app.core.config import get_settings
    get_settings.cache_clear()
    clients = []
    def factory(models, responses=None):
        fake = FakeOpenRouter(models, responses)
        database = Database(str(tmp_path / f"test-{len(clients)}.db"))
        database.initialize()
        auth = AuthService(database, secret)
        user = auth.register(f"user-{len(clients)}@example.com", "a-secure-test-password")
        database.set_openrouter_key(user.id, auth.encrypt_openrouter_key(TEST_OPENROUTER_KEY))
        database.create_api_key(user.id, "Test", TEST_ROUTE_KEY[:16], auth._api_hash(TEST_ROUTE_KEY))
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(fake, database)), base_url="http://test")
        clients.append(client)
        return client, fake
    yield factory
    for client in clients:
        await client.aclose()
    get_settings.cache_clear()
