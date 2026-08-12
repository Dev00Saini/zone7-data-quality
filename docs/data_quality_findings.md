# Data Quality Findings — Zone 7 StreamTracker Sensors

## Summary

Across 11 stations (6 stream, 5 rain/precipitation) covering up to ~4 years of
15-minute interval data, completeness ranged from **57.3% to 95.5%**.
**Altamont Creek at Bluebell Dr** and **Arroyo Valle at Pleasanton** were the
worst performers, each missing over 12,000 hours of readings. Most gaps are
short (98.4% resolve within 2 hours), but a small number of multi-day sensor
outages account for a disproportionate share of total missing time. Two
pipeline-level issues — a duplicated station identity and a fully-redundant
file export — were found and corrected before any of the above numbers were
calculated; both are documented below since they were bigger sources of
apparent "bad data" than the sensors themselves.

## Methodology

- Manually downloaded CSV exports (15-minute interval) for 11 stations from
  the [Zone 7 StreamTracker portal](https://streamtracker.zone7waterca.gov/api/download.html),
  covering the full available history (October 2022 – August 2026, coverage
  varies by station).
- Landed raw data into SQLite (`raw_readings`) in **wide format** — one row
  per station+timestamp, with separate columns per metric (Stage, Flow,
  Precipitation, Water Temperature, Quality) — rather than flattening to a
  single generic value, since different station types report different
  metric sets.
- Detected gaps using a `LAG()` window function comparing each reading's
  timestamp to the previous one for that station.

## Data Pipeline Issues Found (before any "gap" analysis)

These were caught and fixed in `scripts/load_csvs.py` before computing any
of the results below — worth documenting because they initially looked like
massive data quality problems and were not:

1. **Malformed source headers.** Every combined stream+rain-gauge station's
   raw CSV header is missing a comma between `Precipitation (in.)` and
   `Stage (ft)`, so the header claims fewer columns than the data rows
   actually have. Detected by comparing header column count against actual
   field count per row, and cross-validated against the clean (non-combo)
   station files. Fixed in the loader with a targeted string replace.

2. **Duplicate station identity.** *Dublin Creek at Interstate 680* was
   exported under two different names depending on which sensor view was
   selected on the download form — one plain, one with "with rain gauge"
   appended. Both had identical row counts (24,598), confirming they're the
   same physical station. Left unmerged, this would have double-counted
   Dublin Creek in any station-level ranking. Merged in the loader.

3. **Fully redundant file exports.** For every combo station (Tassajara
   Creek, Line G1, Line G3), downloading both the "Stream" view and the
   "Rain / Precipitation" view produced **identical rows** — same
   timestamps, same values, just under two different filenames. This
   initially appeared as 255,676 duplicate `(station, timestamp)` pairs
   (~19% of all loaded rows) in the raw load. Confirmed by direct row
   comparison, then deduplicated, keeping one copy per timestamp.

4. **Floating-point false positives in gap detection.** Using `JULIANDAY`
   date arithmetic, a normal back-to-back 15-minute reading occasionally
   computes as e.g. 15.00003 minutes due to floating-point rounding — which
   technically satisfies a `> 15 minutes` gap filter but isn't a real gap.
   This produced ~380,000 phantom "gaps" (nearly all of them exactly the
   expected interval, just off by a rounding error) before the threshold was
   corrected to `> 20 minutes`, which comfortably clears the floating-point
   noise while still catching every genuine missed reading — confirmed by
   checking that real gaps cluster tightly at 30, 45, 60+ minutes with
   essentially nothing between 15 and 20.

**Takeaway for the write-up:** roughly 19% of "duplicate" rows and nearly
all of ~380K "gaps" from a naive first pass were pipeline artifacts, not
real sensor problems. Validating your own ingestion logic before trusting
its output is itself a data-quality practice worth calling out.

## Findings

### Completeness by station (worst to best)

| Station | % Complete | Date Range |
|---|---|---|
| Altamont Creek at Bluebell Dr | 57.3% | Oct 2022 – Aug 2026 |
| Arroyo Valle at Pleasanton | 62.6% | Nov 2022 – Aug 2026 |
| Arroyo Las Positas at Northfront Road | 81.3% | Apr 2023 – Aug 2026 |
| Altamont Creek at Pasatiempo Street | 86.6% | May 2023 – Aug 2026 |
| Alamo Creek at Willow Drive near Dublin | 90.6% | Oct 2022 – Aug 2026 |
| Arroyo Las Positas at Livermore | 91.1% | Oct 2022 – Aug 2026 |
| Rain Gauge at Dyer Rd | 91.6% | Oct 2022 – Aug 2026 |
| Line G1 at Dublin Blvd (rain gauge) | 92.5% | Oct 2022 – Aug 2026 |
| Tassajara Creek below I-580 (rain gauge) | 93.6% | Oct 2022 – Aug 2026 |
| Line G3 at Fairlands Dr (rain gauge) | 94.5% | Jun 2023 – Aug 2026 |
| Dublin Creek at Interstate 680 | 95.5% | Nov 2025 – Aug 2026 (short/recent history) |

### Gap summary by station (ranked by total missing time, >20 min threshold)

| Station | # Gaps | Total Missing (hrs) | Longest Gap (hrs) |
|---|---|---|---|
| Altamont Creek at Bluebell Dr | 1,835 | 14,929.3 | 8,014.5 |
| Arroyo Valle at Pleasanton | 2,316 | 12,983.5 | 11,201.0 |
| Arroyo Las Positas at Northfront Road | 2,173 | 6,018.5 | 3,502.8 |
| Altamont Creek at Pasatiempo Street | 2,976 | 4,559.5 | 2,641.3 |
| Alamo Creek at Willow Drive near Dublin | 2,355 | 3,777.0 | 1,941.5 |
| Arroyo Las Positas at Livermore | 586 | 3,177.7 | 2,334.2 |
| Rain Gauge at Dyer Rd | 157 | 2,898.0 | 2,299.7 |
| Tassajara Creek below I-580 (rain gauge) | 2,781 | 2,866.3 | 788.3 |
| Line G1 at Dublin Blvd (rain gauge) | 509 | 2,677.7 | 1,925.5 |
| Line G3 at Fairlands Dr (rain gauge) | 2,727 | 2,208.5 | 453.8 |
| Dublin Creek at Interstate 680 | 1,161 | 582.3 | 1.2 |

**Worst overall: Altamont Creek at Bluebell Dr and Arroyo Valle at
Pleasanton** — both by completeness % and total missing hours, and both had
single outages exceeding 8,000 hours (roughly a year), suggesting extended
sensor or transmission failures rather than routine intermittent gaps.

### Gap length distribution (why the threshold matters)

Of 19,576 real gaps (after removing floating-point noise):
- **98.4%** are short — roughly 30 minutes to 2 hours (a handful of missed
  readings, likely transient connectivity issues)
- **1.4%** run 2 hours to 1 day
- **0.3%** (52 gaps) exceed a full day — these are the true sensor/system
  outages, and they're what drive the large "total missing hours" numbers
  above despite being a tiny fraction of gap *count*.

### Metric-level nulls (separate from timing gaps)

Beyond missing timestamps, some stations report on schedule but have a
metric column that's blank on every row — meaning a specific sensor isn't
installed or isn't reporting, not that data was lost in transit:

- Stations without a rain gauge (Alamo Creek, Altamont Creek Bluebell,
  Arroyo Valle at Pleasanton) show 100% blank Precipitation, as expected.
- Rain/precip-only stations show 100% blank Stage and Flow, as expected.
- **Arroyo Las Positas at Livermore** has Flow blank on 100% of rows despite
  reporting Stage normally — this station appears to lack (or never
  activated) a flow-rate sensor, while nearby stream stations report both.
  Worth a caveat if comparing flow across stations.

None of this is an error — it reflects which physical sensors each station
actually has — but it means "blank" needs to be interpreted per-station, not
treated as a uniform missing-data signal.

## Recommended Gap-Handling Strategy

Based on the actual gap distribution above (not a generic default):

- **Short gaps (≤ 2 hrs, 98.4% of cases):** linear interpolation is
  defensible — streamflow and rainfall change gradually at this timescale,
  and this covers nearly all real gaps in this dataset.
- **Medium gaps (2 hrs – 1 day, 1.4%):** exclude from daily aggregates
  rather than interpolate — long enough that false precision becomes a risk,
  short enough that dropping a single day is a reasonable trade-off.
- **Long outages (> 1 day, 0.3% of gaps but the majority of total missing
  time):** exclude affected day(s) entirely from that station's rollups.
  These 52 outages are concentrated in a small number of stations
  (especially Altamont Creek at Bluebell Dr and Arroyo Valle at Pleasanton)
  and likely reflect real equipment failures — worth flagging to a data
  consumer rather than smoothing over with interpolation.
- **Metric-level nulls:** don't interpolate at all — a sensor that's
  always blank isn't a timing gap, it's a missing capability. Flag
  separately from timestamp-gap statistics.

## Limitations

- Zone 7 explicitly labels this data "preliminary" and may contain
  agency-side sensor errors independent of the transmission gaps analyzed
  here (e.g. miscalibration) — this analysis only detects *missing* and
  *structurally anomalous* data, not measurement accuracy.
- Date ranges vary by station (some have ~4 years of history, others only a
  few months), so completeness % isn't perfectly apples-to-apples across
  stations with very different total observation windows.
