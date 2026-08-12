#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"src"))
from alt_asset_explorer.intelligence import IntelligenceConfig, IntelligenceEngine, JsonReportCache, OpenAIResponsesClient


def select_packets(evidence: dict, slates: list, args) -> list[dict]:
    ids=[]
    if args.story_id: ids=[args.story_id]
    elif args.quarter: ids=next((x["story_ids"] for x in slates if x["period"]==args.quarter),[])
    elif args.latest: ids=next((x["story_ids"] for x in reversed(slates)),[])
    else: ids=[sid for slate in slates for sid in slate["story_ids"]]
    packets=[evidence[x] for x in ids if x in evidence]
    return packets[:args.limit] if args.limit is not None else packets


def main() -> int:
    parser=argparse.ArgumentParser(description="Generate cache-first Content Lab Intelligence reports.")
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--story-id"); group.add_argument("--quarter"); group.add_argument("--latest",action="store_true"); group.add_argument("--all",action="store_true")
    parser.add_argument("--force",action="store_true"); parser.add_argument("--report-type",choices=["research_brief","content_brief"],default="research_brief")
    parser.add_argument("--model"); parser.add_argument("--limit",type=int); parser.add_argument("--dry-run",action="store_true")
    args=parser.parse_args(); archive=ROOT/"data/processed/content_lab"
    evidence=json.loads((archive/"story_evidence.json").read_text()); slates=json.loads((archive/"quarterly_story_slates.json").read_text())
    packets=select_packets(evidence,slates,args); config=IntelligenceConfig.from_env(); model=args.model or config.model
    cache=JsonReportCache(archive/"intelligence")  # dry-run never constructs an API client
    keys=[]
    from alt_asset_explorer.intelligence.cache import evidence_hash, make_cache_key
    for p in packets:
        digest=evidence_hash(p); key=make_cache_key(story_id=p["story_id"],evidence_digest=digest,prompt_version=config.prompt_version,schema_version=config.schema_version,model=model,report_type=args.report_type)
        keys.append((p,key,cache.load(p["story_id"],key) is not None))
    hits=sum(hit and not args.force for _,_,hit in keys); misses=len(keys)-hits
    print(json.dumps({"stories_selected":len(keys),"cache_hits":hits,"cache_misses":misses,"expected_api_calls":misses,"model":model,"report_type":args.report_type,"story_ids":[p["story_id"] for p,_,_ in keys]},indent=2))
    if args.dry_run: return 0
    client=OpenAIResponsesClient(os.getenv("OPENAI_API_KEY")); engine=IntelligenceEngine(client,cache,config)
    failures=0
    for packet,_,_ in keys:
        try:
            result=engine.generate_report(packet,report_type=args.report_type,model=model,force=args.force)
            print(f"{packet['story_id']}: {result.cache_status} {result.cache_key}")
        except Exception as exc:
            failures+=1; print(f"{packet['story_id']}: ERROR {exc}",file=sys.stderr)
    return 1 if failures else 0


if __name__=="__main__": raise SystemExit(main())
