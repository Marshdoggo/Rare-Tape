# Rare Tape Content Lab

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

## Detectors shipped (Build 1.5)

The library covers the original mover, drawdown, benchmark, category, contrast, breadth, stale-mark and confirmed-exit families plus conservative correlation-regime changes, volatility expansion/compression, quarterly streaks, leaderboard rank jumps, temporally valid experimental fair-value gaps, canonical index attribution/winner concentration, equal- versus market-cap weighting divergence, and confirmed-exit holding-period SPY comparisons. Every detector discovers subjects from data; none contains asset-specific rules.

Advanced detectors live in `advanced.py` and compose Correlation Lab alignment/correlation, canonical index construction and Contribution Lab concentration metrics. Correlation uses comparable observation-count windows and fails closed below configured overlap. Volatility uses observation-to-observation returns and explicitly warns that sparse marking can create apparent compression.

Valuation temporal validity is owned by `valuation_library/temporal.py`. An authored `valuation_date` is high-confidence; a manifest valuation-file timestamp is accepted as low-confidence availability. Filesystem modification time is never authoritative. Missing dates and unofficial values fail closed, and a dated valuation cannot enter a quarter before its effective date. Values remain experimental estimates, never appraisals.

## Historical and as-of behavior

`discover_quarters` exposes a calendar quarter only when at least two assets have valid observations whose **actual `observed_at` is on or before `period_end`**. For a selected quarter, start and end snapshots use only actual evidence dated before the relevant boundary. A later observation carrying an older quarter label cannot enter the earlier result. The default and currently shipped mode is `contemporaneous`; hindsight mode is reserved for a later build and is not silently simulated.

Stale snapshot values older than 186 days are excluded by default. Historical rankings can still revise when researchers add genuinely historical evidence; the archive represents the current canonical source version, not proof of catalog completeness at the historical date.

## Scoring, quality and deduplication

Weights are configured in `config/content_story_scoring.yml`. Build 1.5 adds bounded historical-rarity, regime-change, rank-change, valuation-gap, contribution-concentration and benchmark-excess dimensions alongside the original dimensions. Inputs are bounded to `[0,1]`. The weighted score is multiplied by `0.65 + 0.35 × data_quality`, which prevents a spectacular but weak observation from winning solely on magnitude. The minimum quality is 0.25.

Ranking uses score descending and stable story ID ascending. Deduplication permits one lead per period/subject/family, at most two leads per subject and five per family in a slate; suppressed subject variants attach as secondary angles. This makes rankings reproducible while retaining more than one genuinely different angle. Archive summaries expose raw, post-quality, post-deduplication, and final-slate counts.

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

The canonical `python scripts/build_dataset.py` rebuild graph also regenerates the
complete archive after processed indexes and quarterly leaderboards. Consequently,
new normalized asset observations are discovered automatically during ordinary
asset-data uploads; Content Lab has no category or ticker allowlist to maintain.

The UI offers period, family, category, quality and count filters, a ranked terminal-style table, detail view, evidence chart, caveats, research backlog, visual suggestions and transparent JSON.

## Known limitations and extension points

Sparse quarterly prices cannot reveal intraperiod paths. Point-in-time share-count/status history is incomplete. Historical category membership uses current canonical identity metadata. Category means are asset-return summaries, not claims about an investable category portfolio. Exit comparisons currently guarantee SPY; category and broad Rally holding-period comparisons fail closed until a single exit-aware historical-series resolver is exposed. Valuation-gap closing/expansion also fails closed because the current library has one dated revision per covered asset. Correlations are descriptive and fair values remain experimental.

New detectors should consume a truncated context, emit atomic facts and sample sizes, label estimation explicitly, and add synthetic leakage/insufficient-data tests.

## Future LLM Integration

A future independent narrative service may take `story.to_evidence_packet()` and use the OpenAI Responses API to propose headline options, Reel hooks/scripts, YouTube outlines, long-form briefs, counterarguments, external research plans, titles/thumbnails, or newsletter drafts. Its instruction must be: *these are the facts; tell the story around them; do not invent additional facts*. Statistical discovery, eligibility, scoring, evidence and ranking must remain fully functional without that service and must never depend on generated prose.
