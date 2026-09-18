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
from app.services.usage_tracker import record_usage

router = APIRouter()
RETRYABLE_UNBILLED_STATUSES = {404, 429, 502, 503}


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


@router.post("/api/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RouteMindError(400, "Request body must be valid JSON", "invalid_request") from exc
    payload, options = _validate_payload(body)
    requirements = classify(payload, options.task_type)
    models = await request.app.state.catalog.get_models()
    candidates = rank_models(models, payload, options, requirements, request.app.state.settings.default_output_tokens)
    attempt_limit = request.app.state.settings.max_fallback_attempts if options.fallback_enabled else 1
    attempts = candidates[:attempt_limit]
    if payload.get("stream") is True:
        return await _stream_completion(request, payload, attempts)

    last_response = None
    for candidate in attempts:
        upstream_payload = {**payload, "model": candidate.model["id"]}
        try:
            response = await request.app.state.openrouter.complete(upstream_payload)
        except httpx.TimeoutException as exc:
            raise RouteMindError(504, "OpenRouter request timed out", "upstream_timeout") from exc
        except httpx.HTTPError as exc:
            raise RouteMindError(502, "Could not reach OpenRouter", "upstream_error") from exc
        last_response = response
        if response.status_code not in RETRYABLE_UNBILLED_STATUSES:
            if response.is_success:
                try:
                    response_json = response.json()
                except ValueError:
                    response_json = None
                record_usage(candidate.model["id"], candidate.estimate.usd, response_json)
            return _upstream_response(response)
    assert last_response is not None
    return _upstream_response(last_response)


async def _stream_completion(request: Request, payload: dict[str, Any], attempts: list[Candidate]) -> Response:
    last_response = None
    for candidate in attempts:
        upstream_payload = {**payload, "model": candidate.model["id"]}
        try:
            response, iterator = await request.app.state.openrouter.stream(upstream_payload)
        except httpx.TimeoutException as exc:
            raise RouteMindError(504, "OpenRouter request timed out", "upstream_timeout") from exc
        except httpx.HTTPError as exc:
            raise RouteMindError(502, "Could not reach OpenRouter", "upstream_error") from exc
        last_response = response
        if response.status_code in RETRYABLE_UNBILLED_STATUSES:
            await response.aclose()
            continue
        if not response.is_success:
            content = await response.aread()
            await response.aclose()
            return Response(content=content, status_code=response.status_code, media_type=response.headers.get("content-type"))

        async def relay():
            try:
                async for chunk in iterator:
                    yield chunk
            finally:
                await response.aclose()

        return StreamingResponse(relay(), status_code=response.status_code, media_type="text/event-stream")
    assert last_response is not None
    content = await last_response.aread()
    await last_response.aclose()
    return Response(content=content, status_code=last_response.status_code, media_type=last_response.headers.get("content-type"))


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
