import re

import httpx

from app.core.config import get_settings
from app.main import create_app
from app.services.auth import AuthService
from conftest import FakeOpenRouter, MemoryDatabase, model


def csrf_from(response: httpx.Response) -> str:
    match = re.search(r"name='csrf' value='([^']+)'", response.text)
    assert match
    return match.group(1)


async def test_account_to_personal_openrouter_key_flow(monkeypatch):
    monkeypatch.setenv("ROUTEMIND_SECRET_KEY", "integration-secret-at-least-32-characters")
    monkeypatch.setenv("ROUTEMIND_ENVIRONMENT", "development")
    monkeypatch.setenv("ROUTEMIND_SECURE_COOKIES", "false")
    get_settings.cache_clear()
    database = MemoryDatabase()
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
        assert "dashboard-grid" in response.text
        assert "Salvar chave" in response.text
        assert "Excluir chave OpenRouter" not in response.text

        csrf = csrf_from(response)
        response = await client.post(
            "/openrouter-key",
            data={"csrf": csrf, "openrouter_key": "sk-or-v1-alice-personal-key"},
            follow_redirects=True,
        )
        assert "Configurada" in response.text
        assert "Excluir chave OpenRouter" in response.text
        assert "id='or-key'" not in response.text
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

        overwrite = await client.post(
            "/openrouter-key",
            data={"csrf": csrf_from(response), "openrouter_key": "sk-or-v1-should-not-overwrite"},
        )
        assert overwrite.status_code == 409
        stored_user = database.get_user(1)
        auth = AuthService(database, "integration-secret-at-least-32-characters")
        assert stored_user and auth.decrypt_openrouter_key(stored_user) == "sk-or-v1-alice-personal-key"

        missing_confirmation = await client.post(
            "/openrouter-key/delete",
            data={"csrf": csrf_from(overwrite)},
        )
        assert missing_confirmation.status_code == 400
        deleted = await client.post(
            "/openrouter-key/delete",
            data={"csrf": csrf_from(missing_confirmation), "confirm": "yes"},
            follow_redirects=True,
        )
        assert "Não configurada" in deleted.text
        assert database.get_user(1).openrouter_key_encrypted is None  # type: ignore[union-attr]

        unavailable = await client.post(
            "/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {route_key}"},
            json={"messages": [{"role": "user", "content": "Olá"}]},
        )
        assert unavailable.status_code == 403

        replaced = await client.post(
            "/openrouter-key",
            data={"csrf": csrf_from(deleted), "openrouter_key": "sk-or-v1-alice-replacement-key"},
            follow_redirects=True,
        )
        assert "Configurada" in replaced.text
        completion = await client.post(
            "/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {route_key}"},
            json={"messages": [{"role": "user", "content": "Olá novamente"}]},
        )
        assert completion.status_code == 200
        assert upstream.upstream_keys[-2:] == ["sk-or-v1-alice-replacement-key"] * 2
    finally:
        await client.aclose()
        get_settings.cache_clear()


async def test_csrf_confirmation_and_physical_key_deletion(monkeypatch):
    monkeypatch.setenv("ROUTEMIND_SECRET_KEY", "integration-secret-at-least-32-characters")
    monkeypatch.setenv("ROUTEMIND_ENVIRONMENT", "development")
    monkeypatch.setenv("ROUTEMIND_SECURE_COOKIES", "false")
    get_settings.cache_clear()
    database = MemoryDatabase()
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
        confirmation = await client.get(f"/keys/{key_id}/delete")
        assert confirmation.status_code == 200
        assert "Confirmar exclusão permanente" in confirmation.text
        assert "Esta ação é permanente" in confirmation.text
        assert len(database.list_api_keys(1)) == 1

        invalid_csrf = await client.post(f"/keys/{key_id}/delete", data={"csrf": "invalid"})
        assert invalid_csrf.status_code == 403
        assert len(database.list_api_keys(1)) == 1

        deleted = await client.post(
            f"/keys/{key_id}/delete",
            data={"csrf": csrf_from(confirmation)},
            follow_redirects=True,
        )
        assert deleted.status_code == 200
        assert "Nenhuma chave criada" in deleted.text
        assert database.list_api_keys(1) == []
        assert database.get_api_key(1, key_id) is None
        denied = await client.post(
            "/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {route_key}"},
            json={"messages": [{"role": "user", "content": "Olá"}]},
        )
        assert denied.status_code == 401
    finally:
        await client.aclose()
        get_settings.cache_clear()


def test_api_keys_are_isolated_per_user():
    database = MemoryDatabase()
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


async def test_api_rejects_account_without_openrouter_key(monkeypatch):
    secret = "missing-key-secret-with-at-least-32-characters"
    monkeypatch.setenv("ROUTEMIND_SECRET_KEY", secret)
    monkeypatch.setenv("ROUTEMIND_ENVIRONMENT", "development")
    monkeypatch.setenv("ROUTEMIND_SECURE_COOKIES", "false")
    get_settings.cache_clear()
    database = MemoryDatabase()
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
