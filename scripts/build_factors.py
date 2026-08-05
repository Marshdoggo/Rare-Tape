from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from alt_asset_explorer.valuation_library.assembler import build_factors

p=argparse.ArgumentParser(description='Build an enriched valuation-library factors.json from Rally Terminal data plus supplemental specs.')
p.add_argument('--asset', required=True)
p.add_argument('--spec-file', required=True, type=Path)
p.add_argument('--write', action='store_true')
p.add_argument('--overwrite', action='store_true')
args=p.parse_args()
f=build_factors(args.asset, json.loads(args.spec_file.read_text()), save=args.write, overwrite=args.overwrite)
print(json.dumps(f.model_dump(mode='json'), indent=2, sort_keys=True))
