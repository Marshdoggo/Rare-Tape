from __future__ import annotations
import argparse, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from alt_asset_explorer.valuation_library.engine import run_valuation

def main():
    p=argparse.ArgumentParser(); p.add_argument('--asset',required=True); args=p.parse_args()
    val=run_valuation(args.asset, write=True)
    print(f'{val.asset_id}: {val.valuation_status} ({val.results.confidence_score:.2f})')
if __name__=='__main__': main()
