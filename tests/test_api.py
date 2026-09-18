import httpx

from conftest import TEST_OPENROUTER_KEY, TEST_ROUTE_KEY, model

HEADERS = {"Authorization": f"Bearer {TEST_ROUTE_KEY}"}


async def test_free_default_and_unknown_fields_preserved(make_client):
    client, upstream = make_client([model("free/model"), model("paid/model", "0.001", "0.002")])
    response = await client.post("/api/v1/chat/completions", headers=HEADERS, json={"messages": [{"role": "user", "content": "hello"}], "future_parameter": {"x": 1}})
    assert response.status_code == 200
    assert upstream.payloads[0]["model"] == "free/model"
    assert upstream.payloads[0]["future_parameter"] == {"x": 1}
    assert "routemind" not in upstream.payloads[0]
    assert upstream.upstream_keys == [TEST_OPENROUTER_KEY, TEST_OPENROUTER_KEY]


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


async def test_restricted_free_model_falls_back_to_free_router_and_is_quarantined(make_client):
    restricted = model("thinkingmachines/restricted:free")
    restricted["description"] = "general assistant"
    free_router = model("openrouter/free")
    free_router["description"] = "random free router"
    responses = [
        httpx.Response(403, json={"error": {"code": 403, "message": "only available on agentic harnesses"}}),
        httpx.Response(200, json={"id": "ok", "choices": [{"message": {"role": "assistant", "content": "OK"}}], "usage": {"cost": 0}}),
    ]
    client, upstream = make_client([restricted, free_router], responses)
    body = {"messages": [{"role": "user", "content": "hello"}]}

    response = await client.post("/api/v1/chat/completions", headers=HEADERS, json=body)
    assert response.status_code == 200
    assert [item["model"] for item in upstream.payloads] == ["thinkingmachines/restricted:free", "openrouter/free"]

    second = await client.post("/api/v1/chat/completions", headers=HEADERS, json=body)
    assert second.status_code == 200
    assert upstream.payloads[-1]["model"] == "openrouter/free"


async def test_explicit_model_does_not_fallback_on_403(make_client):
    responses = [httpx.Response(403, json={"error": {"message": "forbidden"}})]
    client, upstream = make_client([model("free/explicit"), model("openrouter/free")], responses)
    response = await client.post(
        "/api/v1/chat/completions",
        headers=HEADERS,
        json={"model": "free/explicit", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 403
    assert len(upstream.payloads) == 1


async def test_successful_empty_completion_is_not_retried(make_client):
    responses = [httpx.Response(200, json={"id": "ok", "choices": [{"message": {"content": None}}], "usage": {"cost": 0}})]
    client, upstream = make_client([model("free/a"), model("openrouter/free")], responses)
    response = await client.post("/api/v1/chat/completions", headers=HEADERS, json={"messages": [{"role": "user", "content": "hello"}]})
    assert response.status_code == 200
    assert len(upstream.payloads) == 1


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


async def test_request_metrics_record_success_error_model_tokens_and_time(make_client):
    responses = [
        httpx.Response(200, json={
            "id": "ok",
            "model": "free/a",
            "choices": [],
            "usage": {"prompt_tokens": 11, "completion_tokens": 13, "total_tokens": 24},
        })
    ]
    client, _ = make_client([model("free/a")], responses)

    success = await client.post(
        "/api/v1/chat/completions",
        headers=HEADERS,
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    error = await client.post(
        "/api/v1/chat/completions",
        headers=HEADERS,
        json={"messages": []},
    )

    assert success.status_code == 200
    assert error.status_code == 400
    database = client.routemind_database
    summary = database.request_summary(1)
    assert summary["total"] == 2
    assert summary["successful"] == 1
    assert summary["failed"] == 1
    assert summary["total_tokens"] == 24
    rows = database.list_request_logs(1)
    successful = next(row for row in rows if row["success"])
    assert successful["model"] == "free/a"
    assert successful["prompt_tokens"] == 11
    assert successful["completion_tokens"] == 13
    assert successful["total_tokens"] == 24
    assert successful["response_time_ms"] >= 0


async def test_stream_metrics_are_recorded_after_stream_finishes(make_client):
    client, _ = make_client([model("free/a")])
    async with client.stream(
        "POST",
        "/api/v1/chat/completions",
        headers=HEADERS,
        json={"messages": [{"role": "user", "content": "hello"}], "stream": True},
    ) as response:
        _ = b"".join([chunk async for chunk in response.aiter_bytes()])

    row = client.routemind_database.list_request_logs(1)[0]
    assert row["success"] is True
    assert row["model"] == "free/a"
    assert row["prompt_tokens"] == 5
    assert row["completion_tokens"] == 7
    assert row["total_tokens"] == 12
