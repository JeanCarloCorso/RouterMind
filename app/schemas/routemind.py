from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RoutingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    free_only: bool = True
    max_cost: float = Field(default=0, ge=0, allow_inf_nan=False)
    currency: Literal["USD"] = "USD"
    task_type: str = "auto"
    preferred_models: list[str] = Field(default_factory=list)
    excluded_models: list[str] = Field(default_factory=list)
    fallback_enabled: bool = True

    @model_validator(mode="after")
    def consistent_budget(self) -> "RoutingOptions":
        if not self.free_only and self.max_cost <= 0:
            raise ValueError("max_cost must be greater than zero when free_only is false")
        overlap = set(self.preferred_models) & set(self.excluded_models)
        if overlap:
            raise ValueError(f"models cannot be both preferred and excluded: {sorted(overlap)}")
        return self
