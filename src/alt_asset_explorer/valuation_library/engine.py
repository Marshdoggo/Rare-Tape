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
def _as_float(x):
    try:
        return float(x) if x is not None and math.isfinite(float(x)) else None
    except (TypeError, ValueError):
        return None

def _weighted_mean_from_mapping(comp, mapping: dict[str, Any]) -> tuple[float | None, list[str]]:
    vals=[]; warnings=[]
    for field, weight in (mapping.get('fields') or {}).items():
        value = getattr(comp.similarity_scores, field, None)
        if value is None:
            value = getattr(comp, field, None)
        value = _as_float(value)
        if value is not None:
            vals.append((value, float(weight)))
    if not vals and mapping.get('fallback_fields'):
        for field, weight in mapping.get('fallback_fields', {}).items():
            value = getattr(comp.similarity_scores, field, None)
            if value is None:
                value = getattr(comp, field, None)
            value = _as_float(value)
            if value is not None:
                vals.append((value, float(weight)))
        if vals and mapping.get('fallback_warning'):
            warnings.append(mapping['fallback_warning'])
    if not vals:
        return None, warnings
    total=sum(w for _, w in vals)
    return sum(v*w for v,w in vals)/total if total else None, warnings

def _similarity(comp, cat_cfg: dict[str, Any]) -> tuple[float, dict[str, float | None], list[str]]:
    warnings=[]
    components=comp.similarity_scores.model_dump()
    for component, mapping in (cat_cfg.get('similarity_aliases') or {}).items():
        if components.get(component) is None:
            value, component_warnings = _weighted_mean_from_mapping(comp, mapping)
            warnings.extend(component_warnings)
            if value is not None:
                components[component]=value
                warnings.append(f'{component}_derived_from_category_aliases')
    if comp.overall_similarity is not None and cat_cfg.get('use_supplied_overall_similarity', True):
        return float(comp.overall_similarity), components, warnings
    weighted=[]
    for component, weight in (cat_cfg.get('similarity_components') or {}).items():
        value=_as_float(components.get(component))
        if value is not None:
            weighted.append((value, float(weight)))
    if weighted:
        total=sum(w for _,w in weighted)
        warnings.append('overall_similarity_derived_from_components')
        return sum(v*w for v,w in weighted)/total, components, warnings
    return 0.5, components, ['overall_similarity_defaulted']

def _usd_price(comp, engine_cfg: dict[str, Any]) -> tuple[float | None, str | None, float | None, list[str]]:
    if _as_float(getattr(comp, 'price_usd_at_sale', None)) is not None:
        return float(comp.price_usd_at_sale), 'research_price_usd', 1.0, []
    if _as_float(getattr(comp, 'price_usd', None)) is not None:
        return float(comp.price_usd), 'research_price_usd', 1.0, []
    reported = _as_float(getattr(comp, 'reported_price', None))
    currency = getattr(comp, 'currency', None)
    if reported is None:
        return None, None, None, ['missing_reported_price']
    if _as_float(getattr(comp, 'fx_rate_to_usd', None)) is not None:
        rate=float(comp.fx_rate_to_usd)
        return reported*rate, 'research_supplied_fx_rate', rate, []
    if currency == 'USD':
        return reported, 'reported_usd_price', 1.0, []
    table=engine_cfg.get('supported_currencies') or {}
    if currency in table:
        rate=float(table[currency])
        return reported*rate, 'configured_fx_rate', rate, [f'fx_converted_from_{str(currency).lower()}']
    return None, None, None, ['unsupported_currency' if currency else 'missing_currency']

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

def _research_summary(path: Path, raw: dict[str, Any], research: Research | None, parsed_error: str | None = None) -> dict[str, Any]:
    raw_comps = raw.get('comparables')
    if raw_comps is None:
        raw_comps = raw.get('comparable_sales')
    raw_comps = raw_comps if isinstance(raw_comps, list) else []
    parsed_comps = research.comparables if research is not None else []
    return {
        'research_path': str(path),
        'research_hash': _hash(path),
        'top_level_keys': sorted(raw.keys()),
        'raw_comparable_count': len(raw_comps),
        'parsed_comparable_count': len(parsed_comps),
        'comparable_ids': [str(c.get('comparable_id')) for c in raw_comps if isinstance(c, dict) and c.get('comparable_id')],
        'parsed_comparable_ids': [c.comparable_id for c in parsed_comps],
        **({'parsing_error': parsed_error} if parsed_error else {}),
    }

def _valuation_error(factors: Factors, valuation_date: date, engine_cfg: dict[str, Any], cat_cfg: dict[str, Any], warnings: list[str], summary: dict[str, Any], d: Path, write: bool) -> Valuation:
    val=Valuation(asset_id=factors.asset_id,valuation_date=valuation_date,valuation_status='valuation_error',methodology_version=engine_cfg['methodology_version'],category_model_version=cat_cfg['category_model_version'],results=ValuationResults(confidence_score=0,official_value_available=False),research_input_summary=summary,calculation_summary={'eligible_comparable_count':0},warnings=sorted(set(warnings)),calculation_trace=[{'methodology_version':engine_cfg['methodology_version'],'engine_version':engine_cfg['engine_version'],'category_model_version':cat_cfg['category_model_version'],'run_timestamp':datetime.now(timezone.utc).isoformat(),'input_hashes':{'factors':_hash(d/'factors.json'),'research':_hash(d/'research.json')},'research_input_summary':summary}])
    if write: save_json(factors.asset_id,'valuation',val.model_dump(mode='json', by_alias=True),overwrite=True)
    return val

def run_valuation(asset: str, *, valuation_date: date|None=None, write: bool=True) -> Valuation:
    valuation_date=valuation_date or date.today(); d=asset_dir(asset)
    factors=Factors.model_validate(read_json(d/'factors.json'))
    research_path=d/'research.json'
    raw_research=read_json(research_path)
    research=Research.model_validate(raw_research)
    if factors.asset_id!=research.asset_id: raise ValueError('factors and research asset_id mismatch')
    engine_cfg=_load_yaml(METHODOLOGY_DIR/'valuation_engine_v1.yaml')
    cat_file = 'wine_whiskey_v1.yaml' if factors.category=='wine and whiskey' else f'{factors.category}_v1.yaml'
    cat_cfg=_load_yaml(METHODOLOGY_DIR/'categories'/cat_file)
    res=resolve_asset(factors.rally_symbol or factors.asset_id, expected_category=factors.category)
    warnings=list(res.warnings or []) + list(cat_cfg.get('category_warnings',[]))
    research_summary=_research_summary(research_path, raw_research, research)
    if research_summary['raw_comparable_count'] > 0 and research_summary['parsed_comparable_count'] == 0:
        warnings.append('research_comparables_lost_during_parsing')
        return _valuation_error(factors, valuation_date, engine_cfg, cat_cfg, warnings, research_summary, d, write)
    included=[]; trace=[]; raw_weights=[]; adjusted=[]
    now=valuation_date
    for comp in research.comparables:
        cw=list(comp.warnings); include=True; rationale=[]
        price, conversion_source, fx_rate, fx_warnings = _usd_price(comp, engine_cfg)
        cw.extend(fx_warnings)
        sim, parsed_components, sim_warnings = _similarity(comp, cat_cfg)
        cw.extend(sim_warnings)
        if comp.sale_status!='sold': include=False; rationale.append('not_sold')
        if price is None: include=False; rationale.append('missing_usd_normalized_price')
        if comp.sale_date and comp.sale_date>now: include=False; rationale.append('future_sale_date')
        if sim < cat_cfg['evidence_thresholds']['minimum_overall_similarity']: include=False; rationale.append('low_similarity')
        if comp.evidence_quality is not None and comp.evidence_quality < cat_cfg['evidence_thresholds']['minimum_evidence_quality']: include=False; rationale.append('low_evidence_quality')
        if comp.eligible_for_official_valuation is False: include=False; rationale.append('analyst_marked_ineligible')
        eligible_before_filtering=include
        years=0 if not comp.sale_date else max(0,(now-comp.sale_date).days/365.25)
        recency=max(float(engine_cfg['recency_floor']), 1-min(years/float(engine_cfg['max_recency_years']),1))
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
        if include: included.append(rec)
        diag={**rec,'eligible_before_filtering':eligible_before_filtering,'final_eligibility':include,'exclusion_reasons':rationale,'parsed_sale_status':comp.sale_status,'parsed_usd_price':price,'parsed_overall_similarity':sim,'parsed_similarity_components':parsed_components,'parsed_evidence_quality':eq,'verification_status':'verified' if comp.verified else 'unverified','verification_treatment':verification,'recency_treatment':recency,'currency':comp.currency,'original_currency':comp.currency,'original_reported_price':comp.reported_price,'fx_conversion_source':conversion_source,'fx_rate_to_usd':fx_rate,'configured_fx_version':engine_cfg.get('methodology_version'),'calculated_price_usd':price,'fx_warnings':sorted(set(fx_warnings)),'raw_weight':weight}
        trace.append({**diag,'premium_treatment':comp.buyers_premium_included,'similarity_score':sim,'evidence_quality_score':eq})
    total=sum(raw_weights); norm=[w/total if total>0 else 0 for w in raw_weights]
    inc_i=0; diagnostics=[]
    for idx, rec in enumerate(trace):
        w = norm[idx] if rec['final_eligibility'] else 0
        rec['final_weight']=w
        diagnostics.append(rec)
        if rec['final_eligibility']:
            included[inc_i]['final_weight']=w
            inc_i += 1
    vals=[v for v,w in zip(adjusted,norm) if _finite(v) and w>0]; weights=[w for v,w in zip(adjusted,norm) if _finite(v) and w>0]
    count=len(vals); status='completed'; official=True
    if count < int(engine_cfg['minimum_eligible_comparables']): status='insufficient_evidence'; official=False; warnings.append('insufficient_eligible_comparables')
    elif not factors.condition or factors.missing_fields:
        status='completed_with_limitations'; warnings.append('valuation_completed_with_optional_evidence_limitations')
    dispersion=None
    if vals:
        base=weighted_quantile(vals,weights,engine_cfg['estimate_quantiles']['base']); cons=weighted_quantile(vals,weights,engine_cfg['estimate_quantiles']['conservative']); opt=weighted_quantile(vals,weights,engine_cfg['estimate_quantiles']['optimistic']); median=base; wmean=sum(v*w for v,w in zip(vals,weights))/sum(weights)
        if median: dispersion=(max(vals)-min(vals))/median if median else None
        if dispersion and dispersion > float(engine_cfg['extreme_dispersion_pct']): warnings.append('extreme_comparable_dispersion')
    else: base=cons=opt=median=wmean=None
    confidence=float(engine_cfg['confidence_base']) if count else 0.0
    if count==1: confidence-=float(engine_cfg['confidence_penalties']['one_comparable'])
    if research.comparables and sum(1 for c in research.comparables if not c.verified)/len(research.comparables)>0.5: confidence-=float(engine_cfg['confidence_penalties']['most_unverified'])
    if 'condition' in factors.missing_fields or not factors.condition: confidence-=float(engine_cfg['confidence_penalties']['missing_condition'])
    if 'missing_historical_price_data' in warnings: confidence-=float(engine_cfg['confidence_penalties']['missing_history'])
    if 'extreme_comparable_dispersion' in warnings: confidence-=float(engine_cfg['confidence_penalties']['extreme_dispersion'])
    confidence=max(0,min(1,confidence))
    latest_market=factors.rally_data.latest_market_value_usd
    latest_share=factors.rally_data.latest_share_price_usd
    latest_q=(factors.rally_data.quarterly_price_history or [])[-1] if factors.rally_data.quarterly_price_history else None
    if latest_market is None and res.registry_record:
        prices=price_history_frame()
        if not prices.empty:
            ph=prices[prices['asset_id'].astype(str).eq(res.registry_record['asset_id'])].sort_values('date')
            if not ph.empty: latest_market=pd.to_numeric(ph.iloc[-1].get('market_cap_usd'),errors='coerce')
    init=factors.rally_data.initial_offering_value_usd or (res.registry_record or {}).get('offering_valuation_usd')
    prem=(base/float(latest_market)-1) if base and latest_market is not None and pd.notna(latest_market) else None
    issue_prem=(base/float(init)-1) if base and init else None
    latest_q_change=(base/float(latest_q.market_value_usd)-1) if base and latest_q and latest_q.market_value_usd else None
    summary={'eligible_comparable_count':count,'raw_comparable_count':research_summary['raw_comparable_count'],'parsed_comparable_count':research_summary['parsed_comparable_count'],'weighted_comparable_value_usd':wmean,'median_adjusted_comparable_usd':median,'dispersion_pct':dispersion}
    diagnostic_table=[{'Comparable ID':d['comparable_id'],'Included?':d['final_eligibility'],'USD price':d['parsed_usd_price'],'Overall similarity':d['parsed_overall_similarity'],'Evidence quality':d['parsed_evidence_quality'],'Verification status':d['verification_status'],'Exclusion reasons':', '.join(d['exclusion_reasons']) if d['exclusion_reasons'] else 'eligible','Final weight':d['final_weight']} for d in diagnostics]
    meta={'methodology_version':engine_cfg['methodology_version'],'engine_version':engine_cfg['engine_version'],'category_model_version':cat_cfg['category_model_version'],'run_timestamp':datetime.now(timezone.utc).isoformat(),'input_hashes':{'factors':_hash(d/'factors.json'),'research':_hash(d/'research.json')},'research_input_summary':research_summary,'configuration':{'engine':engine_cfg,'category':cat_cfg}}
    val=Valuation(asset_id=factors.asset_id,valuation_date=valuation_date,valuation_status=status,methodology_version=engine_cfg['methodology_version'],category_model_version=cat_cfg['category_model_version'],results=ValuationResults(conservative_value_usd=cons if official else None,base_value_usd=base if official else None,optimistic_value_usd=opt if official else None,confidence_score=confidence,official_value_available=official),market_comparison={'initial_offering_value_usd':init,'latest_share_price_usd':latest_share,'last_observed_market_value_usd':None if latest_market is None or pd.isna(latest_market) else latest_market,'fair_value_premium_discount_to_latest_market_value_pct':prem,'fair_value_premium_discount_to_issue_valuation_pct':issue_prem,'change_from_issue_valuation_pct':issue_prem,'change_from_latest_quarterly_observation_pct':latest_q_change,'asset_status':factors.rally_data.asset_status},comparables_used=included,comparable_diagnostics=diagnostics,diagnostic_table=diagnostic_table,calculation_summary=summary,research_input_summary=research_summary,warnings=sorted(set(warnings)),calculation_trace=[meta]+diagnostics)
    if write: save_json(factors.asset_id,'valuation',val.model_dump(mode='json', by_alias=True),overwrite=True)
    return val
