"""Canonical index adapters used by the Portfolio Construction Laboratory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

import pandas as pd


CANONICAL_INDEX_FREQUENCY = "quarterly"
INDEX_CONSTITUENT_REQUIRED_COLUMNS = {
    "asset_id",
    "category",
    "date",
    "portfolio_weight",
    "universe_scope",
    "weighting_method",
}

# Phase 0 deliberately reads the authored normalized contracts rather than one
# of the several derived price/index shapes used by the application.
NORMALIZED_ASSET_COLUMNS = (
    "asset_id", "ticker", "asset_name", "category", "subcategory", "status",
    "shares_outstanding", "offering_date", "offering_price_per_share",
    "offering_market_cap", "first_trade_date", "exit_date",
    "exit_price_per_share", "exit_value_total", "exit_type", "source_reference",
    "verified_at", "notes", "rally_url", "currency",
    "implied_offering_market_cap", "warning_reason",
)
NORMALIZED_OBSERVATION_COLUMNS = (
    "asset_id", "period_end", "observed_at", "price_per_share", "market_cap",
    "event_type", "source_type", "source_reference", "collected_at", "researcher",
    "precision_status", "notes", "volume", "frequency", "implied_market_cap",
    "warning_reason",
)

CanonicalFrequency = Literal["quarterly"]
CanonicalCollisionPolicy = Literal["latest_available_observation"]
MissingPeriodPolicy = Literal["no_fill"]
CarryPolicy = Literal["none", "carry_last_observation"]
HistoryAlignmentPolicy = Literal["intersection", "union"]


@dataclass(frozen=True)
class AlignmentPolicy:
    """Explicit rules for turning dated evidence into an aligned research panel.

    Carrying is deliberately opt-in.  The production default is an intersection
    of genuinely observed canonical periods with neither interpolation nor
    last-observation carry.
    """

    periods: HistoryAlignmentPolicy = "intersection"
    missing_periods: MissingPeriodPolicy = "no_fill"
    carry: CarryPolicy = "none"

    def __post_init__(self) -> None:
        if self.periods not in ("intersection", "union"):
            raise ValueError("Alignment periods must be 'intersection' or 'union'.")
        if self.missing_periods != "no_fill":
            raise ValueError("Only the explicit no_fill missing-period policy is supported.")
        if self.carry != "none":
            raise ValueError("Observation carry is not supported; use carry='none'.")


@dataclass(frozen=True)
class CanonicalHistoryResult:
    """Auditable history resolution with source evidence kept separately."""

    source_rows: pd.DataFrame
    canonical_rows: pd.DataFrame
    excluded_rows: pd.DataFrame
    as_of_cutoff: pd.Timestamp | None
    collision_policy: CanonicalCollisionPolicy
    missing_period_policy: MissingPeriodPolicy = "no_fill"
    carry_policy: CarryPolicy = "none"


CANONICAL_AUDIT_COLUMNS = (
    "source_observed_at",
    "canonical_period",
    "available_at",
)


def resolve_canonical_history(
    observations: pd.DataFrame,
    selected_asset_ids: Sequence[str] | None = None,
    *,
    as_of_cutoff: pd.Timestamp | str | None = None,
    frequency: CanonicalFrequency = "quarterly",
    collision_policy: CanonicalCollisionPolicy = "latest_available_observation",
    alignment_policy: AlignmentPolicy | None = None,
) -> CanonicalHistoryResult:
    """Resolve authored observations into one row per asset/canonical period.

    ``source_rows`` is a deep copy with the exact input columns, values, order,
    and index.  Normalized audit dates are added only to ``canonical_rows`` and
    ``excluded_rows``.  An as-of cutoff is applied to the real observation date
    (the information-availability date), never to the canonical period label.
    Consequently a quote assigned back to an earlier quarter cannot enter an
    as-of view before it was actually observed.
    """

    required = {"asset_id", "period_end", "observed_at", "frequency"}
    missing = sorted(required.difference(observations.columns))
    if missing:
        raise ValueError(f"Canonical history requires columns {missing}.")
    if frequency != CANONICAL_INDEX_FREQUENCY:
        raise ValueError("Only canonical quarterly history is currently supported.")
    if collision_policy != "latest_available_observation":
        raise ValueError("Only latest_available_observation collision resolution is supported.")
    policy = alignment_policy or AlignmentPolicy()
    # Constructing the policy validates the no-fill/no-carry contract even
    # though alignment itself is performed by ``align_canonical_history``.
    if policy.missing_periods != "no_fill" or policy.carry != "none":
        raise ValueError("Canonical history requires no_fill with carry='none'.")

    source = observations.copy(deep=True)
    work = observations.copy(deep=True)
    work["_resolver_row_id"] = range(len(work))
    if selected_asset_ids is not None:
        selected = set(dict.fromkeys(str(value) for value in selected_asset_ids))
        work = work[work["asset_id"].astype(str).isin(selected)].copy()
    work["source_observed_at"] = pd.to_datetime(work["observed_at"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    work["canonical_period"] = pd.to_datetime(work["period_end"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    work["available_at"] = work["source_observed_at"]

    eligible = work["frequency"].astype("string").str.strip().str.lower().eq(frequency)
    eligible &= work["source_observed_at"].notna() & work["canonical_period"].notna()
    cutoff = None
    if as_of_cutoff is not None:
        cutoff = pd.Timestamp(as_of_cutoff)
        if cutoff.tzinfo is not None:
            cutoff = cutoff.tz_convert(None)
        cutoff = cutoff.normalize()
        eligible &= work["available_at"].le(cutoff)

    candidates = work[eligible].copy()
    candidates["_source_order"] = range(len(candidates))
    candidates = candidates.sort_values(
        ["asset_id", "canonical_period", "available_at", "_source_order"], kind="stable"
    )
    winners = candidates.drop_duplicates(["asset_id", "canonical_period"], keep="last")
    winner_ids = set(winners["_resolver_row_id"])
    excluded = work[~work["_resolver_row_id"].isin(winner_ids)].copy()
    excluded["exclusion_reason"] = "not_canonical_frequency_or_invalid_date"
    after_cutoff = eligible.copy()
    if cutoff is not None:
        after_cutoff = (
            work["frequency"].astype("string").str.strip().str.lower().eq(frequency)
            & work["available_at"].gt(cutoff)
        )
        cutoff_ids = set(work.loc[after_cutoff, "_resolver_row_id"])
        excluded.loc[excluded["_resolver_row_id"].isin(cutoff_ids), "exclusion_reason"] = "after_availability_cutoff"
    collision_losers = set(candidates["_resolver_row_id"]).difference(winner_ids)
    excluded.loc[excluded["_resolver_row_id"].isin(collision_losers), "exclusion_reason"] = "canonical_period_collision"
    excluded = excluded.drop(columns="_resolver_row_id")
    winners = winners.drop(columns=["_source_order", "_resolver_row_id"]).sort_values(["canonical_period", "asset_id"], kind="stable")
    return CanonicalHistoryResult(
        source_rows=source,
        canonical_rows=winners,
        excluded_rows=excluded,
        as_of_cutoff=cutoff,
        collision_policy=collision_policy,
    )


def build_eligibility_timeline(
    history: CanonicalHistoryResult,
    selected_asset_ids: Sequence[str],
    *,
    alignment_policy: AlignmentPolicy | None = None,
) -> pd.DataFrame:
    """Return asset/period eligibility without manufacturing observations."""

    policy = alignment_policy or AlignmentPolicy()
    ids = tuple(dict.fromkeys(str(value) for value in selected_asset_ids))
    canonical = history.canonical_rows
    periods_by_asset = {
        asset_id: set(canonical.loc[canonical["asset_id"].astype(str).eq(asset_id), "canonical_period"])
        for asset_id in ids
    }
    if not ids:
        periods: list[pd.Timestamp] = []
    elif policy.periods == "intersection":
        periods = sorted(set.intersection(*(periods_by_asset[value] for value in ids)))
    else:
        periods = sorted(set.union(*(periods_by_asset[value] for value in ids)))
    panel_periods = sorted(set().union(*periods_by_asset.values())) if ids else []
    rows = []
    aligned = set(periods)
    for period in panel_periods:
        for asset_id in ids:
            observed = period in periods_by_asset[asset_id]
            match = canonical[
                canonical["asset_id"].astype(str).eq(asset_id)
                & canonical["canonical_period"].eq(period)
            ]
            source_observed_at = match["source_observed_at"].iloc[0] if observed else pd.NaT
            if not observed:
                reason = "missing_observation_no_fill"
            elif period not in aligned:
                reason = "excluded_by_intersection"
            else:
                reason = "observed"
            rows.append({
                "asset_id": asset_id,
                "canonical_period": period,
                "source_observed_at": source_observed_at,
                "available_at": source_observed_at,
                "eligible": observed and period in aligned,
                "has_observation": observed,
                "eligibility_reason": reason,
                "alignment_policy": policy.periods,
                "missing_period_policy": policy.missing_periods,
                "carry_policy": policy.carry,
            })
    return pd.DataFrame(rows, columns=[
        "asset_id", "canonical_period", "source_observed_at", "available_at", "eligible", "has_observation",
        "eligibility_reason", "alignment_policy", "missing_period_policy", "carry_policy",
    ])


def align_canonical_history(
    history: CanonicalHistoryResult,
    selected_asset_ids: Sequence[str],
    *,
    alignment_policy: AlignmentPolicy | None = None,
) -> pd.DataFrame:
    """Compatibility-friendly wide panel; values exist only where sourced."""

    policy = alignment_policy or AlignmentPolicy()
    ids = tuple(dict.fromkeys(str(value) for value in selected_asset_ids))
    timeline = build_eligibility_timeline(history, ids, alignment_policy=policy)
    periods = timeline.loc[timeline["eligible"], "canonical_period"].drop_duplicates().sort_values()
    canonical = history.canonical_rows
    value_column = "price_per_share" if "price_per_share" in canonical else "index_level"
    panel = canonical[canonical["asset_id"].astype(str).isin(ids)].pivot(
        index="canonical_period", columns="asset_id", values=value_column
    )
    return panel.reindex(index=periods, columns=list(ids))


def component_series_compatibility_adapter(
    canonical_rows: pd.DataFrame,
    *,
    value_column: str = "price_per_share",
) -> pd.DataFrame:
    """Adapt canonical history to the legacy ``date/index_level`` component shape.

    This adapter is intentionally narrow and temporary.  It retains the audit
    dates alongside the old names so migrated callers can stop treating a
    canonical period as though it were the source quote timestamp.
    """

    required = {"canonical_period", "source_observed_at", value_column}
    missing = sorted(required.difference(canonical_rows.columns))
    if missing:
        raise ValueError(f"Component history adapter requires columns {missing}.")
    adapted = canonical_rows.copy(deep=True)
    adapted["date"] = adapted["canonical_period"]
    adapted["index_level"] = pd.to_numeric(adapted[value_column], errors="coerce")
    return adapted


@dataclass(frozen=True)
class PortfolioPhaseZeroDiagnostic:
    """Auditable selection/alignment facts before a portfolio is simulated.

    ``observed_dates`` retain real quote dates. ``canonical_periods`` are a
    separate, quarterly research alignment and must not be described as quotes
    observed on those dates.
    """

    selected_asset_ids: tuple[str, ...]
    resolved_asset_ids: tuple[str, ...]
    missing_asset_ids: tuple[str, ...]
    observed_date_intersection: tuple[pd.Timestamp, ...]
    canonical_period_intersection: tuple[pd.Timestamp, ...]
    launch_ranges: pd.DataFrame
    raw_observation_rows: int
    unique_observation_rows: int
    duplicate_observation_rows_removed: int
    raw_canonical_rows: int
    unique_canonical_rows: int
    duplicate_canonical_rows_removed: int


def _assert_exact_columns(frame: pd.DataFrame, expected: tuple[str, ...], source: str) -> None:
    actual = tuple(str(column) for column in frame.columns)
    if actual != expected:
        missing = sorted(set(expected).difference(actual))
        extra = sorted(set(actual).difference(expected))
        raise ValueError(
            f"Invalid {source} schema: expected exact columns {list(expected)}; "
            f"actual columns {list(actual)}; missing {missing}; extra {extra}."
        )


def build_phase_zero_diagnostic(
    assets: pd.DataFrame,
    observations: pd.DataFrame,
    selected_asset_ids: Sequence[str],
) -> PortfolioPhaseZeroDiagnostic:
    """Resolve a selection and report its no-fill production-data alignment.

    Repeated requested IDs are collapsed in first-seen order. Exact duplicate
    observations (same asset and ``observed_at``) keep the last committed row.
    Quarterly collisions (same asset and ``period_end``) independently keep the
    latest actual ``observed_at``. Thus an offering and a later chart quote in
    one canonical quarter produce one canonical value without erasing either
    item of dated source evidence.
    """

    _assert_exact_columns(assets, NORMALIZED_ASSET_COLUMNS, "normalized asset")
    _assert_exact_columns(observations, NORMALIZED_OBSERVATION_COLUMNS, "normalized observation")
    selected = tuple(dict.fromkeys(str(value) for value in selected_asset_ids))
    available = set(assets["asset_id"].dropna().astype(str))
    resolved = tuple(asset_id for asset_id in selected if asset_id in available)
    missing = tuple(asset_id for asset_id in selected if asset_id not in available)

    selected_rows = observations[observations["asset_id"].astype(str).isin(resolved)].copy()
    selected_rows["observed_at"] = pd.to_datetime(selected_rows["observed_at"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    selected_rows["period_end"] = pd.to_datetime(selected_rows["period_end"], errors="coerce").dt.normalize()
    selected_rows = selected_rows.dropna(subset=["observed_at"])
    raw_observation_rows = len(selected_rows)
    observed = selected_rows.drop_duplicates(["asset_id", "observed_at"], keep="last")

    quarterly = observed[observed["frequency"].astype(str).str.lower().eq(CANONICAL_INDEX_FREQUENCY)].copy()
    raw_canonical_rows = len(quarterly)
    quarterly = quarterly.sort_values(["asset_id", "period_end", "observed_at"], kind="stable")
    canonical = quarterly.dropna(subset=["period_end"]).drop_duplicates(["asset_id", "period_end"], keep="last")

    def intersection(frame: pd.DataFrame, column: str) -> tuple[pd.Timestamp, ...]:
        if not resolved:
            return ()
        values = [set(frame.loc[frame["asset_id"].astype(str).eq(asset_id), column]) for asset_id in resolved]
        return tuple(sorted(set.intersection(*values))) if values else ()

    ranges = []
    for asset_id in resolved:
        dated = observed[observed["asset_id"].astype(str).eq(asset_id)]
        periods = canonical[canonical["asset_id"].astype(str).eq(asset_id)]
        ranges.append({
            "asset_id": asset_id,
            "first_observed_at": dated["observed_at"].min(),
            "last_observed_at": dated["observed_at"].max(),
            "first_canonical_period": periods["period_end"].min(),
            "last_canonical_period": periods["period_end"].max(),
        })
    launch_ranges = pd.DataFrame(ranges, columns=[
        "asset_id", "first_observed_at", "last_observed_at",
        "first_canonical_period", "last_canonical_period",
    ])
    return PortfolioPhaseZeroDiagnostic(
        selected_asset_ids=selected,
        resolved_asset_ids=resolved,
        missing_asset_ids=missing,
        observed_date_intersection=intersection(observed, "observed_at"),
        canonical_period_intersection=intersection(canonical, "period_end"),
        launch_ranges=launch_ranges,
        raw_observation_rows=raw_observation_rows,
        unique_observation_rows=len(observed),
        duplicate_observation_rows_removed=raw_observation_rows - len(observed),
        raw_canonical_rows=raw_canonical_rows,
        unique_canonical_rows=len(canonical),
        duplicate_canonical_rows_removed=raw_canonical_rows - len(canonical),
    )


def validate_index_constituent_schema(
    frame: pd.DataFrame, *, source: str = "canonical_market.total_return_constituents"
) -> None:
    """Raise a useful error when the canonical constituent contract is broken."""
    missing = sorted(INDEX_CONSTITUENT_REQUIRED_COLUMNS.difference(frame.columns))
    if missing:
        available = sorted(str(column) for column in frame.columns)
        raise ValueError(
            f"Invalid index constituent schema from {source}: missing columns {missing}; "
            f"available columns {available}."
        )


def canonical_index(
    index_portfolio: pd.DataFrame,
    index_constituents: pd.DataFrame,
    component_type: str,
    reference: str,
    method: str,
    scope: str,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Return the canonical quarterly index series and its latest constituents.

    The quarterly frequency here describes the underlying canonical index. It is
    deliberately independent from the rebalance schedule of a portfolio that
    owns this index as a sleeve.
    """
    validate_index_constituent_schema(index_constituents)
    category = "all" if component_type == "full_market" else reference
    selected = index_portfolio[
        index_portfolio["category"].astype(str).eq(category)
        & index_portfolio["weighting_method"].astype(str).eq(method)
        & index_portfolio["rebalance_frequency"].astype(str).eq(CANONICAL_INDEX_FREQUENCY)
        & index_portfolio["universe_scope"].astype(str).eq(scope)
    ].copy()
    holdings = index_constituents[
        index_constituents["category"].astype(str).eq(category)
        & index_constituents["weighting_method"].astype(str).eq(method)
        & index_constituents["universe_scope"].astype(str).eq(scope)
    ].copy()
    if holdings.empty:
        return selected, {}
    holdings["date"] = pd.to_datetime(holdings["date"], errors="coerce")
    latest = holdings[holdings["date"].eq(holdings["date"].max())].copy()
    raw = latest.groupby(latest["asset_id"].astype(str))["portfolio_weight"].sum().to_dict()
    total = sum(raw.values())
    return selected, ({key: float(value / total) for key, value in raw.items()} if total > 0 else {})
