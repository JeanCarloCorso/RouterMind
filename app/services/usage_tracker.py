import logging
import time
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger("routemind.usage")


def _token_value(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def usage_tokens(response_body: dict[str, Any] | None) -> dict[str, int | None]:
    usage = (response_body or {}).get("usage") or {}
    prompt = _token_value(usage.get("prompt_tokens"))
    completion = _token_value(usage.get("completion_tokens"))
    total = _token_value(usage.get("total_tokens"))
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def usage_cost(response_body: dict[str, Any] | None) -> Decimal | None:
    usage = (response_body or {}).get("usage") or {}
    value = usage.get("cost")
    if value is None or isinstance(value, bool):
        return None
    try:
        cost = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return cost if cost.is_finite() and cost >= 0 else None


def persist_request(
    database: Any, user_id: int, *, status_code: int, model: str | None,
    started_at: float, response_body: dict[str, Any] | None = None,
    success: bool | None = None,
) -> None:
    tokens = usage_tokens(response_body)
    cost_usd = usage_cost(response_body)
    elapsed_ms = max(0, round((time.perf_counter() - started_at) * 1000))
    try:
        database.record_request(
            user_id,
            success=(200 <= status_code < 400) if success is None else success,
            status_code=status_code,
            model=model,
            response_time_ms=elapsed_ms,
            cost_usd=cost_usd,
            **tokens,
        )
    except Exception:
        # Metrics must never turn a completed model response into an API error.
        logger.exception("request_metrics_persistence_failed", extra={"user_id": user_id})


def record_usage(model: str, estimated_cost: Decimal, response_body: dict[str, Any] | None) -> None:
    usage = (response_body or {}).get("usage") or {}
    actual = usage.get("cost")
    try:
        actual_cost = str(Decimal(str(actual))) if actual is not None else None
    except (InvalidOperation, ValueError):
        actual_cost = None
    logger.info(
        "completion_usage",
        extra={
            "selected_model": model,
            "estimated_cost_usd": str(estimated_cost),
            "actual_cost_usd": actual_cost,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        },
    )
