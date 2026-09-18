import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
import httpx
from pydantic import ValidationError

from app.core.errors import RouteMindError
from app.schemas.routemind import RoutingOptions
from app.services.model_router import Candidate, rank_models
from app.services.task_classifier import classify
from app.services.usage_tracker import persist_request, record_usage

router = APIRouter()
RETRYABLE_PREGENERATION_STATUSES = {403, 404, 429, 502, 503}


def _validate_payload(body: Any) -> tuple[dict[str, Any], RoutingOptions]:
    if not isinstance(body, dict):
        raise RouteMindError(400, "Request body must be a JSON object", "invalid_request")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise RouteMindError(400, "messages is required and must be a non-empty array", "invalid_request")
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or not isinstance(message.get("role"), str) or "content" not in message:
            raise RouteMindError(400, f"messages[{index}] must contain role and content", "invalid_request")
    try:
        options = RoutingOptions.model_validate(body.get("routemind") or {})
    except ValidationError as exc:
        raise RouteMindError(400, "Invalid routemind configuration", "invalid_request", {"details": exc.errors(include_url=False)}) from exc
    payload = {key: value for key, value in body.items() if key != "routemind"}
    return payload, options


def _upstream_response(response: Any) -> Response:
    headers = {}
    for name in ("x-request-id", "openrouter-processing-ms"):
        if value := response.headers.get(name):
            headers[name] = value
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get("content-type", "application/json"),
        headers=headers,
    )


def _attempts(candidates: list[Candidate], payload: dict[str, Any], options: RoutingOptions, limit: int) -> list[Candidate]:
    selected = candidates[:limit]
    if payload.get("model") or not options.free_only or not options.fallback_enabled or limit < 2:
        return selected
    free_router = next((candidate for candidate in candidates if candidate.model["id"] == "openrouter/free"), None)
    if free_router and free_router not in selected:
        selected = [candidates[0], free_router]
    return selected


@router.post("/api/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RouteMindError(400, "Request body must be valid JSON", "invalid_request") from exc
    payload, options = _validate_payload(body)
    request.state.selected_model = payload.get("model")
    requirements = classify(payload, options.task_type)
    models = await request.app.state.catalog.get_models(request.state.user.id, request.state.openrouter_key)
    candidates = rank_models(models, payload, options, requirements, request.app.state.settings.default_output_tokens)
    attempt_limit = request.app.state.settings.max_fallback_attempts if options.fallback_enabled else 1
    attempts = _attempts(candidates, payload, options, attempt_limit)
    if payload.get("stream") is True:
        return await _stream_completion(request, payload, attempts)

    last_response = None
    for candidate in attempts:
        request.state.selected_model = candidate.model["id"]
        upstream_payload = {**payload, "model": candidate.model["id"]}
        try:
            response = await request.app.state.openrouter.complete(upstream_payload, request.state.openrouter_key)
        except httpx.TimeoutException as exc:
            raise RouteMindError(504, "OpenRouter request timed out", "upstream_timeout") from exc
        except httpx.HTTPError as exc:
            raise RouteMindError(502, "Could not reach OpenRouter", "upstream_error") from exc
        last_response = response
        if response.status_code not in RETRYABLE_PREGENERATION_STATUSES:
            try:
                response_json = response.json()
            except ValueError:
                response_json = None
            response_body = response_json if isinstance(response_json, dict) else None
            if response_body:
                request.state.usage_response_body = response_body
                if isinstance(response_body.get("model"), str):
                    request.state.selected_model = response_body["model"]
            if response.is_success:
                record_usage(candidate.model["id"], candidate.estimate.usd, response_body)
            return _upstream_response(response)
        if response.status_code == 403 and not payload.get("model"):
            request.app.state.catalog.mark_temporarily_unavailable(candidate.model["id"])
    assert last_response is not None
    return _upstream_response(last_response)


async def _stream_completion(request: Request, payload: dict[str, Any], attempts: list[Candidate]) -> Response:
    last_response = None
    for candidate in attempts:
        request.state.selected_model = candidate.model["id"]
        upstream_payload = {**payload, "model": candidate.model["id"]}
        try:
            response, iterator = await request.app.state.openrouter.stream(upstream_payload, request.state.openrouter_key)
        except httpx.TimeoutException as exc:
            raise RouteMindError(504, "OpenRouter request timed out", "upstream_timeout") from exc
        except httpx.HTTPError as exc:
            raise RouteMindError(502, "Could not reach OpenRouter", "upstream_error") from exc
        last_response = response
        if response.status_code in RETRYABLE_PREGENERATION_STATUSES:
            if response.status_code == 403 and not payload.get("model"):
                request.app.state.catalog.mark_temporarily_unavailable(candidate.model["id"])
            await response.aclose()
            continue
        if not response.is_success:
            content = await response.aread()
            await response.aclose()
            return Response(content=content, status_code=response.status_code, media_type=response.headers.get("content-type"))

        request.state.defer_request_log = True

        async def relay():
            pending = b""
            usage_body = None
            completed = False
            try:
                async for chunk in iterator:
                    pending += chunk
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        line = line.strip()
                        if not line.startswith(b"data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == b"[DONE]":
                            continue
                        try:
                            event = json.loads(data)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            continue
                        if isinstance(event, dict):
                            if isinstance(event.get("model"), str):
                                request.state.selected_model = event["model"]
                            if isinstance(event.get("usage"), dict):
                                usage_body = event
                    yield chunk
                completed = True
            finally:
                await response.aclose()
                persist_request(
                    request.app.state.database,
                    request.state.user.id,
                    api_key_id=request.state.api_key_id,
                    status_code=response.status_code if completed else 499,
                    model=getattr(request.state, "selected_model", candidate.model["id"]),
                    started_at=request.state.request_started,
                    response_body=usage_body,
                    success=completed,
                )

        return StreamingResponse(relay(), status_code=response.status_code, media_type="text/event-stream")
    assert last_response is not None
    content = await last_response.aread()
    await last_response.aclose()
    return Response(content=content, status_code=last_response.status_code, media_type=last_response.headers.get("content-type"))


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
