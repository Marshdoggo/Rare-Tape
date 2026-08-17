# Rare Tape Agent Guidance

Before changing this repository, read `docs/PROJECT_CONTEXT.md`. It is the canonical briefing for the product state, architecture, data provenance, limitations, and current priorities.

- Preserve the distinction between source data, normalized observations, processed research outputs, and experimental estimates.
- Never present SEC-derived series as live Rally listings or experimental fair value as a definitive appraisal.
- Keep Streamlit runtime reads limited to committed processed, normalized, report, and curated-index artifacts.
- Do not commit secrets, SEC caches, manual research inputs/history, quarantined rows, source captures, or local custom-index saves.
- Run `pytest -q` after code changes and smoke-test `streamlit run app/Home.py` after UI or deployment changes.
- Refresh `docs/PROJECT_CONTEXT.md` whenever architecture, data flow, shipped capabilities, material dataset coverage, risks, or deployment behavior changes.

