"""Reusable cross-sectional analytics for the Modular Scatter Plot Explorer."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

import pandas as pd


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    display_name: str
    description: str
    metric_type: Literal["numeric", "categorical", "date"] = "numeric"
    format_style: str = "number"
    source_column: str | None = None
    required_fields: tuple[str, ...] = ()
    negative_allowed: bool = True
    zero_allowed: bool = True
    log_allowed: bool = False
    minimum_returns: int = 0
    annualized: bool = False
    subject_types: tuple[str, ...] = ("asset",)


def _metric(
    key: str, name: str, description: str, **kwargs: object
) -> MetricDefinition:
    return MetricDefinition(key, name, description, **kwargs)


METRICS = {
    item.key: item
    for item in (
        _metric(
            "annualized_mean_return",
            "Annualized mean return",
            "Arithmetic mean periodic return annualized using the history's inferred frequency.",
            format_style="percent",
            minimum_returns=2,
            annualized=True,
        ),
        _metric(
            "annualized_volatility",
            "Annualized volatility",
            "Sample volatility annualized with the same frequency as mean return.",
            format_style="percent",
            negative_allowed=False,
            log_allowed=True,
            minimum_returns=2,
            annualized=True,
        ),
        _metric(
            "cagr",
            "CAGR",
            "Geometric return over elapsed calendar time.",
            format_style="percent",
            minimum_returns=1,
            annualized=True,
        ),
        _metric(
            "total_return",
            "Total return",
            "Change from first to last valid price.",
            format_style="percent",
            minimum_returns=1,
        ),
        _metric(
            "mean_period_return",
            "Mean period return",
            "Arithmetic mean of valid observation-to-observation returns.",
            format_style="percent",
            minimum_returns=1,
        ),
        _metric(
            "period_volatility",
            "Period volatility",
            "Sample standard deviation of observation-to-observation returns.",
            format_style="percent",
            negative_allowed=False,
            log_allowed=True,
            minimum_returns=2,
        ),
        _metric(
            "sharpe_ratio",
            "Sharpe ratio",
            "Annualized arithmetic excess return divided by annualized volatility.",
            minimum_returns=2,
            annualized=True,
        ),
        _metric(
            "sortino_ratio",
            "Sortino ratio",
            "Annualized arithmetic excess return divided by downside deviation.",
            minimum_returns=2,
            annualized=True,
        ),
        _metric(
            "maximum_drawdown",
            "Maximum drawdown",
            "Largest peak-to-trough price decline.",
            format_style="percent",
            zero_allowed=True,
            minimum_returns=1,
        ),
        _metric(
            "calmar_ratio",
            "Calmar ratio",
            "CAGR divided by absolute maximum drawdown.",
            minimum_returns=1,
            annualized=True,
        ),
        _metric(
            "positive_period_percentage",
            "Positive-period percentage",
            "Share of valid returns above zero.",
            format_style="percent",
            negative_allowed=False,
            minimum_returns=1,
        ),
        _metric(
            "best_period_return",
            "Best period return",
            "Largest valid periodic return.",
            format_style="percent",
            minimum_returns=1,
        ),
        _metric(
            "worst_period_return",
            "Worst period return",
            "Smallest valid periodic return.",
            format_style="percent",
            minimum_returns=1,
        ),
        _metric(
            "observation_count",
            "Number of observations",
            "Valid price observations in the analysis range.",
            format_style="integer",
            negative_allowed=False,
            log_allowed=True,
        ),
        _metric(
            "history_years",
            "History length",
            "Elapsed years between effective first and last observations.",
            negative_allowed=False,
            log_allowed=True,
        ),
        _metric(
            "inception_date",
            "Inception date",
            "First valid observation in the analysis range.",
            metric_type="date",
            format_style="date",
        ),
        _metric(
            "latest_observation_date",
            "Latest observation date",
            "Last valid observation in the analysis range.",
            metric_type="date",
            format_style="date",
        ),
        _metric(
            "current_price",
            "Current price",
            "Latest authored per-share observation in the selected range.",
            format_style="currency",
            negative_allowed=False,
            log_allowed=True,
        ),
        _metric(
            "offering_price",
            "Offering price",
            "Authored offering price per share.",
            format_style="currency",
            source_column="offering_price_per_share",
            negative_allowed=False,
            log_allowed=True,
        ),
        _metric(
            "return_since_offering",
            "Return since offering",
            "Latest price relative to authored offering price.",
            format_style="percent",
        ),
        _metric(
            "market_cap",
            "Market capitalization",
            "Latest price multiplied by canonical shares outstanding (authored observation market cap is preferred).",
            format_style="currency",
            negative_allowed=False,
            log_allowed=True,
        ),
        _metric(
            "offering_valuation",
            "Offering valuation",
            "Authored offering market capitalization.",
            format_style="currency",
            source_column="offering_market_cap",
            negative_allowed=False,
            log_allowed=True,
        ),
        _metric(
            "shares_outstanding",
            "Shares outstanding",
            "Canonical authored share count.",
            format_style="integer",
            source_column="shares_outstanding",
            negative_allowed=False,
            log_allowed=True,
        ),
        _metric(
            "category",
            "Category",
            "Canonical Rally category.",
            metric_type="categorical",
            source_column="category",
        ),
        _metric(
            "subcategory",
            "Subcategory",
            "Canonical Rally subcategory.",
            metric_type="categorical",
            source_column="subcategory",
        ),
        _metric(
            "status",
            "Trading status",
            "Canonical Rally status.",
            metric_type="categorical",
            source_column="status",
        ),
        _metric(
            "active_exited",
            "Active versus exited",
            "Trading assets versus sold, exited, or exit-announced assets.",
            metric_type="categorical",
        ),
        _metric(
            "offering_year",
            "Offering year",
            "Calendar year of the authored offering date.",
            format_style="integer",
            negative_allowed=False,
        ),
    )
}

AXIS_METRICS = tuple(
    k for k, m in METRICS.items() if m.metric_type in {"numeric", "date"}
)
SIZE_METRICS = (
    "market_cap",
    "offering_valuation",
    "shares_outstanding",
    "current_price",
    "history_years",
    "observation_count",
    "equal_size",
)
COLOR_METRICS = (
    "category",
    "subcategory",
    "status",
    "active_exited",
    "offering_year",
    "return_since_offering",
    "sharpe_ratio",
    "annualized_mean_return",
    "annualized_volatility",
    "market_cap",
    "single_color",
)


def validate_registry(registry: dict[str, MetricDefinition] = METRICS) -> None:
    if any(key != metric.key for key, metric in registry.items()):
        raise ValueError("Metric registry keys must match metric definitions")
    if len({metric.display_name for metric in registry.values()}) != len(registry):
        raise ValueError("Metric display names must be unique")
    for key in (*AXIS_METRICS, *SIZE_METRICS[:-1], *COLOR_METRICS[:-1]):
        if key not in registry:
            raise ValueError(f"Unknown registered metric: {key}")


def _frequency(dates: pd.DatetimeIndex) -> tuple[float, str]:
    gaps = pd.Series(dates).diff().dt.total_seconds().dropna() / 86400
    years = (dates[-1] - dates[0]).days / 365.25 if len(dates) > 1 else 0
    if gaps.empty or years <= 0:
        return math.nan, "unavailable"
    variation = gaps.std(ddof=0) / gaps.mean() if gaps.mean() else math.inf
    if variation <= 0.25:
        median = gaps.median()
        periods = (
            52.0
            if median <= 10
            else 12.0
            if median <= 45
            else 4.0
            if median <= 120
            else 1.0
        )
        return (
            periods,
            f"regular; median spacing {median:.0f} days; {periods:g} periods/year",
        )
    periods = (len(dates) - 1) / years
    return (
        periods,
        f"irregular; {periods:.2f} observed return intervals/year over elapsed time",
    )


def calculate_series_metrics(
    values: pd.Series, *, minimum_returns: int = 4, annual_risk_free_rate: float = 0.0
) -> dict[str, object]:
    clean = pd.Series(
        pd.to_numeric(values, errors="coerce").to_numpy(),
        index=pd.to_datetime(values.index, errors="coerce"),
        dtype=float,
    )
    clean = (
        clean[clean.index.notna() & clean.gt(0)].sort_index().groupby(level=0).last()
    )
    returns = clean.pct_change().dropna()
    start, end = (clean.index[0], clean.index[-1]) if len(clean) else (pd.NaT, pd.NaT)
    years = (end - start).days / 365.25 if len(clean) > 1 else 0.0
    periods, methodology = (
        _frequency(pd.DatetimeIndex(clean.index))
        if len(clean) > 1
        else (math.nan, "unavailable")
    )
    result: dict[str, object] = {
        "observation_count": len(clean),
        "return_observation_count": len(returns),
        "effective_start": start,
        "effective_end": end,
        "inception_date": start,
        "latest_observation_date": end,
        "history_years": years,
        "current_price": clean.iloc[-1] if len(clean) else math.nan,
        "periods_per_year": periods,
        "frequency_methodology": methodology,
    }
    keys = (
        "annualized_mean_return",
        "annualized_volatility",
        "cagr",
        "total_return",
        "mean_period_return",
        "period_volatility",
        "sharpe_ratio",
        "sortino_ratio",
        "maximum_drawdown",
        "calmar_ratio",
        "positive_period_percentage",
        "best_period_return",
        "worst_period_return",
    )
    result.update({key: math.nan for key in keys})
    if len(returns) < minimum_returns or not math.isfinite(periods):
        return result
    mean, std = returns.mean(), returns.std(ddof=1)
    total = clean.iloc[-1] / clean.iloc[0] - 1
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else math.nan
    periodic_rf = (1 + annual_risk_free_rate) ** (1 / periods) - 1
    downside = returns[returns < periodic_rf] - periodic_rf
    downside_deviation = math.sqrt(downside.pow(2).sum() / len(returns)) * math.sqrt(
        periods
    )
    drawdown = clean / clean.cummax() - 1
    max_drawdown = drawdown.min()
    result.update(
        {
            "annualized_mean_return": mean * periods,
            "annualized_volatility": std * math.sqrt(periods),
            "cagr": cagr,
            "total_return": total,
            "mean_period_return": mean,
            "period_volatility": std,
            "sharpe_ratio": (mean - periodic_rf) / std * math.sqrt(periods)
            if std > 0
            else math.nan,
            "sortino_ratio": (mean - periodic_rf) * periods / downside_deviation
            if downside_deviation > 0
            else math.nan,
            "maximum_drawdown": max_drawdown,
            "calmar_ratio": cagr / abs(max_drawdown) if max_drawdown < 0 else math.nan,
            "positive_period_percentage": (returns > 0).mean(),
            "best_period_return": returns.max(),
            "worst_period_return": returns.min(),
        }
    )
    return result


def filter_date_range(
    observations: pd.DataFrame, start: object | None = None, end: object | None = None
) -> pd.DataFrame:
    result = observations.copy()
    result["observed_at"] = pd.to_datetime(
        result["observed_at"], errors="coerce", utc=True
    ).dt.tz_localize(None)
    if start is not None:
        result = result[result["observed_at"] >= pd.Timestamp(start)]
    if end is not None:
        result = result[
            result["observed_at"]
            <= pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        ]
    return result


def build_asset_metric_table(
    assets: pd.DataFrame,
    observations: pd.DataFrame,
    *,
    start: object | None = None,
    end: object | None = None,
    minimum_returns: int = 4,
    annual_risk_free_rate: float = 0.0,
) -> pd.DataFrame:
    history = filter_date_range(observations, start, end)
    rows = []
    for _, asset in assets.iterrows():
        group = history[
            history["asset_id"].astype(str).eq(str(asset["asset_id"]))
        ].sort_values("observed_at")
        metrics = calculate_series_metrics(
            group.set_index("observed_at")["price_per_share"],
            minimum_returns=minimum_returns,
            annual_risk_free_rate=annual_risk_free_rate,
        )
        row = asset.to_dict() | metrics
        row["asset_name"] = row.get("asset_name", row.get("name"))
        row["offering_price"] = pd.to_numeric(
            pd.Series(
                [row.get("offering_price_per_share", row.get("offering_price_usd"))]
            ),
            errors="coerce",
        ).iloc[0]
        row["offering_valuation"] = pd.to_numeric(
            pd.Series(
                [row.get("offering_market_cap", row.get("offering_valuation_usd"))]
            ),
            errors="coerce",
        ).iloc[0]
        row["shares_outstanding"] = pd.to_numeric(
            pd.Series([row.get("shares_outstanding", row.get("share_count"))]),
            errors="coerce",
        ).iloc[0]
        latest_cap = pd.to_numeric(
            group.get("market_cap", pd.Series(dtype=float)), errors="coerce"
        ).dropna()
        row["market_cap"] = (
            latest_cap.iloc[-1]
            if not latest_cap.empty
            else row["current_price"] * row["shares_outstanding"]
        )
        row["return_since_offering"] = (
            row["current_price"] / row["offering_price"] - 1
            if row["offering_price"] > 0
            else math.nan
        )
        row["offering_year"] = pd.to_datetime(
            row.get("offering_date"), errors="coerce"
        ).year
        row["active_exited"] = (
            "Active"
            if str(row.get("status", "")).lower() == "trading"
            else "Exited / other"
        )
        rows.append(row)
    return pd.DataFrame(rows)


def filter_universe(
    table: pd.DataFrame,
    *,
    categories: list[str] | None = None,
    statuses: list[str] | None = None,
    include_exited: bool = False,
    search: str = "",
    minimum_observations: int = 0,
    minimum_history_years: float = 0.0,
    include_missing_market_cap: bool = True,
) -> pd.DataFrame:
    result = table.copy()
    if categories:
        result = result[result["category"].isin(categories)]
    if statuses:
        result = result[result["status"].isin(statuses)]
    if not include_exited:
        result = result[result["status"].astype(str).str.lower().eq("trading")]
    if search:
        needle = search.strip().lower()
        result = result[
            result["ticker"].astype(str).str.lower().str.contains(needle, regex=False)
            | result["asset_name"]
            .astype(str)
            .str.lower()
            .str.contains(needle, regex=False)
        ]
    result = result[
        pd.to_numeric(result["return_observation_count"], errors="coerce")
        .fillna(0)
        .ge(minimum_observations)
    ]
    result = result[
        pd.to_numeric(result["history_years"], errors="coerce")
        .fillna(0)
        .ge(minimum_history_years)
    ]
    if not include_missing_market_cap:
        result = result[pd.to_numeric(result["market_cap"], errors="coerce").notna()]
    return result


def marker_sizes(
    values: pd.Series, *, minimum: float = 9, maximum: float = 42, scale: float = 1.0
) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").clip(lower=0)
    positive = numeric[numeric.gt(0)]
    if positive.empty:
        return pd.Series(minimum * scale, index=values.index, dtype=float)
    transformed = numeric.pow(0.5)
    low, high = transformed[transformed.gt(0)].quantile([0.05, 0.95])
    if high <= low:
        scaled = pd.Series((minimum + maximum) / 2, index=values.index)
    else:
        scaled = minimum + (transformed.clip(low, high) - low) / (high - low) * (
            maximum - minimum
        )
    return scaled.fillna(minimum).clip(minimum, maximum) * scale


def prepare_scatter_data(
    table: pd.DataFrame, x: str, y: str, size: str, color: str
) -> tuple[pd.DataFrame, dict[str, int]]:
    eligible = len(table)
    result = table.copy()

    def valid_axis(key: str) -> pd.Series:
        if METRICS[key].metric_type == "date":
            return pd.to_datetime(result[key], errors="coerce").notna()
        return pd.to_numeric(result[key], errors="coerce").notna()

    valid = valid_axis(x) & valid_axis(y)
    missing = int((~valid).sum())
    result = result[valid].copy()
    result["marker_size"] = 18.0 if size == "equal_size" else marker_sizes(result[size])
    if color == "single_color":
        result["display_color"] = "All assets"
    elif METRICS[color].metric_type == "numeric":
        result["display_color"] = pd.to_numeric(result[color], errors="coerce")
    else:
        result["display_color"] = result[color].fillna("Unknown").astype(str)
    return result, {
        "eligible": eligible,
        "plotted": len(result),
        "excluded": eligible - len(result),
        "missing_selected_metrics": missing,
    }


def export_scatter_csv(table: pd.DataFrame) -> bytes:
    return (
        table.drop(columns=["marker_size", "display_color"], errors="ignore")
        .to_csv(index=False)
        .encode("utf-8")
    )


validate_registry()
