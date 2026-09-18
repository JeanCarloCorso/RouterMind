import re

import httpx

from app.core.config import get_settings
from app.main import create_app
from app.services.database import Database
from app.services.auth import AuthService
from conftest import FakeOpenRouter, model


def csrf_from(response: httpx.Response) -> str:
    match = re.search(r"name='csrf' value='([^']+)'", response.text)
    assert match
    return match.group(1)


async def test_account_to_personal_openrouter_key_flow(monkeypatch, tmp_path):
    monkeypatch.setenv("ROUTEMIND_SECRET_KEY", "integration-secret-at-least-32-characters")
    monkeypatch.setenv("ROUTEMIND_ENVIRONMENT", "development")
    monkeypatch.setenv("ROUTEMIND_SECURE_COOKIES", "false")
    get_settings.cache_clear()
    database = Database(str(tmp_path / "users.db"))
    database.initialize()
    upstream = FakeOpenRouter([model("free/model")])
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(upstream, database)),
        base_url="http://test",
    )
    try:
        register_page = await client.get("/register")
        response = await client.post(
            "/register",
            data={"csrf": csrf_from(register_page), "email": "alice@example.com", "password": "correct horse battery staple"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "Não configurada" in response.text

        csrf = csrf_from(response)
        response = await client.post(
            "/openrouter-key",
            data={"csrf": csrf, "openrouter_key": "sk-or-v1-alice-personal-key"},
            follow_redirects=True,
        )
        assert "Configurada" in response.text
        csrf = csrf_from(response)
        response = await client.post("/keys", data={"csrf": csrf, "label": "Produção"})
        match = re.search(r"rm_live_[A-Za-z0-9_-]+", response.text)
        assert match
        route_key = match.group(0)

        completion = await client.post(
            "/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {route_key}"},
            json={"messages": [{"role": "user", "content": "Olá"}]},
        )
        assert completion.status_code == 200
        assert upstream.upstream_keys == ["sk-or-v1-alice-personal-key"] * 2
        assert route_key not in upstream.upstream_keys
    finally:
        await client.aclose()
        get_settings.cache_clear()


async def test_csrf_and_revoked_key_are_enforced(monkeypatch, tmp_path):
    monkeypatch.setenv("ROUTEMIND_SECRET_KEY", "integration-secret-at-least-32-characters")
    monkeypatch.setenv("ROUTEMIND_ENVIRONMENT", "development")
    monkeypatch.setenv("ROUTEMIND_SECURE_COOKIES", "false")
    get_settings.cache_clear()
    database = Database(str(tmp_path / "security.db"))
    database.initialize()
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(FakeOpenRouter([model("free/model")]), database)),
        base_url="http://test",
    )
    try:
        page = await client.get("/register")
        assert (await client.post("/register", data={"email": "bad@example.com", "password": "correct horse battery staple"})).status_code == 403
        response = await client.post(
            "/register",
            data={"csrf": csrf_from(page), "email": "bob@example.com", "password": "correct horse battery staple"},
            follow_redirects=True,
        )
        csrf = csrf_from(response)
        response = await client.post("/keys", data={"csrf": csrf, "label": "Temporária"})
        route_key = re.search(r"rm_live_[A-Za-z0-9_-]+", response.text).group(0)  # type: ignore[union-attr]
        key_id = database.list_api_keys(1)[0]["id"]
        csrf = csrf_from(response)
        await client.post(f"/keys/{key_id}/revoke", data={"csrf": csrf})
        denied = await client.post(
            "/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {route_key}"},
            json={"messages": [{"role": "user", "content": "Olá"}]},
        )
        assert denied.status_code == 401
    finally:
        await client.aclose()
        get_settings.cache_clear()


def test_api_keys_are_isolated_per_user(tmp_path):
    database = Database(str(tmp_path / "isolation.db"))
    database.initialize()
    auth = AuthService(database, "isolated-secret-with-at-least-32-characters")
    alice = auth.register("alice@example.com", "alice-secure-password")
    bob = auth.register("bob@example.com", "bob-secure-password")
    database.set_openrouter_key(alice.id, auth.encrypt_openrouter_key("sk-or-v1-alice-key"))
    database.set_openrouter_key(bob.id, auth.encrypt_openrouter_key("sk-or-v1-bob-key"))
    alice_route_key = auth.issue_api_key(alice.id, "Alice")
    bob_route_key = auth.issue_api_key(bob.id, "Bob")

    resolved_alice = auth.authenticate_api_key(alice_route_key)
    resolved_bob = auth.authenticate_api_key(bob_route_key)
    assert resolved_alice and auth.decrypt_openrouter_key(resolved_alice) == "sk-or-v1-alice-key"
    assert resolved_bob and auth.decrypt_openrouter_key(resolved_bob) == "sk-or-v1-bob-key"
    assert auth.authenticate_api_key("rm_live_unknown_but_long_enough_to_validate") is None


async def test_api_rejects_account_without_openrouter_key(monkeypatch, tmp_path):
    secret = "missing-key-secret-with-at-least-32-characters"
    monkeypatch.setenv("ROUTEMIND_SECRET_KEY", secret)
    monkeypatch.setenv("ROUTEMIND_ENVIRONMENT", "development")
    monkeypatch.setenv("ROUTEMIND_SECURE_COOKIES", "false")
    get_settings.cache_clear()
    database = Database(str(tmp_path / "missing-key.db"))
    database.initialize()
    auth = AuthService(database, secret)
    user = auth.register("missing@example.com", "missing-secure-password")
    route_key = auth.issue_api_key(user.id, "Sem OpenRouter")
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(FakeOpenRouter([model("free/model")]), database)),
        base_url="http://test",
    )
    try:
        response = await client.post(
            "/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {route_key}"},
            json={"messages": [{"role": "user", "content": "Olá"}]},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "openrouter_key_missing"
    finally:
        await client.aclose()
        get_settings.cache_clear()
