from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.core.errors import RouteMindError
from app.schemas.routemind import RoutingOptions
from app.services.cost_estimator import CostEstimate, estimate_cost, estimate_tokens, is_free
from app.services.task_classifier import TaskRequirements


@dataclass(frozen=True)
class Candidate:
    model: dict[str, Any]
    estimate: CostEstimate
    score: tuple[Any, ...]


def _compatible(model: dict[str, Any], req: TaskRequirements, payload: dict[str, Any]) -> bool:
    architecture = model.get("architecture") or {}
    input_modalities = set(architecture.get("input_modalities") or ["text"])
    output_modalities = set(architecture.get("output_modalities") or ["text"])
    if not req.input_modalities <= input_modalities or not req.output_modalities <= output_modalities:
        return False
    supported = set(model.get("supported_parameters") or [])
    aliases = {"tools": {"tools", "tool_choice"}, "response_format": {"response_format"}, "reasoning": {"reasoning", "include_reasoning"}}
    if any(not (choices & supported) for key, choices in aliases.items() if key in req.required_parameters):
        return False
    requested_output = payload.get("max_completion_tokens")
    if requested_output is None:
        requested_output = payload.get("max_tokens")
    try:
        output_tokens = max(0, int(requested_output if requested_output is not None else 1024))
    except (TypeError, ValueError, OverflowError):
        return False
    needed_context = estimate_tokens(payload.get("messages", [])) + output_tokens
    return int(model.get("context_length") or 0) >= needed_context


def rank_models(
    models: list[dict[str, Any]], payload: dict[str, Any], options: RoutingOptions,
    requirements: TaskRequirements, default_output: int,
) -> list[Candidate]:
    by_id = {model.get("id"): model for model in models if model.get("id")}
    requested = payload.get("model")
    allowed_ids = set(by_id)
    if requested:
        allowed_ids &= {requested}
    if options.preferred_models:
        # Preferences affect ordering, not allow-list semantics.
        preferred = set(options.preferred_models)
    else:
        preferred = set()
    allowed_ids -= set(options.excluded_models)
    candidates: list[Candidate] = []
    budget = Decimal(str(options.max_cost))

    for model_id in allowed_ids:
        model = by_id[model_id]
        if not _compatible(model, requirements, payload):
            continue
        if options.free_only and not is_free(model):
            continue
        estimate = estimate_cost(payload, model, default_output)
        if estimate is None:
            continue
        if estimate.usd > budget:
            continue
        quality_hint = 0 if requirements.task_type.lower() in (model.get("description") or "").lower() else 1
        score = (0 if model_id in preferred else 1, quality_hint, estimate.usd, -int(model.get("context_length") or 0), model_id)
        candidates.append(Candidate(model, estimate, score))

    candidates.sort(key=lambda candidate: candidate.score)
    if not candidates:
        detail = "No model satisfies capabilities and the per-request cost limit"
        if requested and requested not in by_id:
            detail = f"Requested model '{requested}' is absent from the current catalog"
        raise RouteMindError(422, detail, "no_eligible_model", {"free_only": options.free_only, "max_cost_usd": options.max_cost})
    return candidates
