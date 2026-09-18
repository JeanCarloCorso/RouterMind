from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TaskRequirements:
    task_type: str
    input_modalities: frozenset[str]
    output_modalities: frozenset[str]
    required_parameters: frozenset[str]
    quality_floor: int


def classify(payload: dict[str, Any], requested_type: str = "auto") -> TaskRequirements:
    text_parts: list[str] = []
    modalities = {"text"}
    for message in payload.get("messages", []):
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") in {"image_url", "image"}:
                    modalities.add("image")
                elif part.get("type") in {"input_audio", "audio"}:
                    modalities.add("audio")
                elif part.get("type") in {"file", "input_file"}:
                    modalities.add("file")
                if isinstance(part.get("text"), str):
                    text_parts.append(part["text"])

    text = " ".join(text_parts).lower()
    task_type = requested_type
    if requested_type == "auto":
        signals = {
            "coding": ("code", "python", "javascript", "bug", "debug", "function", "stack trace"),
            "reasoning": ("prove", "reason step", "complex analysis", "derive", "logic puzzle"),
            "translation": ("translate", "traduza", "translation"),
            "summarization": ("summarize", "summary", "resuma", "sintetize"),
            "content": ("write an article", "blog post", "marketing copy", "redija"),
        }
        scores = {name: sum(term in text for term in terms) for name, terms in signals.items()}
        task_type = max(scores, key=scores.get) if max(scores.values(), default=0) else "general"

    required = set()
    if payload.get("tools"):
        required.add("tools")
    if payload.get("response_format"):
        required.add("response_format")
    if payload.get("reasoning") or payload.get("reasoning_effort"):
        required.add("reasoning")

    outputs = set(payload.get("modalities") or ["text"])
    quality_floor = 2 if task_type in {"coding", "reasoning"} else 1
    return TaskRequirements(task_type, frozenset(modalities), frozenset(outputs), frozenset(required), quality_floor)
