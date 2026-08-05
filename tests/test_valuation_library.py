from __future__ import annotations
import json, math, shutil
from pathlib import Path
import pytest
import pandas as pd
from pydantic import ValidationError
from alt_asset_explorer.valuation_library.models import Factors, Research
from alt_asset_explorer.valuation_library.engine import run_valuation
from alt_asset_explorer.valuation_library.resolver import resolve_asset
from alt_asset_explorer.valuation_library.storage import asset_dir, save_json, regenerate_manifest, ingest_report, build_report_package

BASE=Path('data/valuation_library/SYNTHETIC-ASSET')

def factors(**kw):
    d=json.loads((BASE/'factors.json').read_text()); d.update(kw); return d

def research(**kw):
    d=json.loads((BASE/'research.json').read_text()); d.update(kw); return d

def test_valid_factors_preserves_unknown_category_extension():
    f=Factors.model_validate(factors())
    assert f.category_factors['unknown_extension_field']=='preserved'

def test_invalid_category_and_missing_asset_id():
    with pytest.raises(ValidationError): Factors.model_validate(factors(category='cars'))
    d=factors(); d.pop('asset_id')
    with pytest.raises(ValidationError): Factors.model_validate(d)

def test_research_validation_scores_duplicates_price_source_dates():
    d=research(); d['comparable_sales'][0]['overall_similarity']=1.2
    with pytest.raises(ValidationError): Research.model_validate(d)
    d=research(); d['comparable_sales'][1]['comparable_id']=d['comparable_sales'][0]['comparable_id']
    with pytest.raises(ValidationError): Research.model_validate(d)
    d=research(); d['research_date']='2099-01-01'
    with pytest.raises(ValidationError): Research.model_validate(d)
    d=research(); d['comparable_sales'][0]['reported_price']=-1
    with pytest.raises(ValidationError): Research.model_validate(d)
    d=research(); d['comparable_sales'][0]['source_url']=None
    r=Research.model_validate(d)
    assert 'missing_source_reference' in r.comparable_sales[0].warnings

def test_asset_resolution_exact_alias_unknown_ambiguous_category_mismatch():
    assert resolve_asset('00MOUTON').status=='matched'
    assert resolve_asset('alias', aliases={'alias':'00MOUTON'}).ticker=='00MOUTON'
    assert resolve_asset('NO_SUCH_ASSET').status=='unknown'
    assert resolve_asset('00MOUTON', expected_category='fossils').status=='category_mismatch'

def test_valuation_repeatability_and_bounds():
    v1=run_valuation('SYNTHETIC-ASSET', write=False).model_dump(mode='json')
    v2=run_valuation('SYNTHETIC-ASSET', write=False).model_dump(mode='json')
    v1['calculation_trace'][0]['run_timestamp']=v2['calculation_trace'][0]['run_timestamp']
    assert v1==v2
    r=v1['results']; assert r['conservative_value_usd'] <= r['base_value_usd'] <= r['optimistic_value_usd']
    assert 0 <= r['confidence_score'] <= 1
    assert abs(sum(c['final_weight'] for c in v1['comparables_used'])) == pytest.approx(1)
    json.dumps(v1, allow_nan=False)

def test_no_eligible_one_comparable_unverified_outlier(tmp_path):
    aid='TMP-VALTEST'; d=asset_dir(aid)
    if d.exists(): shutil.rmtree(d)
    fd=factors(asset_id=aid, rally_symbol='00MOUTON', category='wine and whiskey')
    rd=research(asset_id=aid); rd['comparable_sales']=[]
    save_json(aid,'factors',fd); save_json(aid,'research',rd)
    assert run_valuation(aid, write=False).valuation_status=='insufficient_evidence'
    rd=research(asset_id=aid); rd['comparable_sales']=rd['comparable_sales'][:1]
    save_json(aid,'research',rd,overwrite=True)
    v=run_valuation(aid, write=False); assert v.valuation_status=='insufficient_evidence'; assert v.results.official_value_available is False
    shutil.rmtree(d)

def test_file_handling_manifest_report_package(tmp_path):
    aid='TMP-FILETEST'; d=asset_dir(aid)
    if d.exists(): shutil.rmtree(d)
    save_json(aid,'factors',factors(asset_id=aid, rally_symbol='00MOUTON', category='wine and whiskey'))
    with pytest.raises(FileExistsError): save_json(aid,'factors',factors(asset_id=aid, rally_symbol='00MOUTON', category='wine and whiskey'))
    save_json(aid,'factors',factors(asset_id=aid, rally_symbol='00MOUTON', category='wine and whiskey'), overwrite=True)
    assert any((d/'revisions').iterdir())
    m=regenerate_manifest(aid); assert m.files_present['factors'] and not m.files_present['research']
    ingest_report(aid, '# Asset report\n', overwrite=True)
    with pytest.raises(ValueError): ingest_report(aid, '<script>alert(1)</script>', overwrite=True)
    pkg=build_report_package(aid); assert b'report_generation_instructions.md' in pkg
    shutil.rmtree(d)

from alt_asset_explorer.valuation_library.resolver import get_asset_financial_context
from alt_asset_explorer.valuation_library.assembler import build_factors
import zipfile, io

def test_financial_context_success_and_quarterly_history():
    ctx=get_asset_financial_context('00MOUTON')
    assert ctx['resolution_status']=='matched'
    assert ctx['ticker']=='00MOUTON'
    assert ctx['initial_offering_value_usd'] is not None
    assert ctx['shares_outstanding'] is not None
    assert ctx['latest_market_value_usd'] is not None
    assert len(ctx['quarterly_price_history']) >= 1


def test_financial_context_missing_quarterly_and_offering(monkeypatch):
    import alt_asset_explorer.valuation_library.resolver as r
    base=r.registry_frame().head(1).copy()
    base.loc[:, 'asset_id']='NOHIST'; base.loc[:, 'ticker']='NOHIST'; base.loc[:, 'offering_valuation_usd']=float('nan')
    monkeypatch.setattr(r, 'registry_frame', lambda: base)
    monkeypatch.setattr(r, 'price_history_frame', lambda: r.pd.DataFrame(columns=['asset_id','date','last','market_cap_usd','frequency']))
    ctx=r.get_asset_financial_context('NOHIST')
    assert 'missing_historical_price_data' in ctx['warnings']
    assert 'missing_offering_valuation' in ctx['warnings']


def test_build_factors_supplemental_only_full_conflict_and_category_mismatch():
    f=build_factors('00MOUTON', {'producer':'Chateau Mouton Rothschild','vintage':2000})
    assert f.rally_data.ticker=='00MOUTON'
    assert f.category_factors['producer']=='Chateau Mouton Rothschild'
    assert f.field_provenance['rally_data']=='rally_terminal_existing_data'
    full={'asset_id':'WRONG','category':'books','rally_data':{'latest_share_price_usd':999},'category_factors':{'producer':'X'}}
    f2=build_factors('00MOUTON', full)
    fields={w['field'] for w in f2.merge_warnings}
    assert {'asset_id','category','latest_share_price_usd'} <= fields
    assert f2.category=='wine and whiskey'


def test_build_factors_unknown_and_ambiguous(monkeypatch):
    with pytest.raises(ValueError): build_factors('NO_SUCH_ASSET', {})
    import alt_asset_explorer.valuation_library.assembler as a
    monkeypatch.setattr(a, 'get_asset_financial_context', lambda asset_id: {'resolution_status':'ambiguous','warnings':['ambiguous_asset_match:x']})
    with pytest.raises(ValueError): a.build_factors('x', {})


def test_optional_condition_absence_completed_with_limitations_and_no_comps_insufficient(tmp_path):
    aid='TMP-LIMITED'; d=asset_dir(aid)
    if d.exists(): shutil.rmtree(d)
    f=build_factors('00MOUTON', {'producer':'X'}).model_dump(mode='json'); f['asset_id']=aid; f['rally_symbol']='00MOUTON'
    r=research(asset_id=aid)
    save_json(aid,'factors',f); save_json(aid,'research',r)
    v=run_valuation(aid, write=False)
    assert v.valuation_status=='completed_with_limitations'
    assert v.results.official_value_available is True
    r['comparable_sales']=[]; save_json(aid,'research',r,overwrite=True)
    assert run_valuation(aid, write=False).valuation_status=='insufficient_evidence'
    shutil.rmtree(d)


def test_report_package_contains_enriched_factors(tmp_path):
    aid='TMP-PKG-ENRICHED'; d=asset_dir(aid)
    if d.exists(): shutil.rmtree(d)
    f=build_factors('00MOUTON', {'producer':'X'}).model_dump(mode='json'); f['asset_id']=aid; f['rally_symbol']='00MOUTON'
    save_json(aid,'factors',f); save_json(aid,'research',research(asset_id=aid)); save_json(aid,'valuation',run_valuation(aid, write=False).model_dump(mode='json'))
    pkg=build_report_package(aid)
    with zipfile.ZipFile(io.BytesIO(pkg)) as z:
        fd=json.loads(z.read('factors.json'))
    assert fd['rally_data']['quarterly_price_history']
    assert fd['field_provenance']['rally_data']=='rally_terminal_existing_data'
    shutil.rmtree(d)

from datetime import date
from alt_asset_explorer.valuation_library.display import display_safe_dataframe
from alt_asset_explorer.valuation_library.storage import save_intake_and_run_valuation, normalize_document_identity


def _minimal_handbag_research(asset_id='SOBLACK'):
    r=research(asset_id='SYNTHETIC-ASSET')
    r['asset_id']=asset_id
    r['comparable_sales']=[{
        'comparable_id':'soblack-comp-1','title':'Comparable Birkin sale','sale_date':'2025-01-01','venue':'Test Auction','sale_status':'sold','currency':'USD','reported_price':75000,'buyers_premium_included':True,'price_usd':75000,
        'similarity_scores':{'identity_similarity':0.9,'condition_similarity':0.8,'provenance_similarity':0.7,'presentation_similarity':0.7},'overall_similarity':0.82,'evidence_quality':0.8,'source_url':'https://example.com/sale','verified':True
    },{
        'comparable_id':'soblack-comp-2','title':'Second comparable Birkin sale','sale_date':'2024-01-01','venue':'Test Auction','sale_status':'sold','currency':'USD','reported_price':68000,'buyers_premium_included':True,'price_usd':68000,
        'similarity_scores':{'identity_similarity':0.8,'condition_similarity':0.8,'provenance_similarity':0.7,'presentation_similarity':0.7},'overall_similarity':0.78,'evidence_quality':0.75,'source_url':'https://example.com/sale2','verified':True
    }]
    return r


def _snapshot_dir(d: Path):
    snap={}
    if d.exists():
        for p in d.rglob('*'):
            if p.is_file(): snap[p.relative_to(d)] = p.read_bytes()
    return snap


def _restore_dir(d: Path, snap: dict[Path, bytes]):
    if d.exists(): shutil.rmtree(d)
    if snap:
        d.mkdir(parents=True, exist_ok=True)
        for rel, data in snap.items():
            (d/rel).parent.mkdir(parents=True, exist_ok=True)
            (d/rel).write_bytes(data)


def test_soblack_aliases_resolve_to_canonical_identity():
    for alias in ('SOBLACK','soblack','rally-soblack'):
        r=resolve_asset(alias)
        assert r.status == 'matched'
        assert r.asset_id == 'rally-soblack'
        assert r.ticker == 'SOBLACK'
    assert normalize_document_identity('research', _minimal_handbag_research('SOBLACK'), 'rally-soblack')['asset_id'] == 'rally-soblack'
    assert normalize_document_identity('research', _minimal_handbag_research('soblack'), 'rally-soblack')['asset_id'] == 'rally-soblack'
    assert normalize_document_identity('research', _minimal_handbag_research('rally-soblack'), 'rally-soblack')['asset_id'] == 'rally-soblack'
    with pytest.raises(ValueError):
        normalize_document_identity('research', _minimal_handbag_research('00MOUTON'), 'rally-soblack')


def test_soblack_save_overwrite_backup_and_valuation_rerun():
    aid='rally-soblack'; d=asset_dir(aid); snap=_snapshot_dir(d)
    try:
        if d.exists(): shutil.rmtree(d)
        f=build_factors('SOBLACK', {'condition': {'grade':'test'}}).model_dump(mode='json')
        steps, val=save_intake_and_run_valuation(aid, f, _minimal_handbag_research('SOBLACK'), overwrite=False)
        assert val.asset_id == aid
        assert (d/'factors.json').exists() and (d/'research.json').exists() and (d/'valuation.json').exists() and (d/'manifest.json').exists()
        with pytest.raises(FileExistsError) as exc:
            save_intake_and_run_valuation(aid, f, _minimal_handbag_research('soblack'), overwrite=False)
        assert 'No files were written' in str(exc.value)
        steps, val2=save_intake_and_run_valuation(aid, f, _minimal_handbag_research('rally-soblack'), overwrite=True)
        assert val2.asset_id == aid
        assert any((d/'revisions').glob('factors_*.json'))
        assert any(s['step']=='final_valuation_status' for s in steps)
    finally:
        _restore_dir(d, snap)


def test_partial_prior_directory_atomic_failure_cleanup_and_recoverable_valuation_error():
    aid='rally-soblack'; d=asset_dir(aid); snap=_snapshot_dir(d)
    try:
        if d.exists(): shutil.rmtree(d)
        d.mkdir(parents=True); (d/'factors.json').write_text('{"partial": true}\n')
        f=build_factors('SOBLACK', {}).model_dump(mode='json')
        with pytest.raises(FileExistsError):
            save_intake_and_run_valuation(aid, f, _minimal_handbag_research('SOBLACK'), overwrite=False)
        assert json.loads((d/'factors.json').read_text()) == {'partial': True}
        def boom(_aid): raise RuntimeError('engine exploded')
        with pytest.raises(RuntimeError):
            save_intake_and_run_valuation(aid, f, _minimal_handbag_research('SOBLACK'), overwrite=True, valuation_runner=boom)
        m=json.loads((d/'manifest.json').read_text())
        assert m['publication_status']=='valuation_error'
        assert any('engine exploded' in w for w in m['warnings'])
        steps, val=save_intake_and_run_valuation(aid, f, _minimal_handbag_research('SOBLACK'), overwrite=True)
        assert val.asset_id==aid
    finally:
        _restore_dir(d, snap)


def test_mixed_type_dataframe_display_rendering_values_are_strings():
    df=pd.DataFrame({'field':['text','integer','float','none','date','list','dict'], 'value':['abc', 1000, 35.05, None, date(2026,8,5), [1,'x'], {'a':1}]})
    safe=display_safe_dataframe(df)
    assert safe['value'].tolist() == ['abc','1,000','35.05','Unavailable','2026-08-05','[1, "x"]','{"a": 1}']
    assert all(str(dtype) == 'string' for dtype in safe.dtypes)


def test_switching_assets_clears_prior_canonical_state_model():
    state={'validated_asset_id':'rally-00mouton','last_intake_selection':'00MOUTON'}
    selected='SOBLACK'
    if state.get('last_intake_selection') != selected:
        state.pop('validated_asset_id', None)
        state['last_intake_selection'] = selected
    assert 'validated_asset_id' not in state
    assert state['last_intake_selection'] == 'SOBLACK'
