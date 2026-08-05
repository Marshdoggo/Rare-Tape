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

def _clean(value):
    if pd.isna(value): return None
    if hasattr(value, 'item'):
        try: return value.item()
        except Exception: pass
    return value

def _num(value):
    value=_clean(value)
    return None if value is None else float(value)

def get_asset_financial_context(asset_id: str) -> dict:
    """Resolve committed Rally identity, offering, share, latest-price, and quarterly context."""
    res=resolve_asset(asset_id)
    warnings=list(res.warnings or [])
    base={'asset_id':asset_id,'ticker':None,'asset_name':None,'category':None,'subcategory':None,'launch_date':None,'initial_offering_value_usd':None,'initial_share_price_usd':None,'shares_outstanding':None,'latest_share_price_usd':None,'latest_market_value_usd':None,'last_trade_date':None,'asset_status':None,'quarterly_price_history':[],'quarterly_price_history_source':None,'source_registry_path':str(PROJECT_ROOT/'data'/'processed'/'canonical_asset_master.csv'),'warnings':warnings,'resolution_status':res.status,'matches':res.matches or []}
    if res.status in {'unknown','ambiguous'}:
        return base
    row=res.registry_record or {}
    base.update({'asset_id':str(row.get('asset_id')),'ticker':_clean(row.get('ticker')),'asset_name':_clean(row.get('name')),'category':_clean(row.get('category')),'subcategory':_clean(row.get('subcategory')),'launch_date':_clean(row.get('offering_date')),'initial_offering_value_usd':_num(row.get('offering_valuation_usd')),'initial_share_price_usd':_num(row.get('offering_price_usd')),'shares_outstanding':_num(row.get('share_count')),'asset_status':_clean(row.get('trading_state')) or _clean(row.get('status'))})
    for field, warn in [('initial_offering_value_usd','missing_offering_valuation'),('initial_share_price_usd','missing_initial_share_price'),('shares_outstanding','missing_share_count'),('launch_date','missing_launch_date')]:
        if base.get(field) is None: warnings.append(warn)
    prices=price_history_frame()
    if prices.empty or 'asset_id' not in prices:
        warnings.append('missing_historical_price_data'); base['warnings']=sorted(set(warnings)); return base
    ph=prices[prices['asset_id'].astype(str).str.lower().eq(base['asset_id'].lower())].copy()
    if ph.empty:
        warnings.append('missing_historical_price_data'); base['warnings']=sorted(set(warnings)); return base
    ph['date']=pd.to_datetime(ph['date'], errors='coerce')
    ph=ph.dropna(subset=['date']).sort_values('date')
    q=ph[ph.get('frequency','').astype(str).str.lower().eq('quarterly')] if 'frequency' in ph else ph
    if q.empty:
        warnings.append('missing_quarterly_price_history')
    else:
        hist=[]
        for _,r in q.iterrows():
            hist.append({'date':r['date'].date().isoformat(),'share_price_usd':_num(r.get('last')),'market_value_usd':_num(r.get('market_cap_usd'))})
        base['quarterly_price_history']=hist
        base['quarterly_price_history_source']=str(PROJECT_ROOT/'data'/'processed'/'price_history.csv')
    latest=q.iloc[-1] if not q.empty else ph.iloc[-1]
    base['latest_share_price_usd']=_num(latest.get('last'))
    base['latest_market_value_usd']=_num(latest.get('market_cap_usd'))
    base['last_trade_date']=latest['date'].date().isoformat()
    base['warnings']=sorted(set(warnings))
    return base
