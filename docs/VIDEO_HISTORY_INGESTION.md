# Video History Ingestion Lab

This local-only experimental tool samples a Rally iOS chart screen recording, detects changed tooltip crops, uses Tesseract OCR, reconciles repeated readings by date, flags uncertainty, and exports review CSVs. It never writes canonical data.

## Install and run

Install Python 3.11, Tesseract (`brew install tesseract` on macOS), and the optional Python packages:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[video-ingestion]'
streamlit run app/legacy_pages/14_Video_History_Ingestion_Lab.py
```

## Recording and review workflow

1. Record in portrait orientation at native resolution. Keep notifications and unrelated content off screen.
2. Drag across the entire chart slowly and steadily, pausing briefly on each changed tooltip. Avoid covering the tooltip with a finger or cursor.
3. Upload MP4, MOV, or M4V and select the canonical asset (or explicitly enter an ID).
4. Scrub to a representative frame. Enter normalized crop coordinates that tightly contain the tooltip and no unrelated screen content.
5. Start near 10 sampled frames/second and 0.94 similarity. Increase sampling for fast movement; adjust similarity if states are missed or duplicated.
6. Run extraction. Tesseract is invoked only for materially changed crop states, not every frame.
7. Filter and review low-confidence, failed, or conflicting rows. Diagnostic crops are temporary and opt-in; inspect them before accepting questionable rows.
8. Download the reviewed CSV and diagnostics CSV. Downloads are staging evidence only, not import-ready canonical records.
9. Optionally upload a CSV with `observation_date`/`price_per_share` (canonical `observed_at` or processed `date`/`last` are also recognized) to inspect date recall, extraction precision, and exact price accuracy.

## Known limitations

- Crop selection uses explicit normalized numeric coordinates rather than a draggable canvas.
- Tesseract and the host `tesseract` binary are local requirements and are intentionally excluded from deployed dependencies.
- OCR quality depends heavily on recording resolution, tooltip contrast, motion blur, and a tight crop.
- Change detection compares consecutive processed crops; it does not yet inspect neighboring frames to select the sharpest representative.
- Numeric date ambiguity is rejected unless the operator selects a date order. Missing/unreadable values remain missing.
- Consensus is exact-value modal reconciliation; close-value clustering and richer abrupt-series diagnostics are future work.
- Temporary diagnostic crops last for the local Streamlit process and are not source captures intended for Git.
