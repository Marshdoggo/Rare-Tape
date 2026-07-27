"""Pure analytics and subject adapters for the Correlation Structure Lab.

The module deliberately keeps authored observations, existing index levels, and
persisted benchmark closes as distinct inputs.  It aligns values only at the
requested research grid; it never interpolates or fetches external data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CorrelationResult:
    correlations: pd.DataFrame
    overlaps: pd.DataFrame
    overlap_start: pd.DataFrame
    overlap_end: pd.DataFrame


def period_grid(start: object, end: object, frequency: str) -> pd.DatetimeIndex:
    """Return calendar period ends in the inclusive requested range."""
    aliases = {"monthly": "ME", "quarterly": "QE", "annual": "YE"}
    if frequency not in aliases:
        raise ValueError("frequency must be monthly, quarterly, or annual")
    first, last = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if first > last:
        return pd.DatetimeIndex([], name="period_end")
    return pd.DatetimeIndex(
        pd.date_range(first, last, freq=aliases[frequency]), name="period_end"
    )


def align_values(
    series: Mapping[str, pd.Series],
    grid: pd.DatetimeIndex,
    *,
    method: str = "previous",
    max_staleness_days: int | None = 180,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Align positive values and return their effective observation dates."""
    values = pd.DataFrame(index=grid, columns=list(series), dtype=float)
    effective = pd.DataFrame(index=grid, columns=list(series), dtype="datetime64[ns]")
    for name, raw in series.items():
        clean = pd.Series(
            pd.to_numeric(raw, errors="coerce").array,
            index=pd.to_datetime(raw.index, errors="coerce"),
            dtype=float,
        )
        clean = (
            clean[clean.index.notna() & clean.gt(0)]
            .sort_index()
            .groupby(level=0)
            .last()
        )
        if clean.empty:
            continue
        if method == "exact":
            sampled = clean.reindex(grid)
            dates = pd.Series(grid.where(sampled.notna()), index=grid)
        elif method == "previous":
            left = pd.DataFrame({"period_end": grid})
            right = clean.rename("value").rename_axis("observed_at").reset_index()
            merged = pd.merge_asof(
                left,
                right,
                left_on="period_end",
                right_on="observed_at",
                direction="backward",
            )
            sampled = pd.Series(merged["value"].array, index=grid, dtype=float)
            dates = pd.Series(merged["observed_at"].array, index=grid)
            if max_staleness_days is not None:
                stale = (
                    pd.Series(grid, index=grid) - dates
                ).dt.days > max_staleness_days
                sampled[stale] = np.nan
                dates[stale] = pd.NaT
        else:
            raise ValueError("method must be previous or exact")
        values[name], effective[name] = sampled, dates
    return values, effective


def calculate_returns(values: pd.DataFrame, method: str = "simple") -> pd.DataFrame:
    if method == "simple":
        return values.pct_change(fill_method=None)
    if method == "log":
        return np.log(values / values.shift(1))
    raise ValueError("method must be simple or log")


def correlation_matrices(
    returns: pd.DataFrame, *, method: str = "pearson", minimum_overlap: int = 6
) -> CorrelationResult:
    if method not in {"pearson", "spearman"}:
        raise ValueError("method must be pearson or spearman")
    names = list(returns.columns)
    corr = pd.DataFrame(np.nan, index=names, columns=names, dtype=float)
    overlap = pd.DataFrame(0, index=names, columns=names, dtype=int)
    starts = pd.DataFrame(None, index=names, columns=names, dtype=object)
    ends = starts.copy()
    for i, left in enumerate(names):
        for right in names[i:]:
            if left == right:
                clean = returns[left].dropna()
                count = len(clean)
                overlap.loc[left, left] = count
                if count:
                    starts.loc[left, left], ends.loc[left, left] = (
                        clean.index.min(),
                        clean.index.max(),
                    )
                if count >= minimum_overlap and clean.nunique() > 1:
                    corr.loc[left, left] = 1.0
                continue
            pair = returns[[left, right]].dropna()
            count = len(pair)
            overlap.loc[left, right] = overlap.loc[right, left] = count
            if count:
                starts.loc[left, right] = starts.loc[right, left] = pair.index.min()
                ends.loc[left, right] = ends.loc[right, left] = pair.index.max()
            if (
                count >= minimum_overlap
                and pair[left].nunique() > 1
                and pair[right].nunique() > 1
            ):
                value = (
                    pair[left].rank().corr(pair[right].rank())
                    if method == "spearman"
                    else pair[left].corr(pair[right])
                )
                corr.loc[left, right] = corr.loc[right, left] = value
    return CorrelationResult(corr, overlap, starts, ends)


def complete_subset(correlations: pd.DataFrame) -> tuple[list[str], dict[str, str]]:
    """Deterministically prune the least-connected subject until no cells are missing."""
    keep = list(correlations.index)
    excluded: dict[str, str] = {}
    while len(keep) > 1 and correlations.loc[keep, keep].isna().to_numpy().any():
        valid = correlations.loc[keep, keep].notna().sum().sub(1)
        remove = sorted(keep, key=lambda name: (valid[name], name))[0]
        excluded[remove] = (
            "Incomplete clustering matrix / insufficient pairwise overlap"
        )
        keep.remove(remove)
    if len(keep) == 1 and pd.isna(correlations.loc[keep[0], keep[0]]):
        excluded[keep[0]] = "Invalid or constant return series"
        keep.clear()
    return keep, excluded


def correlation_distance(
    correlations: pd.DataFrame, method: str = "sqrt"
) -> pd.DataFrame:
    clipped = ((correlations + correlations.T) / 2).clip(-1.0, 1.0)
    if method == "sqrt":
        distance = np.sqrt(0.5 * (1.0 - clipped))
    elif method == "one_minus":
        distance = 1.0 - clipped
    else:
        raise ValueError("method must be sqrt or one_minus")
    distance = (distance + distance.T) / 2
    if len(distance):
        np.fill_diagonal(distance.values, 0.0)
    return distance


def cluster(
    distance: pd.DataFrame, method: str = "average"
) -> tuple[np.ndarray | None, list[str]]:
    from scipy.cluster.hierarchy import dendrogram, linkage
    from scipy.spatial.distance import squareform

    if method not in {"average", "complete", "single"}:
        raise ValueError("unsupported linkage method")
    if len(distance) < 2:
        return None, list(distance.index)
    if distance.isna().any().any() or not np.isfinite(distance.to_numpy()).all():
        raise ValueError("clustering requires a complete finite distance matrix")
    tree = linkage(
        squareform(distance.to_numpy(), checks=True),
        method=method,
        optimal_ordering=True,
    )
    info = dendrogram(tree, labels=list(distance.index), no_plot=True)
    return tree, list(info["ivl"])


def ordered_matrix(matrix: pd.DataFrame, order: list[str]) -> pd.DataFrame:
    return matrix.reindex(index=order, columns=order)


def pairwise_table(
    result: CorrelationResult, metadata: pd.DataFrame, distance_method: str = "sqrt"
) -> pd.DataFrame:
    meta = metadata.set_index("subject_id") if not metadata.empty else pd.DataFrame()
    distance = correlation_distance(result.correlations, distance_method)
    rows = []
    names = list(result.correlations)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:

            def field(subject: str, column: str):
                return (
                    meta.loc[subject, column]
                    if subject in meta.index and column in meta
                    else None
                )

            rows.append(
                {
                    "Subject A": field(left, "display_label") or left,
                    "Subject B": field(right, "display_label") or right,
                    "Subject ID A": left,
                    "Subject ID B": right,
                    "Subject type A": field(left, "subject_type"),
                    "Subject type B": field(right, "subject_type"),
                    "Category A": field(left, "category"),
                    "Category B": field(right, "category"),
                    "Correlation": result.correlations.loc[left, right],
                    "Distance": distance.loc[left, right],
                    "Overlap count": result.overlaps.loc[left, right],
                    "Effective overlap start": result.overlap_start.loc[left, right],
                    "Effective overlap end": result.overlap_end.loc[left, right],
                }
            )
    return pd.DataFrame(rows)


def matrix_csv(frame: pd.DataFrame) -> bytes:
    return (
        frame.rename_axis(
            "period_end" if isinstance(frame.index, pd.DatetimeIndex) else "subject_id"
        )
        .to_csv()
        .encode()
    )
