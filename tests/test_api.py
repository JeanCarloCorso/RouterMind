import httpx

from conftest import model

HEADERS = {"Authorization": "Bearer test-key"}


async def test_free_default_and_unknown_fields_preserved(make_client):
    client, upstream = make_client([model("free/model"), model("paid/model", "0.001", "0.002")])
    response = await client.post("/api/v1/chat/completions", headers=HEADERS, json={"messages": [{"role": "user", "content": "hello"}], "future_parameter": {"x": 1}})
    assert response.status_code == 200
    assert upstream.payloads[0]["model"] == "free/model"
    assert upstream.payloads[0]["future_parameter"] == {"x": 1}
    assert "routemind" not in upstream.payloads[0]


async def test_explicit_model_is_respected(make_client):
    client, upstream = make_client([model("free/a"), model("free/b")])
    response = await client.post("/api/v1/chat/completions", headers=HEADERS, json={"model": "free/b", "messages": [{"role": "user", "content": "hello"}]})
    assert response.status_code == 200
    assert upstream.payloads[0]["model"] == "free/b"


async def test_paid_model_must_fit_request_budget(make_client):
    client, upstream = make_client([model("paid/model", "0.000001", "0.000002")])
    response = await client.post("/api/v1/chat/completions", headers=HEADERS, json={"messages": [{"role": "user", "content": "hello"}], "max_tokens": 100, "routemind": {"free_only": False, "max_cost": 0.001}})
    assert response.status_code == 200
    assert upstream.payloads[0]["model"] == "paid/model"


async def test_budget_exceeded_returns_error(make_client):
    client, _ = make_client([model("paid/model", "0.1", "0.1")])
    response = await client.post("/api/v1/chat/completions", headers=HEADERS, json={"messages": [{"role": "user", "content": "hello"}], "routemind": {"free_only": False, "max_cost": 0.001}})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_eligible_model"


async def test_capability_and_modality_filtering(make_client):
    client, upstream = make_client([model("free/text", supported=["temperature"]), model("free/vision-tools", inputs=["text", "image"])])
    content = [{"type": "text", "text": "describe"}, {"type": "image_url", "image_url": {"url": "https://example.test/a.png"}}]
    tools = [{"type": "function", "function": {"name": "weather", "parameters": {}}}]
    response = await client.post("/api/v1/chat/completions", headers=HEADERS, json={"messages": [{"role": "user", "content": content}], "tools": tools})
    assert response.status_code == 200
    assert upstream.payloads[0]["model"] == "free/vision-tools"


async def test_fallback_is_bounded(make_client):
    responses = [httpx.Response(429, json={"error": {"message": "limited"}}), httpx.Response(200, json={"id": "ok", "usage": {}})]
    client, upstream = make_client([model("free/a"), model("free/b"), model("free/c")], responses)
    response = await client.post("/api/v1/chat/completions", headers=HEADERS, json={"messages": [{"role": "user", "content": "hello"}]})
    assert response.status_code == 200
    assert len(upstream.payloads) == 2


async def test_streaming_preserves_sse(make_client):
    client, _ = make_client([model("free/a")])
    async with client.stream("POST", "/api/v1/chat/completions", headers=HEADERS, json={"messages": [{"role": "user", "content": "hello"}], "stream": True}) as response:
        body = b"".join([chunk async for chunk in response.aiter_bytes()])
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert b"data: [DONE]" in body


async def test_auth_and_validation(make_client):
    client, _ = make_client([model("free/a")])
    assert (await client.post("/api/v1/chat/completions", json={"messages": []})).status_code == 401
    assert (await client.post("/api/v1/chat/completions", headers=HEADERS, json={"messages": []})).status_code == 400
