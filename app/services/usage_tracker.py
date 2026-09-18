import logging
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger("routemind.usage")


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
