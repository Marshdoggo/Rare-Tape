from __future__ import annotations
import json, math
from datetime import date, datetime
from typing import Any
import pandas as pd


def format_display_value(value: Any) -> str:
    if value is None:
        return 'Unavailable'
    try:
        if pd.isna(value) and not isinstance(value, (list, dict, tuple, set)):
            return 'Unavailable'
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if isinstance(value, float):
        if math.isnan(value):
            return 'Unavailable'
        return f'{value:,.2f}'
    if isinstance(value, int):
        return f'{value:,}'
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def display_safe_dataframe(rows_or_df: Any) -> pd.DataFrame:
    df = rows_or_df.copy() if isinstance(rows_or_df, pd.DataFrame) else pd.DataFrame(rows_or_df)
    if df.empty:
        return df
    for col in df.columns:
        df[col] = df[col].map(format_display_value).astype('string')
    return df
