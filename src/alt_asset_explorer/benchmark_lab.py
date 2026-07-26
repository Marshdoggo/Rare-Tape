"""Reusable benchmark comparison primitives for sparse Rally research series."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import time
from typing import Mapping

import pandas as pd
import requests

from alt_asset_explorer.paths import DATA_PROCESSED
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


BENCHMARK_PARQUET_PATH = DATA_PROCESSED / "benchmark_history.parquet"
BENCHMARK_CSV_PATH = DATA_PROCESSED / "benchmark_history.csv"
BENCHMARK_COLUMNS = ["date", "ticker", "display_name", "asset_class", "adjusted_close", "data_source", "fetched_at"]


@dataclass(frozen=True)
class BenchmarkLoadResult:
    data: pd.DataFrame
    source: str | None
    path: Path | None


def earliest_rally_observation_date(observations: pd.DataFrame) -> pd.Timestamp:
    """Return the first genuine, priced authored Rally observation date."""
    required = {"asset_id", "observed_at", "price_per_share"}
    missing = required.difference(observations.columns)
    if missing:
        raise BenchmarkDataError(f"Rally observations are missing required columns: {', '.join(sorted(missing))}.")
    dates = pd.to_datetime(observations["observed_at"], errors="coerce", utc=True, format="mixed").dt.tz_localize(None).dt.normalize()
    prices = pd.to_numeric(observations["price_per_share"], errors="coerce")
    asset_ids = observations["asset_id"].astype("string").str.strip()
    usable = dates.notna() & prices.gt(0) & asset_ids.notna() & asset_ids.ne("")
    if "source_type" in observations:
        sources = observations["source_type"].astype("string").str.lower()
        usable &= ~sources.str.contains(r"placeholder|synthetic|demo|test", na=False)
    valid = dates[usable]
    if valid.empty:
        raise BenchmarkDataError("No valid Rally historical observation dates were found.")
    return valid.min()


def validate_benchmark_history(frame: pd.DataFrame, *, allow_empty: bool = False) -> pd.DataFrame:
    """Normalize and validate persisted long-format benchmark prices."""
    missing = set(BENCHMARK_COLUMNS).difference(frame.columns)
    if missing:
        raise BenchmarkDataError(f"Benchmark history is missing columns: {', '.join(sorted(missing))}.")
    result = frame[BENCHMARK_COLUMNS].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.normalize()
    result["fetched_at"] = pd.to_datetime(result["fetched_at"], errors="coerce", utc=True)
    result["ticker"] = result["ticker"].astype("string").str.strip().str.upper()
    result["adjusted_close"] = pd.to_numeric(result["adjusted_close"], errors="coerce")
    result = result[result["date"].notna() & result["ticker"].ne("") & result["adjusted_close"].gt(0)]
    result = result.drop_duplicates(["ticker", "date"], keep="last").sort_values(["ticker", "date"]).reset_index(drop=True)
    if result.empty and not allow_empty:
        raise BenchmarkDataError("Benchmark history contains no usable positive prices.")
    return result


def load_persisted_benchmarks(
    parquet_path: Path = BENCHMARK_PARQUET_PATH, csv_path: Path = BENCHMARK_CSV_PATH
) -> BenchmarkLoadResult:
    """Read committed benchmark history, preferring Parquet over CSV."""
    if parquet_path.exists():
        try:
            return BenchmarkLoadResult(validate_benchmark_history(pd.read_parquet(parquet_path)), "local Parquet", parquet_path)
        except (ImportError, OSError, ValueError) as exc:
            if not csv_path.exists():
                raise BenchmarkDataError(f"Could not read local benchmark Parquet: {exc}") from exc
    if csv_path.exists():
        return BenchmarkLoadResult(validate_benchmark_history(pd.read_csv(csv_path)), "local CSV", csv_path)
    return BenchmarkLoadResult(pd.DataFrame(columns=BENCHMARK_COLUMNS), None, None)


def select_local_benchmark(frame: pd.DataFrame, ticker: str, start: object, end: object) -> pd.DataFrame:
    symbol = str(ticker).strip().upper()
    dates = pd.to_datetime(frame.get("date"), errors="coerce")
    selected = frame[frame.get("ticker", pd.Series(index=frame.index, dtype=str)).astype(str).str.upper().eq(symbol) & dates.between(pd.Timestamp(start), pd.Timestamp(end))].copy()
    if selected.empty:
        return pd.DataFrame(columns=["date", "ticker", "raw_value"])
    return selected.assign(raw_value=pd.to_numeric(selected["adjusted_close"], errors="coerce"))[["date", "ticker", "raw_value"]].reset_index(drop=True)


def merge_benchmark_history(existing: pd.DataFrame, additions: pd.DataFrame) -> pd.DataFrame:
    return validate_benchmark_history(pd.concat([existing, additions], ignore_index=True), allow_empty=True)


def write_benchmark_history_atomic(frame: pd.DataFrame, output: Path = BENCHMARK_PARQUET_PATH) -> Path:
    """Validate and atomically replace Parquet, falling back to CSV without partial files."""
    clean = validate_benchmark_history(frame)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        clean.to_parquet(temporary, index=False)
        temporary.replace(output)
        return output
    except (ImportError, ModuleNotFoundError):
        temporary.unlink(missing_ok=True)
        fallback = output.with_suffix(".csv")
        csv_temporary = fallback.with_name(f".{fallback.name}.tmp")
        clean.to_csv(csv_temporary, index=False)
        csv_temporary.replace(fallback)
        return fallback


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


def download_benchmark(ticker: str, start: object, end: object, *, session=requests, attempts: int = 3,
                       backoff_seconds: float = 1.0, sleep=time.sleep) -> pd.DataFrame:
    """Download one daily benchmark history. Caching belongs at the application boundary."""
    symbol = str(ticker).strip().upper()
    if not symbol or not all(c.isalnum() or c in ".^-=" for c in symbol):
        raise BenchmarkDataError("Ticker contains unsupported characters.")
    period1 = int(pd.Timestamp(start, tz="UTC").timestamp())
    period2 = int((pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    headers = {"User-Agent": "RallyTerminalBenchmarkUpdater/1.0"}
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            response = session.get(url, params={"period1": period1, "period2": period2, "interval": "1d", "events": "div,splits"}, headers=headers, timeout=15)
            if response.status_code == 429:
                raise BenchmarkDataError(f"Benchmark provider rate limited {symbol} (HTTP 429).")
            response.raise_for_status()
            return parse_yahoo_chart(response.json(), symbol)
        except (BenchmarkDataError, requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt + 1 < max(1, attempts):
                sleep(backoff_seconds * (2 ** attempt))
    if isinstance(last_error, BenchmarkDataError):
        raise last_error
    raise BenchmarkDataError(f"Benchmark provider unavailable for {symbol}: {last_error}") from last_error


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
