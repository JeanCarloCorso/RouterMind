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
        self.requests: list[dict[str, Any]] = []
        self._next_user_id = 1
        self._next_key_id = 1

    def initialize(self):
        pass

    def close(self):
        pass

    def create_user(self, name: str, email: str, password_hash: str) -> User:
        if any(user.email == email for user in self.users.values()):
            raise DuplicateUserError
        user = User(self._next_user_id, name, email, password_hash, None)
        self.users[user.id] = user
        self._next_user_id += 1
        return user

    def get_user_by_email(self, email: str) -> User | None:
        return next((user for user in self.users.values() if user.email == email), None)

    def get_user(self, user_id: int) -> User | None:
        return self.users.get(user_id)

    def set_openrouter_key(self, user_id: int, encrypted_key: str) -> None:
        user = self.users[user_id]
        self.users[user_id] = User(user.id, user.name, user.email, user.password_hash, encrypted_key)

    def delete_openrouter_key(self, user_id: int) -> bool:
        user = self.users[user_id]
        if user.openrouter_key_encrypted is None:
            return False
        self.users[user_id] = User(user.id, user.name, user.email, user.password_hash, None)
        return True

    def create_api_key(self, user_id: int, label: str, prefix: str, key_hash: str, expires_at=None) -> int:
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
            "expires_at": expires_at,
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
        if not key or key["user_id"] != user_id or key["revoked_at"]:
            return False
        key["revoked_at"] = datetime.now(UTC).isoformat()
        return True

    def find_api_key_identity(self, key_hash: str):
        key = next((key for key in self.keys.values() if key["key_hash"] == key_hash), None)
        now = datetime.now(UTC).isoformat()
        if not key or key["revoked_at"] or (key["expires_at"] and key["expires_at"] <= now):
            return None
        key["last_used_at"] = datetime.now(UTC).isoformat()
        user = self.users.get(key["user_id"])
        return (user, key["id"]) if user else None

    def find_user_by_api_hash(self, key_hash: str) -> User | None:
        identity = self.find_api_key_identity(key_hash)
        return identity[0] if identity else None

    def record_request(self, user_id: int, **values) -> None:
        self.requests.append({
            "id": len(self.requests) + 1,
            "user_id": user_id,
            "created_at": datetime.now(UTC).isoformat(),
            **values,
        })

    def request_summary(self, user_id: int):
        rows = [row for row in self.requests if row["user_id"] == user_id]
        durations = [row["response_time_ms"] for row in rows]
        return {
            "total": len(rows),
            "successful": sum(bool(row["success"]) for row in rows),
            "failed": sum(not row["success"] for row in rows),
            "total_tokens": sum(row.get("total_tokens") or 0 for row in rows),
            "total_cost_usd": sum((row.get("cost_usd") or 0 for row in rows), 0),
            "average_response_time_ms": sum(durations) / len(durations) if durations else 0,
        }

    def list_request_logs(self, user_id: int, limit: int = 50):
        rows = [row.copy() for row in self.requests if row["user_id"] == user_id]
        for row in rows:
            key = self.keys.get(row.get("api_key_id"))
            row["api_key_label"] = key["label"] if key else None
            row["api_key_prefix"] = key["key_prefix"] if key else None
        return list(reversed(rows))[:limit]

    def dashboard_charts(self, user_id: int):
        days = {}
        for row in self.requests:
            if row["user_id"] != user_id:
                continue
            day = row["created_at"][:10]
            item = days.setdefault(day, {"label": day, "requests": 0, "tokens": 0})
            item["requests"] += 1
            item["tokens"] += row.get("total_tokens") or 0
        keys = []
        for key in self.list_api_keys(user_id):
            matching = [row for row in self.requests if row.get("api_key_id") == key["id"]]
            keys.append({"label": key["label"], "requests": len(matching),
                         "tokens": sum(row.get("total_tokens") or 0 for row in matching)})
        return {"by_day": list(days.values())[-14:], "by_key": keys}


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
            yield b'data: {"id":"x","object":"chat.completion.chunk","model":"free/a"}\n\n'
            yield b'data: {"id":"x","object":"chat.completion.chunk","model":"free/a","usage":{"prompt_tokens":5,"completion_tokens":7,"total_tokens":12,"cost":0.0004}}\n\n'
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
        user = auth.register("Test User", f"user-{len(clients)}@example.com", "a-secure-test-password")
        database.set_openrouter_key(user.id, auth.encrypt_openrouter_key(TEST_OPENROUTER_KEY))
        database.create_api_key(user.id, "Test", TEST_ROUTE_KEY[:16], auth._api_hash(TEST_ROUTE_KEY))
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(fake, database)), base_url="http://test")
        client.routemind_database = database
        clients.append(client)
        return client, fake
    yield factory
    for client in clients:
        await client.aclose()
    get_settings.cache_clear()
