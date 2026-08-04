from __future__ import annotations
import hashlib, json, math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
import yaml
import pandas as pd
from alt_asset_explorer.paths import PROJECT_ROOT
from .models import Factors, Research, Valuation, ValuationResults
from .resolver import resolve_asset, price_history_frame
from .storage import asset_dir, read_json, save_json

METHODOLOGY_DIR=PROJECT_ROOT/'methodology'

def _load_yaml(p: Path)->dict[str,Any]: return yaml.safe_load(p.read_text())
def _hash(p: Path)->str: return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ''
def _finite(x): return x is not None and math.isfinite(float(x))

def weighted_quantile(values, weights, q):
    pairs=sorted((float(v),float(w)) for v,w in zip(values,weights) if _finite(v) and _finite(w) and w>=0)
    if not pairs: return None
    total=sum(w for _,w in pairs)
    if total<=0: return pairs[len(pairs)//2][0]
    acc=0
    for v,w in pairs:
        acc += w
        if acc/total >= q: return v
    return pairs[-1][0]

def run_valuation(asset: str, *, valuation_date: date|None=None, write: bool=True) -> Valuation:
    valuation_date=valuation_date or date.today(); d=asset_dir(asset)
    factors=Factors.model_validate(read_json(d/'factors.json'))
    research=Research.model_validate(read_json(d/'research.json'))
    if factors.asset_id!=research.asset_id: raise ValueError('factors and research asset_id mismatch')
    engine_cfg=_load_yaml(METHODOLOGY_DIR/'valuation_engine_v1.yaml')
    cat_file = 'wine_whiskey_v1.yaml' if factors.category=='wine and whiskey' else f'{factors.category}_v1.yaml'
    cat_cfg=_load_yaml(METHODOLOGY_DIR/'categories'/cat_file)
    res=resolve_asset(factors.rally_symbol or factors.asset_id, expected_category=factors.category)
    warnings=list(res.warnings or []) + list(cat_cfg.get('category_warnings',[]))
    included=[]; trace=[]; raw_weights=[]; adjusted=[]
    now=valuation_date
    for comp in research.comparable_sales:
        cw=list(comp.warnings); include=True; rationale=[]
        price=comp.price_usd or (comp.reported_price if comp.currency=='USD' else None)
        if comp.sale_status!='sold': include=False; rationale.append('not_sold')
        if price is None: include=False; rationale.append('missing_usd_price')
        if comp.sale_date and comp.sale_date>now: include=False; rationale.append('future_sale_date')
        if comp.overall_similarity is not None and comp.overall_similarity < cat_cfg['evidence_thresholds']['minimum_overall_similarity']: include=False; rationale.append('low_similarity')
        if comp.evidence_quality is not None and comp.evidence_quality < cat_cfg['evidence_thresholds']['minimum_evidence_quality']: include=False; rationale.append('low_evidence_quality')
        years=0 if not comp.sale_date else max(0,(now-comp.sale_date).days/365.25)
        recency=max(float(engine_cfg['recency_floor']), 1-min(years/float(engine_cfg['max_recency_years']),1))
        sim=comp.overall_similarity
        if sim is None:
            scores=comp.similarity_scores.model_dump().values(); vals=[v for v in scores if v is not None]
            sim=sum(vals)/len(vals) if vals else 0.5; cw.append('overall_similarity_derived_from_components')
        eq=comp.evidence_quality if comp.evidence_quality is not None else 0.5
        verification=float(engine_cfg['unverified_weight_multiplier']) if not comp.verified else 1.0
        adj=dict(engine_cfg['adjustments'])
        if price is not None:
            time_mult=(1+float(adj['time_adjustment_pct_per_year']))**years
            adj_price=float(price)*time_mult*float(adj['market_adjustment_multiplier'])*float(adj['condition_adjustment_multiplier'])*float(adj['rarity_adjustment_multiplier'])*float(adj['provenance_adjustment_multiplier'])*float(adj['liquidity_adjustment_multiplier'])
        else: adj_price=None
        weight=float(sim)*float(eq)*recency*verification if include else 0.0
        raw_weights.append(weight); adjusted.append(adj_price if adj_price is not None else float('nan'))
        rec={'comparable_id':comp.comparable_id,'reported_price_usd':price,'adjusted_price_usd':adj_price,'included':include,'adjustments':adj,'warnings':sorted(set(cw)),'inclusion_rationale':rationale or ['eligible']}
        included.append(rec)
        trace.append({**rec,'premium_treatment':comp.buyers_premium_included,'currency':comp.currency,'original_reported_price':comp.reported_price,'similarity_score':sim,'evidence_quality_score':eq,'recency_weight':recency,'verification_treatment':verification,'raw_weight':weight})
    total=sum(raw_weights); norm=[w/total if total>0 else 0 for w in raw_weights]
    for rec,w in zip(included,norm): rec['final_weight']=w
    vals=[v for v,w in zip(adjusted,norm) if _finite(v) and w>0]; weights=[w for v,w in zip(adjusted,norm) if _finite(v) and w>0]
    count=len(vals); status='completed'; official=True
    if count < int(engine_cfg['minimum_eligible_comparables']): status='insufficient_evidence'; official=False; warnings.append('insufficient_eligible_comparables')
    dispersion=None
    if vals:
        base=weighted_quantile(vals,weights,engine_cfg['estimate_quantiles']['base']); cons=weighted_quantile(vals,weights,engine_cfg['estimate_quantiles']['conservative']); opt=weighted_quantile(vals,weights,engine_cfg['estimate_quantiles']['optimistic']); median=base; wmean=sum(v*w for v,w in zip(vals,weights))/sum(weights)
        if median: dispersion=(max(vals)-min(vals))/median if median else None
        if dispersion and dispersion > float(engine_cfg['extreme_dispersion_pct']): warnings.append('extreme_comparable_dispersion')
    else: base=cons=opt=median=wmean=None
    confidence=float(engine_cfg['confidence_base']) if count else 0.0
    if count==1: confidence-=float(engine_cfg['confidence_penalties']['one_comparable'])
    if research.comparable_sales and sum(1 for c in research.comparable_sales if not c.verified)/len(research.comparable_sales)>0.5: confidence-=float(engine_cfg['confidence_penalties']['most_unverified'])
    if 'condition' in factors.missing_fields or not factors.condition: confidence-=float(engine_cfg['confidence_penalties']['missing_condition'])
    if 'missing_historical_price_data' in warnings: confidence-=float(engine_cfg['confidence_penalties']['missing_history'])
    if 'extreme_comparable_dispersion' in warnings: confidence-=float(engine_cfg['confidence_penalties']['extreme_dispersion'])
    confidence=max(0,min(1,confidence))
    prices=price_history_frame(); last_market=None
    if res.registry_record and not prices.empty:
        ph=prices[prices['asset_id'].astype(str).eq(res.registry_record['asset_id'])].sort_values('date')
        if not ph.empty: last_market=pd.to_numeric(ph.iloc[-1].get('market_cap_usd'),errors='coerce')
    init=factors.rally_data.initial_offering_value_usd or (res.registry_record or {}).get('offering_valuation_usd')
    prem=(float(last_market)/base-1) if base and pd.notna(last_market) else None
    summary={'eligible_comparable_count':count,'weighted_comparable_value_usd':wmean,'median_adjusted_comparable_usd':median,'dispersion_pct':dispersion}
    meta={'methodology_version':engine_cfg['methodology_version'],'engine_version':engine_cfg['engine_version'],'category_model_version':cat_cfg['category_model_version'],'run_timestamp':datetime.now(timezone.utc).isoformat(),'input_hashes':{'factors':_hash(d/'factors.json'),'research':_hash(d/'research.json')},'configuration':{'engine':engine_cfg,'category':cat_cfg}}
    val=Valuation(asset_id=factors.asset_id,valuation_date=valuation_date,valuation_status=status,methodology_version=engine_cfg['methodology_version'],category_model_version=cat_cfg['category_model_version'],results=ValuationResults(conservative_value_usd=cons if official else None,base_value_usd=base if official else None,optimistic_value_usd=opt if official else None,confidence_score=confidence,official_value_available=official),market_comparison={'initial_offering_value_usd':init,'last_observed_market_value_usd':None if pd.isna(last_market) else last_market,'premium_discount_to_base_pct':prem},comparables_used=included,calculation_summary=summary,warnings=sorted(set(warnings)),calculation_trace=[meta]+trace)
    if write: save_json(factors.asset_id,'valuation',val.model_dump(mode='json'),overwrite=True)
    return val
