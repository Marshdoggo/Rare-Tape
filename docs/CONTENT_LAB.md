# Rally Terminal Content Lab

## Purpose and architecture

Content Lab is a deterministic analytical assignment desk. It searches canonical Rally evidence for measurable extremes, divergences, contrasts and market-structure caveats before any narrative is written. It is not a live listing feed, causal model, appraisal, or LLM copywriter.

The dependency flow is deliberately one-way:

`canonical Rally analytics → ContentLabEngine → StoryLead/Story Evidence Packet → future narrative layer`

Core logic lives in `src/alt_asset_explorer/content_lab/`: `models.py` defines the contract, `engine.py` prepares point-in-time metrics and detectors, `scoring.py` ranks and diversifies leads, and `storage.py` writes reviewable artifacts. `app/pages/9_Content_Lab.py` is a read-only archive browser. No core calculation lives in Streamlit.

## Canonical inputs

- `data/normalized/assets.csv`: identity and category metadata.
- `data/normalized/price_observations.csv`: authored dated prices and quarter labels.
- `data/processed/benchmark_history.parquet` (CSV fallback): committed Benchmark Lab history.
- `data/processed/rally_exits.csv`: contextual confirmed exit records.
- `data/processed/liquidity_metrics.csv`: existing liquidity output (accepted by the engine; historical staleness is recomputed point-in-time from dated observations).
- dated, officially available valuation artifacts only. Version one conservatively emits no fair-value lead when temporal availability or official-value status cannot be established.

The engine reuses Benchmark Lab validation and follows the canonical quarterly/index convention: positive authored prices, no interpolation, actual evidence dates, and explicit staleness limits.

## StoryLead and evidence packets

`StoryLead` contains period/as-of/mode, family/type, subjects, thesis, atomic facts, metrics and sample sizes, score dimensions, quality, caveats, allowed claims, unsupported follow-up questions, visual suggestions, formats, franchises, and sources. `to_evidence_packet()` exposes only structured facts and guardrails so a downstream system does not need to extract numbers from prose.

## Detectors shipped

The first functional library covers extreme movers, dataset-period highs/deep drawdowns, benchmark divergence, category leaders/laggards, systematic within-category contrasts, dispersion/breadth, stale-price/data-quality leads, and confirmed exits. Every detector discovers subjects from data; none contains asset-specific rules. Correlation and fair-value families fail closed when overlap or temporally valid valuation evidence is insufficient.

The modular detector boundary is the family block in `ContentLabEngine.discover`; a future refactor can register detector classes without changing the StoryLead contract. Next priorities are rolling-correlation regime shifts, point-in-time exit benchmark comparisons, index attribution/concentration, valuation manifest dating, volatility compression, and streak/rank-history detectors.

## Historical and as-of behavior

`discover_quarters` exposes a calendar quarter only when at least two assets have valid observations whose **actual `observed_at` is on or before `period_end`**. For a selected quarter, start and end snapshots use only actual evidence dated before the relevant boundary. A later observation carrying an older quarter label cannot enter the earlier result. The default and currently shipped mode is `contemporaneous`; hindsight mode is reserved for a later build and is not silently simulated.

Stale snapshot values older than 186 days are excluded by default. Historical rankings can still revise when researchers add genuinely historical evidence; the archive represents the current canonical source version, not proof of catalog completeness at the historical date.

## Scoring, quality and deduplication

Weights are configured in `config/content_story_scoring.yml`: extremeness 24%, magnitude 18%, contrast 16%, novelty 10%, quality 10%, persistence 8%, breadth 8%, and deterministic narrative usefulness 6%. Inputs are bounded to `[0,1]`. The weighted score is multiplied by `0.65 + 0.35 × data_quality`, which prevents a spectacular but weak observation from winning solely on magnitude. The minimum quality is 0.25.

Ranking uses score descending and stable story ID ascending. Deduplication permits one lead per period/subject/family, at most two leads per subject and five per family in a slate. This makes rankings reproducible while retaining more than one genuinely different angle. Archive summaries expose raw, post-quality, post-deduplication, and final-slate counts.

Quality incorporates observation counts, cross-sectional breadth, staleness and detector-specific confirmation. Caveats distinguish low measured volatility from sparse or stale marking. Coincidence is reported as coincidence; causal explanations are always research questions.

## Outputs and CLI

Run:

```bash
python scripts/build_content_lab.py --all-quarters
python scripts/build_content_lab.py --quarter 2025Q4
python scripts/build_content_lab.py --latest --limit 50
```

The builder writes deterministic, reviewable files under `data/processed/content_lab/`:

- `story_leads.csv`: scalar table used by Streamlit;
- `story_evidence.json`: complete evidence packets keyed by story ID;
- `quarterly_story_slates.json`: generation counts and ordered story IDs.

The UI offers period, family, category, quality and count filters, a ranked terminal-style table, detail view, evidence chart, caveats, research backlog, visual suggestions and transparent JSON.

## Known limitations and extension points

Sparse quarterly prices cannot reveal intraperiod paths. Point-in-time share-count/status history is incomplete. Historical category membership uses current canonical identity metadata. Current benchmark comparison uses available committed endpoints rather than a causal model. Exit analytics do not yet compute holding-period benchmark returns. Category means are asset-return summaries, not claims about an investable category portfolio. Correlation, regime-change, valuation-gap, contribution/concentration, streak and full risk-adjusted detectors require further point-in-time infrastructure and therefore fail closed rather than fabricate coverage.

New detectors should consume a truncated context, emit atomic facts and sample sizes, label estimation explicitly, and add synthetic leakage/insufficient-data tests.

## Future LLM Integration

A future independent narrative service may take `story.to_evidence_packet()` and use the OpenAI Responses API to propose headline options, Reel hooks/scripts, YouTube outlines, long-form briefs, counterarguments, external research plans, titles/thumbnails, or newsletter drafts. Its instruction must be: *these are the facts; tell the story around them; do not invent additional facts*. Statistical discovery, eligibility, scoring, evidence and ranking must remain fully functional without that service and must never depend on generated prose.
