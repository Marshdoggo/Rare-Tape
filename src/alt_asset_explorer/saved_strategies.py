"""Versioned, portable definitions for saved portfolios and strategies.

This contract is intentionally independent of ``CustomIndexDefinition``.  A saved
strategy owns point-in-time research methodology, while a custom index is only a
constant-weight presentation definition.  Keeping the documents separate avoids
silently changing the meaning of existing files in ``data/custom_indices``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, Tag, field_validator, model_validator


SAVED_STRATEGY_SCHEMA_VERSION = 1


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComponentRule(_StrictModel):
    component_id: str = Field(min_length=1, max_length=200)
    component_type: Literal["full_market", "category_index", "individual_asset", "category_strategy"]
    reference: str = Field(min_length=1, max_length=200)
    target_weight: float = Field(ge=0, le=1)
    internal_weighting: Literal["equal", "market_cap", "custom"] | None = None
    custom_constituent_weights: dict[str, float] | None = None

    @model_validator(mode="after")
    def validate_custom_weights(self) -> "ComponentRule":
        if self.internal_weighting == "custom" and not self.custom_constituent_weights:
            raise ValueError("custom internal weighting requires constituent weights")
        if self.custom_constituent_weights is not None and any(
            not asset_id or weight < 0 or weight > 1
            for asset_id, weight in self.custom_constituent_weights.items()
        ):
            raise ValueError("custom constituent weights must use nonblank IDs and values from 0 to 1")
        return self


class ExclusionRules(_StrictModel):
    asset_ids: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)


class WeightingRules(_StrictModel):
    method: Literal["equal", "market_cap", "custom", "inverse_volatility"]
    normalize_to_one: bool = True
    residual_cash: bool = False


class AlignmentRules(_StrictModel):
    calendar: Literal["intersection", "union"]
    missing_observation_policy: Literal["no_fill", "retain_position_for_accounting"] = "no_fill"
    frequency: Literal["weekly", "monthly", "quarterly", "annual"] = "quarterly"


class EligibilityRules(_StrictModel):
    universe_scope: Literal["active_only", "include_exited"]
    admission: Literal["common_inception", "point_in_time_launch"]
    require_source_observation: bool = True


class ExitRules(_StrictModel):
    treatment: Literal["exclude", "terminal_proceeds", "hold_cash"]
    pending_offer_treatment: Literal["ignore_until_realized"] = "ignore_until_realized"


class RebalanceRules(_StrictModel):
    frequency: Literal["none", "monthly", "quarterly", "annual"]
    timing: Literal["period_start", "period_end"] = "period_start"


class InSampleOptimizationResult(_StrictModel):
    result_type: Literal["in_sample"] = "in_sample"
    label: Literal["In-sample optimization (research only; not a forecast)"] = (
        "In-sample optimization (research only; not a forecast)"
    )
    objective: str = Field(min_length=1, max_length=200)
    sample_start: datetime
    sample_end: datetime
    optimized_weights: dict[str, float]
    metrics: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_period(self) -> "InSampleOptimizationResult":
        if self.sample_end < self.sample_start:
            raise ValueError("sample_end must be on or after sample_start")
        return self


class WalkForwardWindow(_StrictModel):
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    selected_weights: dict[str, float]
    out_of_sample_metrics: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_window(self) -> "WalkForwardWindow":
        if not (self.train_start <= self.train_end < self.test_start <= self.test_end):
            raise ValueError("walk-forward windows require training before a non-overlapping test period")
        return self


class WalkForwardOptimizationResult(_StrictModel):
    result_type: Literal["walk_forward"] = "walk_forward"
    label: Literal["Walk-forward optimization (historical out-of-sample research; not a forecast)"] = (
        "Walk-forward optimization (historical out-of-sample research; not a forecast)"
    )
    objective: str = Field(min_length=1, max_length=200)
    windows: list[WalkForwardWindow] = Field(min_length=1)
    aggregate_out_of_sample_metrics: dict[str, float] = Field(default_factory=dict)


OptimizationResult = Annotated[
    Annotated[InSampleOptimizationResult, Tag("in_sample")]
    | Annotated[WalkForwardOptimizationResult, Tag("walk_forward")],
    Field(discriminator="result_type"),
]


class SavedStrategyDefinition(_StrictModel):
    """Complete reproducibility contract for a saved portfolio or strategy."""

    id: str = Field(pattern=r"^strategy_[a-z0-9][a-z0-9_-]{5,90}$")
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    created_at: datetime
    updated_at: datetime
    schema_version: int = SAVED_STRATEGY_SCHEMA_VERSION
    saved_type: Literal["portfolio", "strategy"]
    component_rules: list[ComponentRule] = Field(min_length=1, max_length=200)
    exclusions: ExclusionRules
    weighting: WeightingRules
    alignment: AlignmentRules
    eligibility: EligibilityRules
    exit: ExitRules
    rebalance: RebalanceRules
    as_of_cutoff: datetime
    dataset_version: str = Field(min_length=1, max_length=200)
    methodology_version: str = Field(min_length=1, max_length=200)
    optimization_results: list[OptimizationResult] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("name cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_definition(self) -> "SavedStrategyDefinition":
        if self.schema_version != SAVED_STRATEGY_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {self.schema_version}")
        component_ids = [rule.component_id for rule in self.component_rules]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("component IDs must be unique")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be on or after created_at")
        return self
