from __future__ import annotations
import json, shutil, tempfile, zipfile, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from pydantic import ValidationError
from alt_asset_explorer.paths import PROJECT_ROOT
from .models import Factors, Research, Valuation, Manifest
from .resolver import resolve_asset

LIBRARY_ROOT = PROJECT_ROOT / 'data' / 'valuation_library'
FILENAMES = {'factors':'factors.json','research':'research.json','valuation':'valuation.json','report':'report.md'}

def asset_dir(asset_id: str) -> Path: return LIBRARY_ROOT / asset_id

def _json_default(o):
    return o.isoformat() if hasattr(o,'isoformat') else o

def read_json(path: Path) -> dict[str, Any]: return json.loads(path.read_text())

def validate_document(kind: str, data: dict[str, Any]):
    return {'factors':Factors,'research':Research,'valuation':Valuation,'manifest':Manifest}[kind].model_validate(data)

def atomic_write_text(path: Path, text: str, *, overwrite: bool=False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite: raise FileExistsError(f'{path} exists; pass overwrite=True to create a revision backup')
    if path.exists(): create_revision(path)
    with tempfile.NamedTemporaryFile('w', delete=False, dir=path.parent, encoding='utf-8') as tmp:
        tmp.write(text); tmp_path=Path(tmp.name)
    tmp_path.replace(path); return path

def create_revision(path: Path) -> Path:
    rev=path.parent/'revisions'; rev.mkdir(exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dest=rev/f'{path.stem}_{stamp}{path.suffix}'
    shutil.copy2(path,dest); return dest

def save_json(asset_id: str, kind: str, data: dict[str, Any], *, overwrite: bool=False) -> Path:
    obj=validate_document(kind, data)
    if obj.asset_id != asset_id: raise ValueError(f'document asset_id {obj.asset_id} does not match selected asset {asset_id}')
    text=json.dumps(obj.model_dump(mode='json'), indent=2, sort_keys=True, default=_json_default)+'\n'
    path=asset_dir(asset_id)/FILENAMES[kind]
    out=atomic_write_text(path,text,overwrite=overwrite)
    regenerate_manifest(asset_id)
    return out

def ingest_report(asset_id: str, markdown: str, *, overwrite: bool=False) -> Path:
    if re.search(r'<\s*(script|iframe|object|embed)\b', markdown, re.I): raise ValueError('unsafe HTML tag detected in report.md')
    out=atomic_write_text(asset_dir(asset_id)/'report.md', markdown, overwrite=overwrite)
    regenerate_manifest(asset_id); return out

def library_assets() -> list[str]:
    if not LIBRARY_ROOT.exists(): return []
    return sorted(p.name for p in LIBRARY_ROOT.iterdir() if p.is_dir())

def load_asset_files(asset_id: str) -> dict[str, Any]:
    d=asset_dir(asset_id); out={}
    for k,fn in FILENAMES.items():
        p=d/fn
        if p.exists(): out[k]=p.read_text() if k=='report' else read_json(p)
    return out

def workflow_status(files: dict[str, bool], warnings: list[str]) -> str:
    if any(w.startswith('stale') for w in warnings): return 'stale'
    if files.get('report'): return 'report_ready'
    if files.get('valuation'): return 'valuation_ready'
    if files.get('factors') and files.get('research'): return 'research_ready'
    if files.get('factors'): return 'factors_ready'
    return 'intake_missing'

def regenerate_manifest(asset_id: str) -> Manifest:
    d=asset_dir(asset_id); d.mkdir(parents=True, exist_ok=True); (d/'source_material').mkdir(exist_ok=True)
    files={k:(d/fn).exists() for k,fn in FILENAMES.items()}; missing=[fn for k,fn in FILENAMES.items() if k in ('factors','research') and not files[k]]
    schema_versions={}; warnings=[]; display=None; rally_match=None; research_date=None; valuation_date=None; methodology=None; report_date=None
    for kind in ('factors','research','valuation'):
        if not files.get(kind): continue
        try:
            obj=validate_document(kind, read_json(d/FILENAMES[kind])); schema_versions[kind]=obj.schema_version
            if kind=='factors':
                display=obj.asset_name; res=resolve_asset(obj.rally_symbol or obj.asset_id, expected_category=obj.category); rally_match=res.__dict__; warnings += res.warnings or []
            if kind=='research': research_date=obj.research_date
            if kind=='valuation': valuation_date=obj.valuation_date; methodology=obj.methodology_version
        except Exception as e: warnings.append(f'{kind}_validation_error:{e}')
    if files.get('report'):
        report_date=datetime.fromtimestamp((d/'report.md').stat().st_mtime, timezone.utc).date()
        if files.get('valuation') and report_date and valuation_date and report_date < valuation_date: warnings.append('stale_report_before_latest_valuation')
        if files.get('research') and report_date and research_date and report_date < research_date: warnings.append('stale_report_before_latest_research')
    lm={fn:datetime.fromtimestamp((d/fn).stat().st_mtime, timezone.utc).isoformat() for fn in FILENAMES.values() if (d/fn).exists()}
    m=Manifest(asset_id=asset_id,display_name=display,rally_match=rally_match,files_present=files,schema_versions=schema_versions,methodology_version=methodology,research_date=research_date,valuation_date=valuation_date,report_date=report_date,publication_status=workflow_status(files,warnings),validation_status='warning' if warnings else 'valid',missing_required_files=missing,warnings=sorted(set(warnings)),last_modified=lm)
    atomic_write_text(d/'manifest.json', json.dumps(m.model_dump(mode='json'),indent=2,sort_keys=True)+'\n', overwrite=True)
    return m

def build_report_package(asset_id: str) -> bytes:
    d=asset_dir(asset_id)
    with tempfile.NamedTemporaryFile(delete=False) as tmp: zpath=Path(tmp.name)
    with zipfile.ZipFile(zpath,'w',zipfile.ZIP_DEFLATED) as z:
        for fn in ('factors.json','research.json','valuation.json'):
            p=d/fn
            if p.exists(): z.write(p, fn)
        z.writestr('report_generation_instructions.md', '# Rally Terminal Report Drafting Package\nUse factors.json, research.json, valuation.json, and the methodology document to draft report.md. Do not treat report prose as authoritative structured data.\n')
    data=zpath.read_bytes(); zpath.unlink(missing_ok=True); return data
