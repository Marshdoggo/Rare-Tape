"""Typed boundaries between portfolio component selection and accounting.

A definition is user intent, a resolver owns the sleeve methodology, and a
resolved component is the immutable evidence consumed by portfolio accounting.
This keeps the top-level engine from rebuilding category or index returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Protocol, Sequence

import pandas as pd


ComponentKind = Literal["full_market", "category_index", "individual_asset", "category_strategy"]


@dataclass(frozen=True)
class ComponentDefinition:
    component_id: str
    component_type: ComponentKind
    label: str
    target_weight: float
    reference: str | None = None
    internal_method: str = "Direct position"
    parameters: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolutionContext:
    """Point-in-time inputs supplied to resolvers, never to accounting."""

    as_of_cutoff: pd.Timestamp | str | None = None
    assets: pd.DataFrame | None = None
    observations: pd.DataFrame | None = None
    exits: pd.DataFrame | None = None


@dataclass(frozen=True)
class ResolvedComponent:
    """A sleeve's own levels and dated, canonical-asset look-through weights."""

    definition: ComponentDefinition
    series: pd.DataFrame
    constituents: pd.DataFrame = field(default_factory=pd.DataFrame)
    methodology: Mapping[str, object] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def component_id(self) -> str:
        return self.definition.component_id

    @property
    def component_type(self) -> ComponentKind:
        return self.definition.component_type

    @property
    def label(self) -> str:
        return self.definition.label

    @property
    def target_weight(self) -> float:
        return self.definition.target_weight

    @property
    def internal_method(self) -> str:
        return self.definition.internal_method


class ComponentResolver(Protocol):
    """Methodology-specific adapter from intent to auditable sleeve evidence."""

    def supports(self, definition: ComponentDefinition) -> bool: ...

    def resolve(self, definition: ComponentDefinition, context: ResolutionContext) -> ResolvedComponent: ...


def resolve_components(
    definitions: Sequence[ComponentDefinition],
    resolvers: Sequence[ComponentResolver],
    context: ResolutionContext | None = None,
) -> tuple[ResolvedComponent, ...]:
    """Resolve each definition exactly once with an unambiguous owner."""

    resolved = []
    context = context or ResolutionContext()
    for definition in definitions:
        matches = [resolver for resolver in resolvers if resolver.supports(definition)]
        if len(matches) != 1:
            raise ValueError(
                f"Component {definition.component_id!r} requires exactly one resolver; found {len(matches)}."
            )
        resolved.append(matches[0].resolve(definition, context))
    return tuple(resolved)


def _dated_constituents(frame: pd.DataFrame, cutoff: object | None) -> pd.DataFrame:
    required = {"date", "asset_id", "portfolio_weight"}
    if frame.empty or not required.issubset(frame):
        return pd.DataFrame(columns=["date", "asset_id", "portfolio_weight"])
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    out["portfolio_weight"] = pd.to_numeric(out["portfolio_weight"], errors="coerce")
    out = out.dropna(subset=["date", "asset_id", "portfolio_weight"])
    if cutoff is not None:
        out = out[out["date"] <= pd.Timestamp(cutoff).normalize()]
    return out.sort_values(["date", "asset_id"]).drop_duplicates(["date", "asset_id"], keep="last")


class CanonicalIndexResolver:
    """Resolve canonical full-market and category sleeves from committed outputs."""

    def __init__(self, series: pd.DataFrame, constituents: pd.DataFrame):
        self.series = series
        self.constituents = constituents

    def supports(self, definition: ComponentDefinition) -> bool:
        return definition.component_type in ("full_market", "category_index")

    def _filter(self, frame: pd.DataFrame, definition: ComponentDefinition) -> pd.DataFrame:
        out = frame.copy()
        expected_universe = "full_market" if definition.component_type == "full_market" else "category"
        if "universe" in out:
            out = out[out["universe"].astype(str).eq(expected_universe)]
        if "category" in out and definition.component_type == "category_index":
            out = out[out["category"].astype(str).str.casefold().eq(str(definition.reference).casefold())]
        filters = {"weighting_method": definition.internal_method, **dict(definition.parameters)}
        for column, value in filters.items():
            if column in out and value is not None:
                out = out[out[column].astype(str).eq(str(value))]
        return out

    def resolve(self, definition: ComponentDefinition, context: ResolutionContext) -> ResolvedComponent:
        series = self._filter(self.series, definition)
        series["date"] = pd.to_datetime(series["date"], errors="coerce").dt.normalize()
        if context.as_of_cutoff is not None:
            series = series[series["date"] <= pd.Timestamp(context.as_of_cutoff).normalize()]
        series = series.sort_values("date").drop_duplicates("date", keep="last")
        constituents = _dated_constituents(self._filter(self.constituents, definition), context.as_of_cutoff)
        return ResolvedComponent(
            definition, series, constituents,
            {"resolver": type(self).__name__, "internal_method": definition.internal_method},
        )


class DirectAssetResolver:
    """Resolve a direct asset without turning it into an index methodology."""

    def supports(self, definition: ComponentDefinition) -> bool:
        return definition.component_type == "individual_asset"

    def resolve(self, definition: ComponentDefinition, context: ResolutionContext) -> ResolvedComponent:
        if context.observations is None:
            raise ValueError("Direct assets require observations in ResolutionContext.")
        from alt_asset_explorer.portfolio_lab import resolve_canonical_history

        asset_id = definition.reference or definition.component_id.removeprefix("asset:")
        history = resolve_canonical_history(context.observations, [asset_id], as_of_cutoff=context.as_of_cutoff)
        rows = history.canonical_rows.copy()
        price = pd.to_numeric(rows.get("price_per_share"), errors="coerce")
        series = pd.DataFrame({
            "date": rows.get("canonical_period"),
            "available_at": rows.get("available_at"),
            "index_level": price,
        }).dropna(subset=["date", "available_at", "index_level"])
        constituents = pd.DataFrame({"date": series["date"], "asset_id": asset_id, "portfolio_weight": 1.0})
        return ResolvedComponent(definition, series, constituents, {"resolver": type(self).__name__, "price_policy": "canonical_no_fill"})


class CategoryStrategyResolver:
    """Delegate category sleeve internals to the existing strategy simulator."""

    def supports(self, definition: ComponentDefinition) -> bool:
        return definition.component_type == "category_strategy"

    def resolve(self, definition: ComponentDefinition, context: ResolutionContext) -> ResolvedComponent:
        if context.assets is None or context.observations is None:
            raise ValueError("Category strategies require assets and observations in ResolutionContext.")
        from alt_asset_explorer.category_strategy import CategoryStrategyDefinition, simulate_category_strategy

        allowed = set(CategoryStrategyDefinition.__dataclass_fields__)
        kwargs: dict[str, Any] = {k: v for k, v in definition.parameters.items() if k in allowed}
        kwargs.setdefault("category", definition.reference or "")
        result = simulate_category_strategy(
            CategoryStrategyDefinition(**kwargs), context.assets, context.observations, context.exits,
            as_of_cutoff=context.as_of_cutoff,
        )
        constituents = result.constituents.rename(columns={"portfolio_weight": "portfolio_weight"})
        return ResolvedComponent(
            definition, result.series, constituents,
            {"resolver": type(self).__name__, "strategy_definition": result.definition}, result.warnings,
        )
