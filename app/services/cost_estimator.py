import json
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class CostEstimate:
    input_tokens: int
    output_tokens: int
    usd: Decimal


def estimate_tokens(value: Any) -> int:
    # Conservative model-agnostic approximation; exact tokenization varies by model.
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return max(1, math.ceil(len(serialized.encode("utf-8")) / 3))


def parse_price(value: Any) -> Decimal | None:
    try:
        price = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return price if price >= 0 else None


def estimate_cost(payload: dict[str, Any], model: dict[str, Any], default_output: int) -> CostEstimate | None:
    pricing = model.get("pricing") or {}
    prompt_price = parse_price(pricing.get("prompt"))
    completion_price = parse_price(pricing.get("completion"))
    request_price = parse_price(pricing.get("request", 0))
    if None in (prompt_price, completion_price, request_price):
        return None

    # Optional paid plugins/tools have independent pricing not represented in the model catalog.
    if payload.get("plugins"):
        return None
    input_tokens = estimate_tokens(payload.get("messages", []))
    requested_output = payload.get("max_completion_tokens")
    if requested_output is None:
        requested_output = payload.get("max_tokens")
    if requested_output is None:
        requested_output = default_output
    try:
        output_tokens = max(0, int(requested_output))
    except (TypeError, ValueError, OverflowError):
        return None
    cost = prompt_price * input_tokens + completion_price * output_tokens + request_price
    return CostEstimate(input_tokens, output_tokens, cost)


def is_free(model: dict[str, Any]) -> bool:
    pricing = model.get("pricing") or {}
    relevant = [pricing.get(key, 0) for key in ("prompt", "completion", "request", "image", "audio")]
    parsed = [parse_price(value) for value in relevant]
    return all(value is not None and value == 0 for value in parsed)
