# Data Quality Findings — Zone 7 StreamTracker Sensors

*Fill this in after running `run_analysis.py`. This is the actual deliverable —
the queries are just how you got here.*

## Summary

*(1-2 sentences: which stations are worst, roughly how bad, and your recommended
handling strategy. This is what a reviewer reads first.)*

## Methodology

- Pulled 15-minute interval readings for [N] stream stations and [N] rain stations,
  water year [20XX] ([start date] to [end date]), via the Zone 7 StreamTracker API.
- Landed raw data untouched into SQLite (`raw_readings` table) before any cleaning,
  so every finding below is traceable back to the original source.
- Detected gaps using a window-function query comparing each reading's timestamp to
  the previous reading for that station; any interval over 15 minutes is flagged.

## Findings

### Completeness by station

*(Paste/summarize output of query #2 — % complete per station)*

| Station | % Complete | Notes |
|---|---|---|
| | | |

### Worst gaps

*(Paste/summarize output of query #4 — ranked by total missing time)*

| Station | # Gaps | Total Missing (hrs) | Longest Gap |
|---|---|---|---|
| | | | |

### Duplicate readings

*(Any found? How many, which stations?)*

### Out-of-range values

*(Any negative flow/rainfall or implausible spikes found?)*

## Recommended Gap-Handling Strategy

- **Short gaps (≤ 30 min):** linear interpolation — defensible since streamflow/rainfall
  change gradually at this timescale.
- **Medium gaps (up to a few hours):** exclude from daily aggregates rather than
  interpolate, to avoid false precision.
- **Long gaps / sensor outages:** exclude the affected day(s) from that station's
  rollups entirely, and log it here rather than silently dropping it.

*(Adjust these thresholds based on what the actual gap distribution looks like —
don't just keep the defaults if the data tells a different story.)*

## Limitations

- Data is explicitly labeled "preliminary" by Zone 7 and may contain uncorrected
  sensor errors beyond what this analysis caught.
- [Any other caveats specific to your actual run — API limits, date range constraints, etc.]
