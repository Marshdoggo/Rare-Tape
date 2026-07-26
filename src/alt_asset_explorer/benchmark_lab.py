"""Reusable benchmark comparison primitives for sparse Rally research series."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import pandas as pd
import requests

from alt_asset_explorer.portfolio_analytics import infer_periods_per_year


@dataclass(frozen=True)
class BenchmarkDefinition:
    name: str
    ticker: str
    asset_class: str
    source: str = "Yahoo Finance chart API"
    notes: str = "Adjusted close when supplied; otherwise exchange close."


BENCHMARKS: dict[str, BenchmarkDefinition] = {
    "SPY": BenchmarkDefinition("S&P 500", "SPY", "U.S. equity"),
    "QQQ": BenchmarkDefinition("Nasdaq-100", "QQQ", "U.S. equity"),
    "DIA": BenchmarkDefinition("Dow Jones Industrial Average", "DIA", "U.S. equity"),
    "GLD": BenchmarkDefinition("Gold", "GLD", "commodity"),
    "AGG": BenchmarkDefinition("U.S. Aggregate Bonds", "AGG", "fixed income"),
    "BTC-USD": BenchmarkDefinition("Bitcoin", "BTC-USD", "digital asset"),
}


class BenchmarkDataError(RuntimeError):
    """A controlled external-data failure suitable for display in the UI."""


def parse_yahoo_chart(payload: object, ticker: str) -> pd.DataFrame:
    """Normalize a Yahoo chart response to date/raw_value without deriving returns."""
    try:
        result = payload["chart"]["result"][0]  # type: ignore[index]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]["close"]
        adjusted = result["indicators"].get("adjclose", [{}])[0].get("adjclose")
        values = adjusted if adjusted and len(adjusted) == len(timestamps) else quote
    except (KeyError, IndexError, TypeError) as exc:
        raise BenchmarkDataError(f"Malformed response for {ticker}.") from exc
    frame = pd.DataFrame({"date": pd.to_datetime(timestamps, unit="s", utc=True).tz_localize(None).normalize(),
                          "raw_value": pd.to_numeric(values, errors="coerce")})
    frame = frame.dropna().query("raw_value > 0").drop_duplicates("date", keep="last").sort_values("date")
    if frame.empty:
        raise BenchmarkDataError(f"No usable price history returned for {ticker}.")
    frame["ticker"] = ticker
    return frame[["date", "ticker", "raw_value"]].reset_index(drop=True)


def download_benchmark(ticker: str, start: object, end: object, *, session=requests) -> pd.DataFrame:
    """Download one daily benchmark history. Caching belongs at the application boundary."""
    symbol = str(ticker).strip().upper()
    if not symbol or not all(c.isalnum() or c in ".^-=" for c in symbol):
        raise BenchmarkDataError("Ticker contains unsupported characters.")
    period1 = int(pd.Timestamp(start, tz="UTC").timestamp())
    period2 = int((pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    try:
        response = session.get(url, params={"period1": period1, "period2": period2, "interval": "1d", "events": "div,splits"}, timeout=15)
        response.raise_for_status()
        return parse_yahoo_chart(response.json(), symbol)
    except BenchmarkDataError:
        raise
    except (requests.RequestException, ValueError) as exc:
        raise BenchmarkDataError(f"Benchmark provider unavailable for {symbol}: {exc}") from exc


def _clean_series(series: pd.Series) -> pd.Series:
    result = pd.Series(pd.to_numeric(series, errors="coerce").values,
                       index=pd.to_datetime(series.index, errors="coerce"), dtype=float)
    return result[result.index.notna() & result.notna() & result.gt(0)].sort_index().groupby(level=0).last()


def normalize_to_100(series: pd.Series) -> pd.Series:
    clean = _clean_series(series)
    return clean / clean.iloc[0] * 100 if not clean.empty else clean


def align_series(rally: pd.Series, benchmarks: Mapping[str, pd.Series], method: str = "previous") -> pd.DataFrame:
    """Align benchmarks to Rally evidence dates without manufacturing Rally observations."""
    subject = _clean_series(rally).rename("Rally subject")
    if subject.empty:
        return pd.DataFrame(columns=["Rally subject", *benchmarks])
    output = subject.to_frame()
    for name, raw in benchmarks.items():
        benchmark = _clean_series(raw)
        if method == "exact":
            sampled = benchmark.reindex(subject.index)
        elif method == "previous":
            sampled = benchmark.reindex(benchmark.index.union(subject.index)).sort_index().ffill().reindex(subject.index)
        elif method in {"month_end", "quarter_end"}:
            frequency = "ME" if method == "month_end" else "QE"
            subject_period = subject.resample(frequency).last().dropna()
            output = subject_period.rename("Rally subject").to_frame()
            sampled = benchmark.resample(frequency).last().reindex(output.index)
        else:
            raise ValueError("Unknown alignment method")
        output[name] = sampled
    return output.dropna(how="any")


def series_metrics(values: pd.Series) -> dict[str, object]:
    clean = _clean_series(values)
    blank = {key: math.nan for key in ("total_return", "annualized_return", "annualized_volatility", "sharpe_ratio", "sortino_ratio", "maximum_drawdown", "calmar_ratio", "best_period", "worst_period", "positive_period_percentage")}
    if len(clean) < 2:
        return {**blank, "observations": len(clean), "start": clean.index.min() if len(clean) else None, "end": clean.index.max() if len(clean) else None}
    returns = clean.pct_change().dropna(); years = (clean.index[-1] - clean.index[0]).days / 365.25
    total = clean.iloc[-1] / clean.iloc[0] - 1
    annual = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else math.nan
    periods = infer_periods_per_year(clean.index); std = returns.std(ddof=1)
    vol = std * math.sqrt(periods) if len(returns) > 1 else math.nan
    downside = returns[returns < 0]; down_dev = math.sqrt((downside.pow(2).sum() / len(returns))) * math.sqrt(periods)
    drawdown = clean / clean.cummax() - 1; max_dd = drawdown.min()
    return {"total_return": total, "annualized_return": annual, "annualized_volatility": vol,
            "sharpe_ratio": returns.mean() / std * math.sqrt(periods) if std > 0 else math.nan,
            "sortino_ratio": returns.mean() * periods / down_dev if down_dev > 0 else math.nan,
            "maximum_drawdown": max_dd, "calmar_ratio": annual / abs(max_dd) if max_dd < 0 else math.nan,
            "best_period": returns.max(), "worst_period": returns.min(),
            "positive_period_percentage": (returns > 0).mean(), "observations": len(clean),
            "start": clean.index[0], "end": clean.index[-1], "periods_per_year": periods}


def relative_metrics(subject: pd.Series, benchmark: pd.Series) -> dict[str, float]:
    frame = pd.concat([_clean_series(subject), _clean_series(benchmark)], axis=1).dropna()
    if len(frame) < 3:
        return {key: math.nan for key in ("excess_total_return", "annualized_excess_return", "tracking_error", "information_ratio", "beta", "alpha", "correlation", "upside_capture", "downside_capture")}
    sr, br = frame.iloc[:, 0].pct_change().dropna(), frame.iloc[:, 1].pct_change().dropna()
    periods = infer_periods_per_year(frame.index); excess = sr - br; te = excess.std(ddof=1) * math.sqrt(periods)
    beta = sr.cov(br) / br.var(ddof=1) if br.var(ddof=1) > 0 else math.nan
    alpha = (sr.mean() - beta * br.mean()) * periods if math.isfinite(beta) else math.nan
    def capture(mask: pd.Series) -> float:
        return sr[mask].mean() / br[mask].mean() if mask.any() and br[mask].mean() != 0 else math.nan
    sm, bm = series_metrics(frame.iloc[:, 0]), series_metrics(frame.iloc[:, 1])
    return {"excess_total_return": sm["total_return"] - bm["total_return"],
            "annualized_excess_return": sm["annualized_return"] - bm["annualized_return"],
            "tracking_error": te, "information_ratio": excess.mean() * periods / te if te > 0 else math.nan,
            "beta": beta, "alpha": alpha, "correlation": sr.corr(br),
            "upside_capture": capture(br > 0), "downside_capture": capture(br < 0)}


def comparison_dataset(aligned: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(index=aligned.index)
    for column in aligned:
        slug = str(column).replace(" ", "_").lower()
        result[f"{slug}_raw_value"] = aligned[column]
        result[f"{slug}_normalized_value"] = normalize_to_100(aligned[column])
        result[f"{slug}_return"] = aligned[column].pct_change()
        if column != "Rally subject" and "Rally subject" in aligned:
            result[f"excess_return_vs_{slug}"] = aligned["Rally subject"].pct_change() - aligned[column].pct_change()
    return result.rename_axis("date").reset_index()
