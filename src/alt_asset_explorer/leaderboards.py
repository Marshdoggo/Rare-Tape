"""Point-in-time quarterly leaderboards over committed Rally research artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
from typing import Literal, Mapping

import pandas as pd

from .benchmark_lab import load_persisted_benchmarks
from .paths import DATA_NORMALIZED, DATA_PROCESSED
from .portfolio_analytics import portfolio_risk_metrics

METHODOLOGY_VERSION = "rally-leaderboards-v1"
# This archive is deterministic but large and binary.  Keep it in the ignored
# rebuild cache rather than making a generated Parquet file a deployment input.
ARCHIVE_PATH = DATA_PROCESSED.parent / "cache" / "quarterly_leaderboard_history.parquet"
ARCHIVE_CSV_PATH = ARCHIVE_PATH.with_suffix(".csv")
DEFAULT_STALENESS_DAYS = 186


def leaderboard_source_paths() -> list[Path]:
    """Return every committed input whose change invalidates the archive."""
    return [
        DATA_NORMALIZED / "assets.csv",
        DATA_NORMALIZED / "price_observations.csv",
        DATA_PROCESSED / "rally_quarterly_indices.csv",
        DATA_PROCESSED / "benchmark_history.parquet",
    ]


def current_source_version() -> str:
    """Fingerprint the canonical inputs used to construct leaderboards."""
    return source_fingerprint(leaderboard_source_paths())


@dataclass(frozen=True)
class LeaderboardMetric:
    key: str
    display_name: str
    description: str
    minimum_returns: int = 1
    minimum_years: float = 0.0
    direction: Literal["higher", "lower"] = "higher"
    format_style: str = "percent"
    point_in_time_compatible: bool = True
    negative_allowed: bool = True
    subject_types: tuple[str, ...] = ("Individual Rally asset", "Equal-weight category index", "Market-cap-weighted category index", "Full-market index", "External benchmark")
    missing_behavior: str = "excluded"
    annualization: str = "quarterly (4 periods/year)"


def _m(key: str, name: str, description: str, **kwargs: object) -> LeaderboardMetric:
    return LeaderboardMetric(key, name, description, **kwargs)


METRICS = {m.key: m for m in (
    _m("latest_quarter_return", "Latest quarter return", "Change from the previous quarterly as-of value."),
    _m("trailing_2q_return", "Trailing 2-quarter return", "Change over two calendar-quarter endpoints.", minimum_returns=2, minimum_years=.45),
    _m("trailing_1y_return", "Trailing 1-year return", "Change over four calendar-quarter endpoints.", minimum_returns=4, minimum_years=1),
    _m("trailing_2y_return", "Trailing 2-year return", "Change over eight calendar-quarter endpoints.", minimum_returns=8, minimum_years=2),
    _m("trailing_3y_return", "Trailing 3-year return", "Change over twelve calendar-quarter endpoints.", minimum_returns=12, minimum_years=3),
    _m("total_return", "Total return", "Change from first available value through the snapshot."),
    _m("cagr", "CAGR", "Geometric return annualized over elapsed calendar time.", minimum_years=1),
    _m("annualized_mean_return", "Annualized arithmetic mean return", "Mean quarterly return multiplied by four."),
    _m("annualized_volatility", "Annualized volatility", "Sample standard deviation of quarterly returns multiplied by sqrt(4).", minimum_returns=2, direction="lower"),
    _m("maximum_drawdown", "Maximum drawdown", "Largest point-in-time peak-to-trough decline.", direction="lower"),
    _m("downside_deviation", "Downside deviation", "Quarterly downside deviation annualized by sqrt(4).", minimum_returns=2, direction="lower"),
    _m("sharpe_ratio", "Sharpe ratio", "Annualized mean return divided by annualized volatility.", minimum_returns=2, format_style="number"),
    _m("sortino_ratio", "Sortino ratio", "Annualized mean return divided by downside deviation.", minimum_returns=2, format_style="number"),
    _m("calmar_ratio", "Calmar ratio", "CAGR divided by absolute maximum drawdown.", minimum_years=1, format_style="number"),
    _m("positive_period_percentage", "Positive-quarter percentage", "Share of valid quarterly returns above zero."),
    _m("consecutive_positive_periods", "Consecutive positive quarters", "Positive-return streak ending at the snapshot.", format_style="integer"),
    _m("best_quarter", "Best quarter", "Largest quarterly return."),
    _m("worst_quarter", "Worst quarter", "Smallest quarterly return.", direction="lower"),
    _m("median_period_return", "Median quarter return", "Median valid quarterly return."),
    _m("current_price", "Current price / index level", "Latest as-of value.", format_style="currency"),
    _m("market_cap", "Estimated market capitalization", "Latest as-of price times available canonical share count.", format_style="currency", negative_allowed=False),
    _m("offering_valuation", "Offering valuation", "Canonical authored offering market capitalization.", format_style="currency", negative_allowed=False),
    _m("premium_to_offering", "Premium / discount to offering", "Latest as-of price relative to canonical offering price."),
    _m("observation_count", "Observation count", "Valid source observations available by the snapshot.", format_style="integer", negative_allowed=False),
    _m("history_years", "History length", "Elapsed years between first and latest source observation.", format_style="number", negative_allowed=False),
    _m("observation_age_days", "Observation staleness", "Days from snapshot to latest source observation.", direction="lower", format_style="integer", negative_allowed=False),
)}


def quarter_ends(start: object, end: object) -> pd.DatetimeIndex:
    """Return calendar quarter ends in an inclusive date range."""
    start_ts, end_ts = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    return pd.date_range(start_ts.to_period("Q").end_time.normalize(), end_ts, freq="QE")


def latest_completed_quarter(as_of: object | None = None) -> pd.Timestamp:
    today = pd.Timestamp(as_of or pd.Timestamp.today()).normalize()
    current_end = today.to_period("Q").end_time.normalize()
    return current_end if today >= current_end else (today.to_period("Q") - 1).end_time.normalize()


def truncate_as_of(series: pd.Series, snapshot: object) -> pd.Series:
    values = pd.Series(pd.to_numeric(series, errors="coerce").array, index=pd.to_datetime(series.index, errors="coerce", utc=True).tz_localize(None))
    values = values[values.index.notna() & values.gt(0) & (values.index <= pd.Timestamp(snapshot))]
    return values.sort_index().groupby(level=0).last()


def quarterly_asof_series(series: pd.Series, snapshot: object, max_staleness_days: int | None = DEFAULT_STALENESS_DAYS) -> tuple[pd.Series, pd.Series]:
    source = truncate_as_of(series, snapshot)
    if source.empty:
        return pd.Series(dtype=float), pd.Series(dtype="datetime64[ns]")
    grid = quarter_ends(source.index.min(), snapshot)
    left = pd.DataFrame({"snapshot": grid})
    right = source.rename("value").rename_axis("effective_date").reset_index()
    aligned = pd.merge_asof(left, right, left_on="snapshot", right_on="effective_date", direction="backward")
    age = (aligned["snapshot"] - aligned["effective_date"]).dt.days
    if max_staleness_days is not None:
        aligned.loc[age > max_staleness_days, "value"] = math.nan
    return aligned.set_index("snapshot")["value"], aligned.set_index("snapshot")["effective_date"]


def calculate_metrics(series: pd.Series, snapshot: object, *, source_observation_count: int | None = None) -> dict[str, float]:
    values = series.dropna().sort_index()
    returns = values.pct_change(fill_method=None).dropna()
    result = {key: math.nan for key in METRICS}
    if values.empty:
        return result
    years = (values.index[-1] - values.index[0]).days / 365.25
    def trailing(periods: int) -> float:
        target = pd.Timestamp(snapshot) - pd.DateOffset(months=3 * periods)
        prior = values[values.index <= target]
        return values.iloc[-1] / prior.iloc[-1] - 1 if not prior.empty else math.nan
    result.update({
        "latest_quarter_return": returns.iloc[-1] if len(returns) else math.nan,
        "trailing_2q_return": trailing(2), "trailing_1y_return": trailing(4),
        "trailing_2y_return": trailing(8), "trailing_3y_return": trailing(12),
        "total_return": values.iloc[-1] / values.iloc[0] - 1 if len(values) > 1 else math.nan,
        "cagr": (values.iloc[-1] / values.iloc[0]) ** (1 / years) - 1 if years > 0 else math.nan,
        "annualized_mean_return": returns.mean() * 4 if len(returns) else math.nan,
        "annualized_volatility": returns.std(ddof=1) * 2 if len(returns) > 1 else math.nan,
        "maximum_drawdown": (values / values.cummax() - 1).min(),
        "downside_deviation": math.sqrt(returns.clip(upper=0).pow(2).mean()) * 2 if len(returns) else math.nan,
        "positive_period_percentage": (returns > 0).mean() if len(returns) else math.nan,
        "best_quarter": returns.max() if len(returns) else math.nan,
        "worst_quarter": returns.min() if len(returns) else math.nan,
        "median_period_return": returns.median() if len(returns) else math.nan,
        "current_price": values.iloc[-1], "observation_count": source_observation_count if source_observation_count is not None else len(values),
        "history_years": years,
    })
    streak = 0
    for value in returns.iloc[::-1]:
        if value <= 0: break
        streak += 1
    result["consecutive_positive_periods"] = streak
    analytics = portfolio_risk_metrics(pd.DataFrame({"date": values.index, "period_return": values.pct_change(fill_method=None).fillna(0)}))
    for key in ("sharpe_ratio", "sortino_ratio", "calmar_ratio"):
        result[key] = analytics.get(key, math.nan)
    return result


def rank_snapshot(frame: pd.DataFrame, metric: LeaderboardMetric) -> pd.DataFrame:
    result = frame.copy()
    valid = result["eligible"] & pd.to_numeric(result["metric_value"], errors="coerce").notna()
    ordered = result.loc[valid].sort_values(["metric_value", "subject_id"], ascending=[metric.direction == "lower", True], kind="stable")
    # Ordinal ranks make the documented ticker/id tie breaker explicit and reproducible.
    result["rank"] = pd.Series(range(1, len(ordered) + 1), index=ordered.index, dtype="Int64")
    n = len(ordered)
    result["eligible_universe_size"] = n
    result["percentile_rank"] = result["rank"].map(lambda r: 1.0 if n == 1 and pd.notna(r) else ((n-r)/(n-1) if n > 1 and pd.notna(r) else math.nan))
    return result


def source_fingerprint(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        if path.exists(): digest.update(path.name.encode()); digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def collect_leaderboard_subjects(assets: pd.DataFrame, observations: pd.DataFrame, indices: pd.DataFrame, benchmarks: pd.DataFrame) -> tuple[dict[str, pd.Series], pd.DataFrame]:
    series, rows = {}, []
    lookup = assets.set_index("asset_id", drop=False)
    for aid, group in observations.groupby("asset_id"):
        if aid not in lookup.index: continue
        meta = lookup.loc[aid]
        sid = f"asset:{aid}"
        series[sid] = pd.Series(pd.to_numeric(group.price_per_share, errors="coerce").array, index=pd.to_datetime(group.observed_at, errors="coerce", format="mixed", utc=True).dt.tz_localize(None))
        rows.append({"subject_id": sid, "subject_name": meta.get("asset_name"), "ticker": meta.get("ticker"), "subject_type": "Individual Rally asset", "category": meta.get("category"), "subcategory": meta.get("subcategory"), "current_known_status": meta.get("status"), "shares_outstanding": meta.get("shares_outstanding"), "offering_price": meta.get("offering_price_per_share"), "offering_valuation": meta.get("offering_market_cap")})
    for iid, group in indices.groupby("index_id"):
        first = group.iloc[0]; category, weighting = str(first.category), str(first.weighting_method)
        kind = "Full-market index" if category == "all" else ("Equal-weight category index" if weighting == "equal" else "Market-cap-weighted category index")
        sid = f"index:{iid}"; series[sid] = pd.Series(pd.to_numeric(group.index_level, errors="coerce").array, index=pd.to_datetime(group.date, errors="coerce"))
        rows.append({"subject_id": sid, "subject_name": first.index_name, "ticker": iid, "subject_type": kind, "category": category, "subcategory": None, "current_known_status": "research prototype"})
    for ticker, group in benchmarks.groupby("ticker"):
        sid=f"benchmark:{ticker}"; series[sid]=pd.Series(pd.to_numeric(group.adjusted_close, errors="coerce").array,index=pd.to_datetime(group.date,errors="coerce"))
        rows.append({"subject_id":sid,"subject_name":group.iloc[0].get("display_name",ticker),"ticker":ticker,"subject_type":"External benchmark","category":group.iloc[0].get("asset_class"),"subcategory":None,"current_known_status":"public market"})
    return series, pd.DataFrame(rows)


def build_archive(assets: pd.DataFrame, observations: pd.DataFrame, indices: pd.DataFrame | None = None, benchmarks: pd.DataFrame | None = None, *, snapshots: pd.DatetimeIndex | None = None, max_staleness_days: int | None = DEFAULT_STALENESS_DAYS, generated_at: object | None = None, source_version: str = "fixture") -> pd.DataFrame:
    indices = indices if indices is not None else pd.DataFrame(columns=["index_id"])
    benchmarks = benchmarks if benchmarks is not None else pd.DataFrame(columns=["ticker"])
    subject_series, metadata = collect_leaderboard_subjects(assets, observations, indices, benchmarks)
    if snapshots is None:
        dates = pd.to_datetime(observations.observed_at, errors="coerce", format="mixed", utc=True).dt.tz_localize(None).dropna()
        snapshots = quarter_ends(dates.min(), latest_completed_quarter())
    generated = pd.Timestamp(generated_at or pd.Timestamp.now(tz="UTC"))
    rows=[]
    for snapshot in snapshots:
        for _, meta in metadata.iterrows():
            raw = truncate_as_of(subject_series[meta.subject_id], snapshot)
            quarterly, effective = quarterly_asof_series(raw, snapshot, max_staleness_days)
            latest_date = raw.index.max() if len(raw) else pd.NaT
            age = (snapshot-latest_date).days if pd.notna(latest_date) else math.nan
            base_reason = "not_yet_launched" if raw.empty else ("stale_latest_observation" if max_staleness_days is not None and age > max_staleness_days else "")
            metrics = calculate_metrics(quarterly, snapshot, source_observation_count=len(raw))
            offering = pd.to_numeric(pd.Series([meta.get("offering_price")]), errors="coerce").iloc[0]
            shares = pd.to_numeric(pd.Series([meta.get("shares_outstanding")]), errors="coerce").iloc[0]
            metrics["observation_age_days"], metrics["offering_valuation"] = age, pd.to_numeric(pd.Series([meta.get("offering_valuation")]),errors="coerce").iloc[0]
            metrics["premium_to_offering"] = metrics["current_price"]/offering-1 if offering > 0 and pd.notna(metrics["current_price"]) else math.nan
            metrics["market_cap"] = metrics["current_price"]*shares if shares > 0 and pd.notna(metrics["current_price"]) else math.nan
            for key, value in metrics.items():
                definition=METRICS[key]; reason=base_reason
                if not reason and (len(raw)-1 < definition.minimum_returns): reason="insufficient_observations"
                if not reason and metrics["history_years"] < definition.minimum_years: reason="insufficient_trailing_history"
                if not reason and (pd.isna(value) or not math.isfinite(float(value))):
                    reason="invalid_metric_value"
                rows.append(meta.to_dict() | {"snapshot_date":snapshot,"point_in_time_status":"inferred from observations; historical tradability unavailable","metric_key":key,"metric_value":value,"eligible":not bool(reason),"exclusion_reason":reason,"observation_count":len(raw),"effective_start_date":raw.index.min() if len(raw) else pd.NaT,"effective_end_date":quarterly.dropna().index.max() if quarterly.notna().any() else pd.NaT,"latest_observation_date":latest_date,"observation_age_days":age,"market_cap_as_of_snapshot":metrics["market_cap"],"generated_at":generated,"methodology_version":METHODOLOGY_VERSION,"source_data_version":source_version})
    archive=pd.DataFrame(rows)
    ranked=[rank_snapshot(group,METRICS[key]) for (_,key),group in archive.groupby(["snapshot_date","metric_key"],sort=False)]
    return pd.concat(ranked,ignore_index=True).sort_values(["snapshot_date","metric_key","subject_id"]).reset_index(drop=True) if ranked else archive


def validate_archive(frame: pd.DataFrame) -> None:
    required={"snapshot_date","subject_id","metric_key","metric_value","rank","eligible","methodology_version","source_data_version"}
    if missing:=required-set(frame): raise ValueError(f"Leaderboard archive missing columns: {sorted(missing)}")
    if frame.duplicated(["snapshot_date","subject_id","metric_key"]).any(): raise ValueError("Duplicate leaderboard states")
    if (pd.to_datetime(frame.latest_observation_date,errors="coerce") > pd.to_datetime(frame.snapshot_date,errors="coerce")).any(): raise ValueError("Future observation leakage detected")


def write_archive_atomic(frame: pd.DataFrame, path: Path = ARCHIVE_PATH) -> Path:
    validate_archive(frame); path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name(f".{path.name}.tmp")
    try: frame.to_parquet(tmp,index=False); tmp.replace(path); return path
    except (ImportError,ModuleNotFoundError):
        tmp.unlink(missing_ok=True); fallback=path.with_suffix(".csv"); csv_tmp=fallback.with_name(f".{fallback.name}.tmp"); frame.to_csv(csv_tmp,index=False); csv_tmp.replace(fallback); return fallback


def load_archive(path: Path = ARCHIVE_PATH, *, expected_source_version: str | None = None) -> pd.DataFrame:
    archive = None
    if path.exists(): archive = pd.read_parquet(path)
    elif path.with_suffix(".csv").exists(): archive = pd.read_csv(path.with_suffix(".csv"),parse_dates=["snapshot_date","latest_observation_date","effective_start_date","effective_end_date","generated_at"])
    if archive is not None:
        expected = expected_source_version or (current_source_version() if path == ARCHIVE_PATH else None)
        versions = set(archive.get("source_data_version", pd.Series(dtype=str)).dropna().astype(str))
        if expected is None or versions == {expected}:
            return archive
        # A locally generated archive can outlive a canonical data refresh.
        # Rebuild in memory rather than serving subjects from the old snapshot.
        if path != ARCHIVE_PATH:
            return pd.DataFrame()
    # Deployed checkouts intentionally do not commit the generated archive.
    # Reconstruct it from the same committed normalized inputs used by the
    # Market Table; Streamlit caches this result for the process lifetime.
    if path == ARCHIVE_PATH:
        return build_default_archive()
    return pd.DataFrame()


def movement_table(frame: pd.DataFrame, start: object, end: object, metric_key: str) -> pd.DataFrame:
    selected=frame[(frame.metric_key==metric_key)&frame.snapshot_date.isin([pd.Timestamp(start),pd.Timestamp(end)])]
    cols=["subject_id","subject_name","ticker","category","subject_type","rank","metric_value","eligible"]
    left=selected[selected.snapshot_date==pd.Timestamp(start)][cols].add_prefix("start_")
    right=selected[selected.snapshot_date==pd.Timestamp(end)][cols].add_prefix("end_")
    merged=left.merge(right,left_on="start_subject_id",right_on="end_subject_id",how="outer")
    merged["subject_id"]=merged.start_subject_id.fillna(merged.end_subject_id); merged["subject"]=merged.start_subject_name.fillna(merged.end_subject_name)
    start_ok=merged.start_eligible.fillna(False); end_ok=merged.end_eligible.fillna(False)
    merged["eligibility_transition"]="Ineligible both"; merged.loc[start_ok&end_ok,"eligibility_transition"]="Remained eligible"; merged.loc[~start_ok&end_ok,"eligibility_transition"]="New entrant"; merged.loc[start_ok&~end_ok,"eligibility_transition"]="Dropped out"
    merged["rank_change"]=merged.start_rank-merged.end_rank; merged["metric_value_change"]=merged.end_metric_value-merged.start_metric_value
    return merged[["subject_id","subject","start_rank","end_rank","rank_change","start_metric_value","end_metric_value","metric_value_change","eligibility_transition","end_category","end_subject_type"]]


def rank_history_data(frame: pd.DataFrame, metric_key: str, subject_ids: list[str]) -> pd.DataFrame:
    result=frame[(frame.metric_key==metric_key)&frame.subject_id.isin(subject_ids)].copy().sort_values(["subject_id","snapshot_date"])
    result["previous_rank"]=result.groupby("subject_id")["rank"].shift(); result["rank_change"]=result.previous_rank-result["rank"]
    result.loc[~result.eligible,["rank","percentile_rank"]]=pd.NA
    return result


def build_default_archive(*, from_date: object | None = None) -> pd.DataFrame:
    paths=leaderboard_source_paths()
    assets=pd.read_csv(paths[0]); observations=pd.read_csv(paths[1]); indices=pd.read_csv(paths[2]); benchmarks=load_persisted_benchmarks().data
    dates=pd.to_datetime(observations.observed_at,errors="coerce",format="mixed",utc=True).dt.tz_localize(None).dropna(); start=max(dates.min(),pd.Timestamp(from_date)) if from_date else dates.min()
    return build_archive(assets,observations,indices,benchmarks,snapshots=quarter_ends(start,latest_completed_quarter()),source_version=source_fingerprint(paths))
