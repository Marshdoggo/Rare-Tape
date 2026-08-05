from __future__ import annotations
import json, shutil, tempfile, zipfile, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
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


def resolve_canonical_asset_id(identifier: str, *, selected_asset_id: str | None = None, expected_category: str | None = None) -> str:
    res = resolve_asset(identifier, expected_category=expected_category)
    selected = resolve_asset(selected_asset_id) if selected_asset_id is not None else None
    if selected is not None and selected.status in {'unknown', 'ambiguous'} and str(identifier) == str(selected_asset_id):
        return str(selected_asset_id)
    if res.status in {'unknown', 'ambiguous'}:
        raise ValueError(f'unresolved asset alias {identifier!r}: {"; ".join(res.warnings or [])}')
    canonical = res.asset_id
    if selected is not None:
        if selected.status in {'unknown', 'ambiguous'}:
            raise ValueError(f'selected asset {selected_asset_id!r} could not be resolved: {"; ".join(selected.warnings or [])}')
        if canonical != selected.asset_id:
            raise ValueError(f'document asset_id {identifier} resolves to {canonical}, not selected asset {selected.asset_id}')
        canonical = selected.asset_id
    return canonical

def normalize_document_identity(kind: str, data: dict[str, Any], selected_asset_id: str) -> dict[str, Any]:
    raw = dict(data)
    input_asset_id = str(raw.get('asset_id', '')).strip()
    if not input_asset_id:
        raise ValueError(f'{kind} document is missing asset_id')
    category = raw.get('category') if kind == 'factors' else None
    canonical = resolve_canonical_asset_id(input_asset_id, selected_asset_id=selected_asset_id, expected_category=category)
    raw['asset_id'] = canonical
    provenance = dict(raw.get('provenance') or {})
    provenance.setdefault('input_asset_id', input_asset_id)
    provenance['canonical_asset_id'] = canonical
    raw['provenance'] = provenance
    if kind == 'factors' and isinstance(raw.get('rally_data'), dict):
        raw['rally_data'] = {**raw['rally_data'], 'asset_id': canonical}
    return raw

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
    data = normalize_document_identity(kind, data, asset_id)
    obj=validate_document(kind, data)
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
    if files.get('factors') and files.get('research') and any(w.startswith('valuation_error:') for w in warnings): return 'valuation_error'
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


def existing_intake_files(asset_id: str, kinds: tuple[str, ...] = ('factors', 'research', 'valuation', 'manifest')) -> list[Path]:
    d = asset_dir(asset_id)
    name_by_kind = {**FILENAMES, 'manifest': 'manifest.json'}
    return [d / name_by_kind[k] for k in kinds if (d / name_by_kind[k]).exists()]

def save_intake_and_run_valuation(asset_id: str, factors_data: dict[str, Any], research_data: dict[str, Any], *, overwrite: bool = False, valuation_runner: Callable[[str], Any] | None = None) -> tuple[list[dict[str, str]], Any | None]:
    canonical = resolve_canonical_asset_id(asset_id)
    factors_norm = normalize_document_identity('factors', factors_data, canonical)
    research_norm = normalize_document_identity('research', research_data, canonical)
    factors_obj = validate_document('factors', factors_norm)
    research_obj = validate_document('research', research_norm)
    existing = existing_intake_files(canonical, ('factors', 'research', 'valuation'))
    if existing and not overwrite:
        names = ', '.join(str(p) for p in existing)
        raise FileExistsError(f'Existing valuation-library files would be overwritten: {names}. Enable revision-safe overwrite to create timestamped backups before replacing them. No files were written.')
    d = asset_dir(canonical); d.mkdir(parents=True, exist_ok=True); (d/'source_material').mkdir(exist_ok=True)
    staged = {
        FILENAMES['factors']: json.dumps(factors_obj.model_dump(mode='json'), indent=2, sort_keys=True, default=_json_default)+'\n',
        FILENAMES['research']: json.dumps(research_obj.model_dump(mode='json'), indent=2, sort_keys=True, default=_json_default)+'\n',
    }
    steps: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(dir=d) as tmpdir:
        tmp = Path(tmpdir)
        for fn, text in staged.items():
            (tmp/fn).write_text(text, encoding='utf-8')
        backups = []
        try:
            if overwrite:
                for fn in staged:
                    p=d/fn
                    if p.exists(): backups.append(create_revision(p))
            for fn in staged:
                (tmp/fn).replace(d/fn)
                steps.append({'step': fn, 'status': 'saved'})
            manifest = regenerate_manifest(canonical)
            steps.append({'step': 'manifest.json', 'status': manifest.publication_status})
        except Exception:
            raise
    runner = valuation_runner
    if runner is None:
        from .engine import run_valuation
        runner = lambda aid: run_valuation(aid, write=True)
    try:
        val = runner(canonical)
        steps.append({'step': 'valuation_engine', 'status': 'executed'})
        steps.append({'step': 'valuation.json', 'status': 'saved'})
        steps.append({'step': 'final_valuation_status', 'status': getattr(val, 'valuation_status', 'completed')})
        regenerate_manifest(canonical)
        return steps, val
    except Exception as e:
        m = regenerate_manifest(canonical)
        md = m.model_dump(mode='json')
        md['publication_status'] = 'valuation_error'
        md['validation_status'] = 'error'
        md['warnings'] = sorted(set(list(md.get('warnings') or []) + [f'valuation_error:{e}']))
        atomic_write_text(d/'manifest.json', json.dumps(md, indent=2, sort_keys=True, default=_json_default)+'\n', overwrite=True)
        steps.append({'step': 'valuation_engine', 'status': f'failed: {e}'})
        raise RuntimeError(f'valuation generation failed after saving factors/research: {e}') from e
