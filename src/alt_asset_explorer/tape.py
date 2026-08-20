from __future__ import annotations

import random
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import pandas as pd


OBJECT_WEIGHTS = {"asset": 0.55, "category_index": 0.30, "market_index": 0.15}
METRIC_WEIGHTS = {"qoq_return": 0.35, "yoy_return": 0.35, "latest_price": 0.20, "index_level": 0.20}


def _number(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return float(parsed) if pd.notna(parsed) else None


def _date_label(value: object, *, quarterly: bool) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    if quarterly:
        return f"As of {parsed.year}-Q{parsed.quarter}"
    return f"Through {parsed.date().isoformat()}"


def _candidate(
    *,
    label: str,
    object_id: str,
    object_type: str,
    metric_type: str,
    value: float,
    as_of: str,
    weighting: str | None,
    source_context: str,
    group_id: str,
) -> dict[str, object]:
    return {
        "candidate_id": f"{object_id}:{metric_type}",
        "label": label,
        "object_id": object_id,
        "object_type": object_type,
        "metric_type": metric_type,
        "value": value,
        "as_of": as_of,
        "weighting": weighting,
        "source_context": source_context,
        "group_id": group_id,
    }


def build_tape_candidate_pool(
    market_table: pd.DataFrame,
    quarterly_indices: pd.DataFrame,
    *,
    allowed_asset_ids: Iterable[str] | None = None,
) -> list[dict[str, object]]:
    """Normalize display-ready Tape observations without manufacturing values.

    Asset returns are consumed from the canonical market-table calculation.
    Index returns require observations in the exact previous quarter/year; gaps
    are never interpolated or replaced with a more distant observation.
    """
    candidates: list[dict[str, object]] = []
    allowed = {str(value) for value in allowed_asset_ids} if allowed_asset_ids is not None else None

    if not market_table.empty and "asset_id" in market_table:
        assets = market_table.copy()
        if "is_current_listed" in assets:
            assets = assets[assets["is_current_listed"].fillna(False)]
        if allowed is not None:
            assets = assets[assets["asset_id"].astype(str).isin(allowed)]
        for _, row in assets.drop_duplicates("asset_id").iterrows():
            object_id = str(row.get("asset_id"))
            label = str(row.get("ticker") or row.get("name") or object_id).strip()
            as_of = _date_label(row.get("last_quote_observed_at"), quarterly=False)
            if not label or not as_of:
                continue
            price = _number(row.get("last_price"))
            if price is not None and price > 0:
                candidates.append(
                    _candidate(
                        label=label,
                        object_id=object_id,
                        object_type="asset",
                        metric_type="latest_price",
                        value=price,
                        as_of=as_of,
                        weighting=None,
                        source_context="Canonical latest authored Rally share-price observation.",
                        group_id=f"asset:{object_id}",
                    )
                )
            for column, metric_type, description in (
                ("return_1q", "qoq_return", "Canonical trailing one-quarter asset return."),
                ("return_1y", "yoy_return", "Canonical trailing one-year asset return."),
            ):
                value = _number(row.get(column))
                if value is not None:
                    candidates.append(
                        _candidate(
                            label=label,
                            object_id=object_id,
                            object_type="asset",
                            metric_type=metric_type,
                            value=value,
                            as_of=as_of,
                            weighting=None,
                            source_context=description,
                            group_id=f"asset:{object_id}",
                        )
                    )

    required_index_columns = {"index_id", "date", "index_level", "weighting_method", "category"}
    if quarterly_indices.empty or not required_index_columns.issubset(quarterly_indices.columns):
        return candidates

    indices = quarterly_indices.copy()
    indices["date"] = pd.to_datetime(indices["date"], errors="coerce")
    indices["index_level"] = pd.to_numeric(indices["index_level"], errors="coerce")
    indices = indices.dropna(subset=["index_id", "date", "index_level"])
    indices = indices[indices["index_level"] > 0].sort_values(["index_id", "date"])
    for index_id, series in indices.groupby("index_id", sort=True):
        series = series.drop_duplicates("date", keep="last").copy()
        if series.empty:
            continue
        latest = series.iloc[-1]
        latest_date = pd.Timestamp(latest["date"])
        as_of = _date_label(latest_date, quarterly=True)
        if not as_of:
            continue
        category = str(latest.get("category") or "all").strip().lower()
        is_market = category == "all"
        object_type = "market_index" if is_market else "category_index"
        raw_weighting = str(latest.get("weighting_method") or "").strip().lower()
        weighting = "equal_weight" if raw_weighting in {"equal", "equal_weight"} else "market_cap_weight" if raw_weighting in {"market_cap", "market_cap_weight"} else None
        if weighting is None:
            continue
        suffix = "EW" if weighting == "equal_weight" else "MCW"
        label = f"RARE TAPE {suffix}" if is_market else f"{category.replace('_', ' ').upper()} {suffix}"
        object_id = str(index_id)
        group_id = "market:all" if is_market else f"category:{category}"
        latest_level = float(latest["index_level"])
        source = str(latest.get("data_quality_notes") or "Committed quarterly Rare Tape index artifact.")
        candidates.append(
            _candidate(
                label=label,
                object_id=object_id,
                object_type=object_type,
                metric_type="index_level",
                value=latest_level,
                as_of=as_of,
                weighting=weighting,
                source_context=source,
                group_id=group_id,
            )
        )

        levels_by_period = {
            pd.Timestamp(row["date"]).to_period("Q"): float(row["index_level"])
            for _, row in series.iterrows()
        }
        latest_period = latest_date.to_period("Q")
        for periods_back, metric_type in ((1, "qoq_return"), (4, "yoy_return")):
            base = levels_by_period.get(latest_period - periods_back)
            if base is None or base <= 0:
                continue
            candidates.append(
                _candidate(
                    label=label,
                    object_id=object_id,
                    object_type=object_type,
                    metric_type=metric_type,
                    value=latest_level / base - 1,
                    as_of=as_of,
                    weighting=weighting,
                    source_context=f"Exact calendar-period return from the committed quarterly index series. {source}",
                    group_id=group_id,
                )
            )
    return candidates


def _weighted_pick(items: Sequence[Mapping[str, object]], rng: random.Random) -> Mapping[str, object] | None:
    if not items:
        return None
    weights = [METRIC_WEIGHTS.get(str(item.get("metric_type")), 0.10) for item in items]
    return rng.choices(list(items), weights=weights, k=1)[0]


def select_tape_panel(
    candidates: Sequence[Mapping[str, object]],
    *,
    rng: random.Random,
    previous_object_ids: Iterable[str] = (),
) -> list[dict[str, object]]:
    """Select a diverse panel, degrading to however many unique items exist."""
    pool = [dict(item) for item in candidates]
    previous = {str(value) for value in previous_object_ids}
    selected: list[dict[str, object]] = []

    def eligible(types: set[str], *, avoid_previous: bool = True, vary_metric: bool = True) -> list[dict[str, object]]:
        used_objects = {str(item["object_id"]) for item in selected}
        used_groups = {str(item["group_id"]) for item in selected}
        used_labels = {str(item["label"]) for item in selected}
        used_metrics = {str(item["metric_type"]) for item in selected}
        result = [
            item for item in pool
            if str(item.get("object_type")) in types
            and str(item.get("object_id")) not in used_objects
            and str(item.get("group_id")) not in used_groups
            and str(item.get("label")) not in used_labels
            and (not avoid_previous or str(item.get("object_id")) not in previous)
        ]
        varied = [item for item in result if str(item.get("metric_type")) not in used_metrics]
        return varied if vary_metric and varied else result

    def append_from(types: set[str], *, object_type_weights: Mapping[str, float] | None = None) -> None:
        options = eligible(types)
        if not options:
            options = eligible(types, avoid_previous=False)
        if not options:
            return
        if object_type_weights:
            available_types = sorted({str(item["object_type"]) for item in options})
            chosen_type = rng.choices(
                available_types,
                weights=[object_type_weights.get(object_type, 0.01) for object_type in available_types],
                k=1,
            )[0]
            options = [item for item in options if str(item["object_type"]) == chosen_type]
        choice = _weighted_pick(options, rng)
        if choice is not None:
            selected.append(dict(choice))

    append_from({"asset"})
    append_from({"category_index", "market_index"}, object_type_weights={"category_index": 0.75, "market_index": 0.25})
    append_from(set(OBJECT_WEIGHTS), object_type_weights=OBJECT_WEIGHTS)

    while len(selected) < min(3, len({str(item.get("object_id")) for item in pool})):
        options = eligible(set(OBJECT_WEIGHTS), avoid_previous=False, vary_metric=False)
        choice = _weighted_pick(options, rng)
        if choice is None:
            break
        selected.append(dict(choice))
    return selected


def build_tape_sequence(
    candidates: Sequence[Mapping[str, object]],
    *,
    seed: int,
    panel_count: int = 30,
) -> list[list[dict[str, object]]]:
    rng = random.Random(seed)
    panels: list[list[dict[str, object]]] = []
    previous: set[str] = set()
    for _ in range(max(panel_count, 1)):
        panel = select_tape_panel(candidates, rng=rng, previous_object_ids=previous)
        if not panel:
            break
        panels.append(panel)
        previous = {str(item["object_id"]) for item in panel}
    return panels


def load_saved_tape_headlines(path: Path, *, limit: int = 40) -> list[str]:
    """Read persisted Content Lab headlines only; never invokes generation."""
    if not path.exists():
        return []
    try:
        leads = pd.read_csv(path)
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return []
    if "headline" not in leads:
        return []
    sort_columns = [column for column in ("period_end", "content_score") if column in leads]
    if sort_columns:
        leads = leads.sort_values(sort_columns, ascending=[False] * len(sort_columns), na_position="last")
    headlines: list[str] = []
    seen: set[str] = set()
    for value in leads["headline"]:
        if pd.isna(value):
            continue
        headline = str(value).strip()
        if not headline or headline in seen:
            continue
        headlines.append(headline)
        seen.add(headline)
        if len(headlines) >= limit:
            break
    return headlines
