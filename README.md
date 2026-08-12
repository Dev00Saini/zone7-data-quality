# Zone 7 StreamTracker: Sensor Data Quality Analysis

**Question:** Which stream/rainfall sensor stations have the most data quality
issues, and what's a reliable way to detect and handle gaps in 15-minute
interval sensor data?

## Background

[Zone 7 Water Agency](https://www.zone7waterca.gov/) manages flood protection
and water resources for California's Tri-Valley region and publishes 15-minute
interval streamflow and rainfall sensor data through their public
[StreamTracker API](https://streamtracker.zone7waterca.gov/api/), starting
October 2022. The agency explicitly flags the data as preliminary and
containing gaps/errors — which makes it a good real-world data hygiene case
study rather than a pre-cleaned dataset.

## Approach

1. **Ingest** — pull raw 15-minute readings for a set of stream and rain
   stations via the API, landing them untouched into SQLite (`raw_readings`).
   Nothing is cleaned at this stage — the raw layer is preserved so every
   downstream decision is auditable.
2. **SQL-driven quality analysis** — all detection logic lives in SQL, not
   pandas:
   - Deduplication check
   - Completeness (% of expected 15-min readings actually present, per station)
   - Gap detection via window functions (`LAG` to compare consecutive timestamps)
   - Per-station gap scorecard (count, total missing time, longest outage)
   - Out-of-range value flagging
3. **Findings & recommendation** — documented in
   [`docs/data_quality_findings.md`](docs/data_quality_findings.md), including
   a proposed gap-handling strategy (interpolate vs. exclude vs. flag) based on
   gap length.

## Results

*(Summary — fill in after running the analysis. See `docs/data_quality_findings.md`
for the full write-up.)*

## Project Structure

```
├── data/
│   ├── raw/                          # (unused — API landed directly to SQLite)
│   └── processed/
│       ├── zone7.db                  # SQLite: raw_readings, ingestion_log
│       └── *.csv                     # exported query results
├── scripts/
│   ├── ingest.py                     # API -> SQLite, raw landing
│   └── run_analysis.py               # runs sql/data_quality_analysis.sql, exports CSVs
├── sql/
│   └── data_quality_analysis.sql     # all gap-detection / quality-scoring queries
├── docs/
│   └── data_quality_findings.md      # the actual write-up / deliverable
└── README.md
```

## How to Run

```bash
pip install requests pandas

# 1. Confirm the real API request shape (see scripts/ingest.py docstring),
#    then populate the STATIONS dict in scripts/ingest.py.

cd scripts
python ingest.py            # pulls raw data into ../data/processed/zone7.db
python run_analysis.py      # runs SQL analysis, exports CSVs, prints summary
```

Then fill in `docs/data_quality_findings.md` with the real results.

## Tech Stack

Python (requests, pandas) · SQL (SQLite — window functions, CTEs) · Zone 7 StreamTracker API

## Notes on Data Source

Zone 7's data is preliminary and may contain agency-side errors independent of
transmission gaps. This project focuses specifically on detecting *missing*
and *anomalous* readings from a data-engineering standpoint, not on validating
the underlying sensor accuracy.
