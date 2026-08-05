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


def test_soblack_real_research_shape_uses_handbag_aliases_fx_and_diagnostics():
    aid='TMP-SOBLACK-REAL-SHAPE'; d=asset_dir(aid)
    if d.exists(): shutil.rmtree(d)
    try:
        f=build_factors('SOBLACK', {'condition': {}, 'missing_fields': ['condition']}).model_dump(mode='json')
        f['asset_id']=aid; f['rally_symbol']='SOBLACK'
        r=research(asset_id=aid)
        r['research_limitations']=['Subject condition is not fully documented.']
        r['comparable_sales']=[
            {'comparable_id':'SOBLACK-COMP-001','title':'Heritage 2016 Hermès So Black Birkin completed sale','sale_date':'2016-12-01','venue':'Heritage','sale_status':'sold','currency':'USD','reported_price':106250,'buyers_premium_included':True,'price_usd_at_sale':106250,'model_similarity':0.96,'size_similarity':0.92,'material_similarity':0.90,'hardware_similarity':0.94,'year_similarity':0.72,'accessory_similarity':0.85,'condition_similarity':0.78,'overall_similarity':0.88,'evidence_quality':0.82,'source_url':'https://example.com/heritage-2016','verified':True,'eligible_for_official_valuation':True},
            {'comparable_id':'SOBLACK-COMP-002','title':'Christie’s 2017 Hermès So Black Birkin completed sale','sale_date':'2017-05-31','venue':'Christies','sale_status':'sold','currency':'USD','reported_price':81250,'buyers_premium_included':True,'price_usd_at_sale':81250,'model_similarity':0.94,'size_similarity':0.90,'material_similarity':0.89,'hardware_similarity':0.91,'year_similarity':0.70,'accessory_similarity':0.82,'condition_similarity':0.76,'overall_similarity':0.84,'evidence_quality':0.76,'source_url':'https://example.com/christies-2017','verified':False,'eligible_for_official_valuation':True},
            {'comparable_id':'SOBLACK-COMP-003','title':'Christie’s 2022 Hermès So Black Birkin completed sale','sale_date':'2022-11-25','venue':'Christies Hong Kong','sale_status':'sold','currency':'HKD','reported_price':875000,'buyers_premium_included':True,'model_similarity':0.98,'size_similarity':0.94,'material_similarity':0.92,'hardware_similarity':0.96,'year_similarity':0.80,'accessory_similarity':0.86,'condition_similarity':0.80,'overall_similarity':0.90,'evidence_quality':0.84,'source_url':'https://example.com/christies-2022','verified':True,'eligible_for_official_valuation':True},
        ]
        save_json(aid,'factors',f); save_json(aid,'research',r)
        v=run_valuation(aid, write=False)
        assert v.valuation_status in {'completed_with_limitations','provisional'}
        assert v.calculation_summary['eligible_comparable_count'] >= 2
        assert {c['comparable_id'] for c in v.comparables_used} == {'SOBLACK-COMP-001','SOBLACK-COMP-002','SOBLACK-COMP-003'}
        by_id={d['comparable_id']: d for d in v.comparable_diagnostics}
        assert by_id['SOBLACK-COMP-001']['final_eligibility'] is True
        assert by_id['SOBLACK-COMP-002']['verification_treatment'] == pytest.approx(0.65)
        assert by_id['SOBLACK-COMP-003']['parsed_usd_price'] == pytest.approx(112000)
        assert by_id['SOBLACK-COMP-003']['fx_conversion_source'] == 'deterministic_engine_fx_table'
        assert 'provenance_similarity' in by_id['SOBLACK-COMP-001']['parsed_similarity_components']
        assert by_id['SOBLACK-COMP-001']['exclusion_reasons'] == []
        assert v.results.conservative_value_usd is not None
        assert v.results.base_value_usd is not None
        assert v.results.optimistic_value_usd is not None
        assert v.results.confidence_score < 0.75
        assert v.diagnostic_table and v.diagnostic_table[0]['Comparable ID'] == 'SOBLACK-COMP-001'
    finally:
        if d.exists(): shutil.rmtree(d)


def _soblack_three_research(asset_id='rally-soblack'):
    r=_minimal_handbag_research(asset_id)
    r.pop('comparable_sales', None)
    r['comparables']=[
        {'comparable_id':'SOBLACK-COMP-001','title':'Heritage 2016 Hermès So Black Birkin completed sale','sale_date':'2016-12-01','venue':'Heritage','sale_status':'sold','currency':'USD','reported_price':106250,'buyers_premium_included':True,'price_usd_at_sale':106250,'overall_similarity':0.88,'evidence_quality':0.82,'source_url':'https://example.com/heritage-2016','verified':True,'eligible_for_official_valuation':True},
        {'comparable_id':'SOBLACK-COMP-002','title':'Christie’s 2017 Hermès So Black Birkin completed sale','sale_date':'2017-05-31','venue':'Christies','sale_status':'sold','currency':'USD','reported_price':81250,'buyers_premium_included':True,'price_usd_at_sale':81250,'overall_similarity':0.84,'evidence_quality':0.76,'source_url':'https://example.com/christies-2017','verified':False,'eligible_for_official_valuation':True},
        {'comparable_id':'SOBLACK-COMP-003','title':'Christie’s 2022 Hermès So Black Birkin completed sale','sale_date':'2022-11-25','venue':'Christies Hong Kong','sale_status':'sold','currency':'HKD','reported_price':875000,'buyers_premium_included':True,'overall_similarity':0.90,'evidence_quality':0.84,'source_url':'https://example.com/christies-2022','verified':True,'eligible_for_official_valuation':True},
    ]
    return r


def test_canonical_comparables_parse_validate_serialize_save_load_engine():
    aid='TMP-CANONICAL-COMPS'; d=asset_dir(aid)
    if d.exists(): shutil.rmtree(d)
    try:
        f=build_factors('SOBLACK', {'condition': {'grade':'test'}}).model_dump(mode='json'); f['asset_id']=aid; f['rally_symbol']='SOBLACK'
        r=_soblack_three_research(aid); r['unknown_optional_field']={'kept': True}
        parsed=Research.model_validate(r)
        assert len(parsed.comparables) == 3
        assert [c.comparable_id for c in parsed.comparables] == ['SOBLACK-COMP-001','SOBLACK-COMP-002','SOBLACK-COMP-003']
        dumped=parsed.model_dump(mode='json', by_alias=True)
        assert 'comparables' in dumped and 'comparable_sales' not in dumped
        save_json(aid,'factors',f); save_json(aid,'research',r)
        saved=json.loads((d/'research.json').read_text())
        assert 'comparables' in saved and len(saved['comparables']) == 3
        loaded=Research.model_validate(saved)
        assert [c.comparable_id for c in loaded.comparables] == ['SOBLACK-COMP-001','SOBLACK-COMP-002','SOBLACK-COMP-003']
        v=run_valuation(aid, write=False)
        assert v.research_input_summary['raw_comparable_count'] == 3
        assert v.research_input_summary['parsed_comparable_count'] == 3
        assert len(v.comparable_diagnostics) == 3
    finally:
        if d.exists(): shutil.rmtree(d)


def test_saved_files_rerun_from_canonical_directory_only():
    from alt_asset_explorer.valuation_library.storage import rerun_valuation_from_saved_files, asset_file_inventory
    aid='rally-soblack'; d=asset_dir(aid); snap=_snapshot_dir(d)
    upper=asset_dir('SOBLACK'); lower=asset_dir('soblack'); upper_snap=_snapshot_dir(upper); lower_snap=_snapshot_dir(lower)
    try:
        for x in (d, upper, lower):
            if x.exists(): shutil.rmtree(x)
        upper.mkdir(parents=True); (upper/'research.json').write_text('{"asset_id":"SOBLACK","research_date":"2026-08-05","comparables":[]}\n')
        lower.mkdir(parents=True); (lower/'research.json').write_text('{"asset_id":"soblack","research_date":"2026-08-05","comparables":[]}\n')
        f=build_factors('SOBLACK', {'condition': {'grade':'test'}}).model_dump(mode='json')
        save_json(aid,'factors',f); save_json(aid,'research',_soblack_three_research('SOBLACK'))
        inv=asset_file_inventory(aid)
        assert inv['raw_comparable_count'] == 3
        summary, val=rerun_valuation_from_saved_files(aid)
        assert summary['raw_comparable_count'] == 3
        assert val.research_input_summary['research_path'].endswith('data/valuation_library/rally-soblack/research.json')
        assert len(val.comparable_diagnostics) == 3
    finally:
        _restore_dir(d, snap); _restore_dir(upper, upper_snap); _restore_dir(lower, lower_snap)


def test_raw_comparables_lost_returns_valuation_error(monkeypatch):
    import alt_asset_explorer.valuation_library.engine as e
    aid='TMP-LOST-COMPS'; d=asset_dir(aid)
    if d.exists(): shutil.rmtree(d)
    try:
        f=build_factors('SOBLACK', {'condition': {'grade':'test'}}).model_dump(mode='json'); f['asset_id']=aid; f['rally_symbol']='SOBLACK'
        save_json(aid,'factors',f); save_json(aid,'research',_soblack_three_research(aid))
        real=e.Research
        class DroppingResearch:
            @classmethod
            def model_validate(cls, data):
                obj=real.model_validate(data)
                obj.comparables=[]
                return obj
        monkeypatch.setattr(e, 'Research', DroppingResearch)
        v=run_valuation(aid, write=False)
        assert v.valuation_status == 'valuation_error'
        assert 'research_comparables_lost_during_parsing' in v.warnings
    finally:
        if d.exists(): shutil.rmtree(d)
