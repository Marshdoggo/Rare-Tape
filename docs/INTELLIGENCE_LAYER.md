# Rally Terminal Intelligence Layer

## Purpose and boundary

Build 2 turns a deterministic `StoryEvidencePacket` into a structured research or content brief. The dependency remains one-way: canonical analytics → Content Lab → evidence packet → Intelligence → cached report → UI. Generated language explains and frames evidence; it never replaces Rally Data as the source of financial/statistical facts. Reports explicitly separate **FACT**, **INTERPRETATION**, **HYPOTHESIS**, and **UNKNOWN**.

The old broad `ai_context.json` outputs and retired AI context page are not report inputs. A request receives only its selected evidence packet.

## Architecture and Responses API

`src/alt_asset_explorer/intelligence/` contains typed Pydantic contracts (`models.py`), centralized configuration, stable prompts and family guidance, canonical hashing/cache storage, a thin official OpenAI SDK adapter, orchestration/validation, and a pure UI-state helper. Streamlit and the CLI never call the SDK directly. The adapter uses `client.responses.parse(...)` with a Pydantic Structured Output; legacy Chat Completions are not used.

The default is `gpt-5-mini`, selected as a configurable, cost-conscious model suitable for grounded structured generation. Override it with `RALLY_OPENAI_MODEL` or CLI `--model`. Configuration also centralizes low reasoning effort, medium verbosity, a 6,000-output-token ceiling, `story_intelligence_v1`, `story_intelligence_schema_v1`, and the default `research_brief` type.

Only `internal_only` mode is enabled. Prompts put the stable grounding/style prefix before dynamic family guidance and canonical evidence, which is friendly to provider prompt caching. A future `research_enhanced` mode can add `tools=[{"type":"web_search"}]` inside the client adapter without changing callers, but must keep external claims distinct and is intentionally disabled now.

## Report schema and grounding

`StoryIntelligenceReport` contains provenance plus a structured content object. Content includes headline/dek, executive summary, happened/importance/historical/market context, interpretations, possible explanations, counterarguments, caveats, unknowns, next research, short/long angles, editorial content-brief fields, article Markdown, and a claim audit. The audit maps supported claims to evidence JSON paths and separately lists interpretations, hypotheses, unknowns, and unsupported claims avoided.

Before saving, Pydantic rejects missing/extra fields and empty required prose; orchestration rejects a mismatched story ID. A conservative numeric scan warns when percentage tokens in article prose are not found verbatim in the packet. This is a review flag, not a brittle theorem prover. The prompt prohibits invented financial numbers, causal conclusions from coincidence, definitive appraisals, and presentation of SEC context as live listings.

## Cache, invalidation, and provenance

Canonical JSON uses sorted keys and compact deterministic separators. The evidence SHA-256 is stable across dictionary key ordering. The cache key is SHA-256 over story ID, evidence hash, prompt version, schema version, model, and report type. Any material change creates a miss; an identical request returns the JSON without an API call.

Files live at `data/processed/content_lab/intelligence/<story_id>/<cache_key>.json`, with `latest.json` for inspection and `revisions/` preserving the previous file on forced regeneration. These runtime reports are ignored by Git: they may contain costly generated output and can be reviewed/promoted through a future editorial workflow. Each file records story/evidence identity, prompt/schema/model/type/mode, response ID, UTC generation time, validation warnings, and token usage (including cached-input/reasoning tokens when supplied).

This local adapter works for development and a single running process, but Streamlit Community Cloud storage is ephemeral and not shared across replicas. It must not be treated as durable production persistence. `JsonReportCache` is deliberately isolated so object storage or a database can replace it later. Committed reports, if later desired, require an explicit editorial promotion policy.

## Streamlit workflow and failures

Content Lab always renders Rally Data first. Rally Intelligence then checks cache without constructing an API client. Missing state offers **Generate Intelligence Report**; cached state immediately renders the same report, structured audit, provenance, and usage. **Regenerate report** explains that it makes another request and preserves a revision. Report type is selectable. No page load generates content.

`OPENAI_API_KEY` can be supplied through the environment or Streamlit secrets; it is never rendered, logged, or serialized. `.env*` and `.streamlit/secrets.toml` remain ignored. Missing credentials, corrupt cache, validation issues, SDK/network/rate-limit/timeout/model failures are surfaced as controlled messages while deterministic Content Lab remains usable.

## CLI

```bash
python scripts/build_story_intelligence.py --story-id STORY_ID --dry-run
python scripts/build_story_intelligence.py --quarter 2026Q3 --report-type research_brief
python scripts/build_story_intelligence.py --latest --limit 5
python scripts/build_story_intelligence.py --all --dry-run
```

Options include `--force`, `--model`, `--report-type research_brief|content_brief`, `--limit`, and `--dry-run`. Dry-run performs no client construction and prints selected IDs, hits, misses, and expected calls. Normal bulk execution is synchronous and cache-first.

For later archive enrichment, the same static instructions, dynamic input, model, and JSON schema can be emitted as JSONL requests with `custom_id` equal to the cache identity and submitted through the Batch API to `/v1/responses`. Completed records should pass through the same validation/cache writer. Batch submission and polling are deliberately outside this MVP.

## Future Content Factory

The structured report is the research brain for Build 3 outputs (scripts, Reels, carousel, captions, newsletter, and title/thumbnail tests); Build 2 does not generate those finished assets. Recommended Build 2.5 work is a durable object-storage adapter, editorial approval/promotion state, stronger evidence-path auditing, and optional isolated external-research citations before a Content Factory is added.
