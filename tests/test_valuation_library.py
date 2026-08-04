from __future__ import annotations
import json, math, shutil
from pathlib import Path
import pytest
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
