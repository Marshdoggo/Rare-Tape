from __future__ import annotations

import pandas as pd


def evaluate_against_ground_truth(extracted: pd.DataFrame, truth: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    left = extracted.copy(); right = truth.copy()
    left["observation_date"] = pd.to_datetime(left["observation_date"], errors="coerce").dt.date
    date_col = "observation_date" if "observation_date" in right else "observed_at" if "observed_at" in right else "date"
    right["observation_date"] = pd.to_datetime(right[date_col], errors="coerce").dt.date
    price_col = "price_per_share" if "price_per_share" in right else "last"
    merged = left.merge(right[["observation_date", price_col]].rename(columns={price_col: "expected_price"}), on="observation_date", how="outer", indicator=True)
    matched = merged["_merge"].eq("both"); exact = matched & pd.to_numeric(merged["price_per_share"], errors="coerce").eq(pd.to_numeric(merged["expected_price"], errors="coerce"))
    expected, found = len(right), len(left)
    metrics = {"expected_observation_count": expected, "extracted_observation_count": found, "correctly_matched_dates": int(matched.sum()), "missing_dates": int(merged["_merge"].eq("right_only").sum()), "unexpected_dates": int(merged["_merge"].eq("left_only").sum()), "exact_price_matches": int(exact.sum()), "price_mismatches": int((matched & ~exact).sum()), "date_recall": float(matched.sum()/expected) if expected else 0, "extraction_precision": float(matched.sum()/found) if found else 0, "price_accuracy": float(exact.sum()/matched.sum()) if matched.any() else 0}
    return metrics, merged
