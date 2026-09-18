import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import pytest_asyncio

os.environ.setdefault(
    "ROUTEMIND_DATABASE_URL",
    "postgresql://test:test@localhost:5432/routemind_test",
)

from app.main import create_app
from app.services.auth import AuthService
from app.services.database import DuplicateUserError, User

TEST_ROUTE_KEY = "rm_live_test_key_with_more_than_32_characters"
TEST_OPENROUTER_KEY = "sk-or-v1-user-specific-test-key"


class MemoryDatabase:
    """Test repository with no external database dependency."""

    def __init__(self):
        self.users: dict[int, User] = {}
        self.keys: dict[int, dict[str, Any]] = {}
        self._next_user_id = 1
        self._next_key_id = 1

    def initialize(self):
        pass

    def close(self):
        pass

    def create_user(self, email: str, password_hash: str) -> User:
        if any(user.email == email for user in self.users.values()):
            raise DuplicateUserError
        user = User(self._next_user_id, email, password_hash, None)
        self.users[user.id] = user
        self._next_user_id += 1
        return user

    def get_user_by_email(self, email: str) -> User | None:
        return next((user for user in self.users.values() if user.email == email), None)

    def get_user(self, user_id: int) -> User | None:
        return self.users.get(user_id)

    def set_openrouter_key(self, user_id: int, encrypted_key: str) -> None:
        user = self.users[user_id]
        self.users[user_id] = User(user.id, user.email, user.password_hash, encrypted_key)

    def delete_openrouter_key(self, user_id: int) -> bool:
        user = self.users[user_id]
        if user.openrouter_key_encrypted is None:
            return False
        self.users[user_id] = User(user.id, user.email, user.password_hash, None)
        return True

    def create_api_key(self, user_id: int, label: str, prefix: str, key_hash: str) -> int:
        key_id = self._next_key_id
        self._next_key_id += 1
        self.keys[key_id] = {
            "id": key_id,
            "user_id": user_id,
            "label": label,
            "key_prefix": prefix,
            "key_hash": key_hash,
            "created_at": datetime.now(UTC).isoformat(),
            "last_used_at": None,
            "revoked_at": None,
        }
        return key_id

    def list_api_keys(self, user_id: int):
        return sorted(
            (key.copy() for key in self.keys.values() if key["user_id"] == user_id),
            key=lambda key: key["id"],
            reverse=True,
        )

    def get_api_key(self, user_id: int, key_id: int):
        key = self.keys.get(key_id)
        return key.copy() if key and key["user_id"] == user_id else None

    def delete_api_key(self, user_id: int, key_id: int) -> bool:
        key = self.keys.get(key_id)
        if not key or key["user_id"] != user_id:
            return False
        del self.keys[key_id]
        return True

    def find_user_by_api_hash(self, key_hash: str) -> User | None:
        key = next((key for key in self.keys.values() if key["key_hash"] == key_hash), None)
        if not key:
            return None
        key["last_used_at"] = datetime.now(UTC).isoformat()
        return self.users.get(key["user_id"])


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
async def make_client(monkeypatch):
    secret = "test-secret-key-with-at-least-32-characters"
    monkeypatch.setenv("ROUTEMIND_SECRET_KEY", secret)
    from app.core.config import get_settings
    get_settings.cache_clear()
    clients = []
    def factory(models, responses=None):
        fake = FakeOpenRouter(models, responses)
        database = MemoryDatabase()
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
