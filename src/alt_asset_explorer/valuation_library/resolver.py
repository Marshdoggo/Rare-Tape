from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import pandas as pd
from alt_asset_explorer.paths import PROJECT_ROOT

@dataclass
class AssetResolution:
    status: str
    asset_id: str
    ticker: str|None=None
    display_name: str|None=None
    category: str|None=None
    registry_record: dict|None=None
    warnings: list[str]|None=None
    matches: list[dict]|None=None

class AssetResolutionError(ValueError): pass

def _load(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()

def registry_frame() -> pd.DataFrame:
    p=PROJECT_ROOT/'data'/'processed'/'canonical_asset_master.csv'
    return _load(p)

def price_history_frame() -> pd.DataFrame:
    return _load(PROJECT_ROOT/'data'/'processed'/'price_history.csv')

def resolve_asset(identifier: str, *, expected_category: str|None=None, aliases: dict[str,str]|None=None) -> AssetResolution:
    ident=str(identifier).strip()
    registry=registry_frame()
    if registry.empty: raise AssetResolutionError('canonical asset registry is missing')
    aliases=aliases or {}
    keys=[ident, aliases.get(ident, ident)]
    mask=False
    for key in set(keys):
        k=str(key).lower()
        m=registry['asset_id'].astype(str).str.lower().eq(k) | registry['ticker'].astype(str).str.lower().eq(k)
        if 'name' in registry: m = m | registry['name'].astype(str).str.lower().eq(k)
        mask = m if isinstance(mask,bool) else (mask|m)
    matches=registry[mask].copy()
    if matches.empty:
        return AssetResolution('unknown', ident, warnings=[f'unknown_asset_id:{ident}'], matches=[])
    if len(matches)>1:
        return AssetResolution('ambiguous', ident, warnings=[f'ambiguous_asset_match:{ident}'], matches=matches.to_dict('records'))
    row=matches.iloc[0].to_dict()
    warnings=[]
    cat=str(row.get('category',''))
    if expected_category and cat.lower()!=expected_category.lower():
        warnings.append(f'category_mismatch: factors={expected_category} registry={cat}')
    prices=price_history_frame()
    if prices.empty or not prices['asset_id'].astype(str).eq(str(row['asset_id'])).any(): warnings.append('missing_historical_price_data')
    status='matched' if not any(w.startswith('category_mismatch') for w in warnings) else 'category_mismatch'
    return AssetResolution(status, str(row['asset_id']), str(row.get('ticker')), str(row.get('name')), cat, row, warnings, [row])
