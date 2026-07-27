"""Adapters from canonical/local Rally artifacts to correlation subject series."""

from __future__ import annotations

import pandas as pd


def collect_subjects(
    assets: pd.DataFrame,
    observations: pd.DataFrame,
    quarterly_indices: pd.DataFrame,
    total_return_indices: pd.DataFrame,
    benchmarks: pd.DataFrame,
) -> tuple[dict[str, pd.Series], pd.DataFrame]:
    series: dict[str, pd.Series] = {}
    rows: list[dict] = []
    asset_meta = (
        assets.set_index("asset_id", drop=False) if not assets.empty else pd.DataFrame()
    )
    for asset_id, group in (
        observations.groupby("asset_id") if not observations.empty else []
    ):
        if asset_id not in asset_meta.index:
            continue
        row = asset_meta.loc[asset_id]
        ticker = str(row.get("ticker", asset_id)).lstrip("#")
        values = pd.Series(
            pd.to_numeric(group["price_per_share"], errors="coerce").array,
            index=pd.to_datetime(
                group["observed_at"], errors="coerce", utc=True
            ).dt.tz_localize(None),
        )
        sid = f"asset:{asset_id}"
        series[sid] = values
        rows.append(
            _meta(sid, f"Asset · {ticker}", "Individual Rally asset", row, values)
        )
    if not quarterly_indices.empty:
        for index_id, group in quarterly_indices.groupby("index_id"):
            first = group.iloc[0]
            weighting = str(first["weighting_method"])
            category = str(first["category"])
            full = category == "all"
            kind = (
                "Full-market index"
                if full
                else (
                    "Equal-weight category index"
                    if weighting == "equal"
                    else "Market-cap-weighted category index"
                )
            )
            prefix = (
                "Full Index"
                if full
                else ("EW Index" if weighting == "equal" else "MCW Index")
            )
            label = f"{prefix} · {str(first['index_name']).replace('Rally Market ', '').replace(' Quarterly Historical Index Prototype', '') if full else category.title()}"
            values = pd.Series(
                pd.to_numeric(group["index_level"], errors="coerce").array,
                index=pd.to_datetime(group["date"], errors="coerce"),
            )
            sid = f"quarterly_index:{index_id}"
            series[sid] = values
            rows.append(
                _meta(
                    sid,
                    label,
                    kind,
                    {"category": category, "status": "research prototype"},
                    values,
                )
            )
    if not total_return_indices.empty:
        required = {
            "date",
            "index_level",
            "category",
            "weighting_method",
            "rebalance_frequency",
            "universe_scope",
        }
        if required.issubset(total_return_indices):
            selected = total_return_indices[
                total_return_indices["rebalance_frequency"].astype(str).eq("quarterly")
            ]
            for keys, group in selected.groupby(
                ["category", "weighting_method", "universe_scope"]
            ):
                category, weighting, scope = map(str, keys)
                if category != "all":
                    continue  # category variants already represented above without duplicating semantics
                sid = f"total_return:{category}:{weighting}:{scope}"
                label = f"Full Index · {'Equal Weight' if weighting == 'equal_weight' else 'Market-Cap Weight'} · {'Exit-aware' if scope == 'include_exited' else 'Survivors'}"
                values = pd.Series(
                    pd.to_numeric(group["index_level"], errors="coerce").array,
                    index=pd.to_datetime(group["date"], errors="coerce"),
                )
                series[sid] = values
                rows.append(
                    _meta(
                        sid,
                        label,
                        "Full-market index",
                        {"category": "all", "status": scope},
                        values,
                    )
                )
    if not benchmarks.empty:
        for ticker, group in benchmarks.groupby("ticker"):
            sid = f"benchmark:{ticker}"
            values = pd.Series(
                pd.to_numeric(group["adjusted_close"], errors="coerce").array,
                index=pd.to_datetime(group["date"], errors="coerce"),
            )
            series[sid] = values
            rows.append(
                _meta(
                    sid,
                    f"Benchmark · {ticker}",
                    "External benchmark",
                    {
                        "category": group.iloc[0].get("asset_class"),
                        "status": "public market",
                    },
                    values,
                )
            )
    return series, pd.DataFrame(rows)


def _meta(
    subject_id: str, label: str, subject_type: str, row, values: pd.Series
) -> dict:
    clean = values.dropna().sort_index()
    gaps = clean.index.to_series().diff().dt.days
    return {
        "subject_id": subject_id,
        "display_label": label,
        "subject_type": subject_type,
        "category": row.get("category"),
        "subcategory": row.get("subcategory"),
        "status": row.get("status"),
        "effective_start": clean.index.min() if len(clean) else pd.NaT,
        "effective_end": clean.index.max() if len(clean) else pd.NaT,
        "observation_count": len(clean),
        "median_observation_gap": gaps.median() if len(clean) > 1 else None,
        "latest_observation_date": clean.index.max() if len(clean) else pd.NaT,
        "market_cap": row.get("offering_market_cap"),
    }
