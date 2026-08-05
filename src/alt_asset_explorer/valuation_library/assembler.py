from __future__ import annotations
from copy import deepcopy
from typing import Any
from .models import Factors
from .resolver import get_asset_financial_context
from .storage import save_json

CANONICAL_FIELDS={
    'asset_id':'rally_data.asset_id','ticker':'rally_data.ticker','rally_symbol':'rally_data.ticker','asset_name':'rally_data.asset_name','category':'rally_data.category','subcategory':'rally_data.subcategory',
    'launch_date':'rally_data.launch_date','initial_offering_value_usd':'rally_data.initial_offering_value_usd','initial_share_price_usd':'rally_data.initial_share_price_usd','shares_outstanding':'rally_data.shares_outstanding','shares_offered':'rally_data.shares_outstanding','latest_share_price_usd':'rally_data.latest_share_price_usd','latest_market_value_usd':'rally_data.latest_market_value_usd','last_trade_date':'rally_data.last_trade_date','asset_status':'rally_data.asset_status','quarterly_price_history':'rally_data.quarterly_price_history'
}
OPTIONAL_CONDITION_WARNINGS={
    'polishing_history':'Detailed polishing history unavailable.',
    'dial_surface_condition':'Dial surface condition not independently verified.',
    'bracelet_stretch':'Bracelet stretch not reported.',
    'service_history':'Service history unavailable.',
    'restoration_detail':'Restoration detail unavailable.',
    'independent_expert_inspection':'Independent expert inspection not provided.',
    'original_box':'Original box status not reported.',
    'ownership_provenance':'Complete ownership provenance unavailable.',
}

def _norm(v: Any) -> str:
    return '' if v is None else str(v).strip().lower()

def _get(d: dict[str,Any], dotted: str) -> Any:
    cur=d
    for p in dotted.split('.'):
        if not isinstance(cur,dict) or p not in cur: return None
        cur=cur[p]
    return cur

def _collect_supplemental(data: dict[str,Any]) -> dict[str,Any]:
    if 'category_factors' in data or 'rally_data' in data:
        out=deepcopy(data.get('category_factors') or {})
        for k in ('condition','provenance','identity','observed_facts','analyst_judgments'):
            if data.get(k): out.setdefault(k, data[k])
        return out
    return deepcopy(data)

def build_factors(asset_id: str, supplemental_specs: dict[str,Any], *, save: bool=False, overwrite: bool=False) -> Factors:
    ctx=get_asset_financial_context(asset_id)
    if ctx['resolution_status'] in {'unknown','ambiguous'}:
        raise ValueError(f"cannot build factors for {asset_id}: {ctx['resolution_status']}")
    conflicts=[]
    for manual_key, canonical_path in CANONICAL_FIELDS.items():
        manual = supplemental_specs.get(manual_key)
        if manual is None and isinstance(supplemental_specs.get('rally_data'), dict):
            manual=supplemental_specs['rally_data'].get(manual_key)
        canonical=_get({'rally_data':ctx}, canonical_path)
        if manual is not None and canonical is not None and _norm(manual)!=_norm(canonical):
            conflicts.append({'field':manual_key,'canonical_value':canonical,'manual_value':manual,'resolution':'canonical_value_retained'})
    category_factors=_collect_supplemental(supplemental_specs)
    for k in list(CANONICAL_FIELDS): category_factors.pop(k, None)
    category_factors.pop('rally_data', None)
    warnings=list(ctx.get('warnings') or [])
    for key,msg in OPTIONAL_CONDITION_WARNINGS.items():
        if key not in category_factors and key not in (supplemental_specs.get('condition') or {}): warnings.append(msg)
    if conflicts: warnings.append('canonical_manual_conflicts_retained_canonical_values')
    data={
        'schema_version':'1.1','asset_id':ctx['asset_id'],'rally_symbol':ctx['ticker'],'asset_name':ctx['asset_name'] or ctx['asset_id'],'category':str(ctx.get('category') or '').lower(),'subcategory':ctx.get('subcategory'),
        'rally_data':ctx,'category_factors':category_factors,'field_provenance':{'rally_data':'rally_terminal_existing_data','category_factors':'manual_rally_specification_transcription'},
        'merge_warnings':conflicts,'source_notes':['Financial, identity, and historical fields are auto-enriched from committed Rally Terminal artifacts.'],
        'missing_fields':warnings,
    }
    f=Factors.model_validate(data)
    if save: save_json(f.asset_id,'factors',f.model_dump(mode='json'),overwrite=overwrite)
    return f
