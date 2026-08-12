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

## Stations Analyzed

This project uses a fixed set of 11 stations (14 files, since combo stations
have both a Stream and Rain export). Full list, types, and date ranges:
[`docs/stations.md`](docs/stations.md) — download those specific stations to
reproduce these exact results, or add more CSVs to `data/raw/` to extend
the analysis to additional stations.

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

Across 11 stations and up to ~4 years of 15-minute data, completeness ranged
from **57.3% to 95.5%**. **Altamont Creek at Bluebell Dr** and **Arroyo Valle
at Pleasanton** were the worst performers, each missing 12,000+ hours of
readings, largely driven by single multi-day sensor outages rather than
routine gaps (98.4% of all gaps resolve within 2 hours).

Notably, the data pipeline itself introduced more apparent "bad data" than
the sensors did: a duplicated station identity and a fully-redundant file
export together accounted for ~19% of initially-loaded rows being exact
duplicates, and a floating-point rounding issue in date-difference math
produced ~380,000 false "gaps" before the detection threshold was corrected.
Full write-up, numbers, and methodology: [`docs/data_quality_findings.md`](docs/data_quality_findings.md).

## Project Structure

```
├── data/
│   ├── raw/                          # manually downloaded station CSVs (not committed)
│   └── processed/
│       ├── zone7.db                  # SQLite: raw_readings (wide format)
│       └── gap_summary_by_station.csv
├── scripts/
│   └── load_csvs.py                  # CSV -> SQLite, incl. header-bug fix, dedup, station merge
├── sql/
│   └── data_quality_analysis.sql     # all gap-detection / quality-scoring queries
├── docs/
│   └── data_quality_findings.md      # the actual write-up / deliverable, with real numbers
└── README.md
```

## How to Run

```bash
pip install pandas

# 1. Download CSVs for the stations listed in docs/stations.md from
#    https://streamtracker.zone7waterca.gov/api/download.html
#    and place them in data/raw/

cd scripts
python load_csvs.py         # loads CSVs -> ../data/processed/zone7.db,
                             # fixes the known header bug, merges the
                             # duplicate Dublin Creek station identity,
                             # and dedupes redundant combo-station exports
```

Then run the queries in `sql/data_quality_analysis.sql` against
`data/processed/zone7.db` (e.g. via `sqlite3` CLI or `pandas.read_sql_query`)
to reproduce the analysis in `docs/data_quality_findings.md`.

## Tech Stack

Python (pandas) · SQL (SQLite — window functions, CTEs) · Zone 7 StreamTracker portal (manual CSV export)

## Notes on Data Source

Zone 7's data is preliminary and may contain agency-side errors independent of
transmission gaps. This project focuses specifically on detecting *missing*
and *anomalous* readings from a data-engineering standpoint, not on validating
the underlying sensor accuracy.
