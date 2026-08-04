# Rally Terminal Asset Valuation Library

The valuation library adds a four-layer asset-level research workflow:

1. `factors.json` — observed asset facts, category factors, missing fields, derived scores, and analyst judgments.
2. `research.json` — documented external evidence, comparable sales, market context, limitations, and source ledger.
3. `valuation.json` — deterministic output from the configured v1 valuation engine.
4. `report.md` — narrative explanation rendered in Streamlit; it is never parsed as the authoritative data source.

Files live under `data/valuation_library/<ASSET_ID>/`, with `source_material/` and timestamped `revisions/` directories for revision safety. The manifest at `manifest.json` is regenerable from the directory contents.

## Manual ChatGPT workflow

1. In ChatGPT, prepare `factors.json` and `research.json` from Rally screenshots, specs, provenance, condition notes, quarterly prices, and this methodology.
2. In Rally Terminal, open `app/pages/8_Valuation_Library.py`, choose **Data Intake and Validation**, paste or upload both JSON blocks, validate, save, and run valuation.
3. Download **ChatGPT Report Package**. It contains `factors.json`, `research.json`, `valuation.json`, and `report_generation_instructions.md`.
4. Bring that package and `methodology/fair_value_methodology_v1.md` back to ChatGPT to draft `report.md`.
5. Return to Rally Terminal, use **Report Intake and Display**, paste or upload `report.md`, preview, and save.

CLI valuation example:

```bash
python scripts/run_valuation.py --asset SYNTHETIC-ASSET
```

The command writes `data/valuation_library/SYNTHETIC-ASSET/valuation.json` and refreshes `manifest.json`.

## Methodology versions

General assumptions are in `methodology/valuation_engine_v1.yaml`. Category models are in `methodology/categories/*_v1.yaml`. The v1 engine uses eligible sold comparable observations, configured adjustment multipliers, normalized weights from similarity, evidence quality, recency, and verification status, and weighted quantiles for conservative/base/optimistic estimates.

All v1 parameters are provisional. If comparable evidence is insufficient, the engine returns `valuation_status: insufficient_evidence` and `official_value_available: false` rather than a confident fair-value spectrum.

## Adding a category

Add a new category literal in `src/alt_asset_explorer/valuation_library/models.py`, add a matching YAML file under `methodology/categories/`, and add tests for validation, evidence thresholds, and expected warnings.

## Tests

Run:

```bash
pytest -q
```
