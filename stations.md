# Stations Used in This Analysis

Zone 7's StreamTracker network includes more sensors than are analyzed here.
This project uses a fixed set of **11 stations** (14 downloaded files, since
some combo stations have both a Stream and a Rain/Precipitation export) to
keep the analysis reproducible. To reproduce these exact results, download
CSVs for the following stations from
[streamtracker.zone7waterca.gov/api/download.html](https://streamtracker.zone7waterca.gov/api/download.html):

| Station | Type | Format | Date Range Downloaded |
|---|---|---|---|
| Alamo Creek at Willow Drive near Dublin | Stream | CSV | Oct 2022 to Aug 2026 |
| Altamont Creek at Bluebell Dr | Stream | CSV | Oct 2022 to Aug 2026 |
| Altamont Creek at Pasatiempo Street | Rain / Precipitation | CSV | May 2023 to Aug 2026 |
| Arroyo Las Positas at Livermore | Stream | CSV | Oct 2022 to Aug 2026 |
| Arroyo Las Positas at Northfront Road | Rain / Precipitation | CSV | Apr 2023 to Aug 2026 |
| Arroyo Valle at Pleasanton | Stream | CSV | Nov 2022 to Aug 2026 |
| Dublin Creek at Interstate 680 | Stream | CSV | Nov 2025 to Aug 2026 |
| Dublin Creek at Interstate 680 (with rain gauge) | Rain / Precipitation | CSV | Nov 2025 to Aug 2026 |
| Line G1 at Dublin Blvd (with rain gauge) | Stream | CSV | Oct 2022 to Aug 2026 |
| Line G3 at Fairlands Dr (with rain gauge) | Stream | CSV | Jun 2023 to Aug 2026 |
| Line G3 at Fairlands Dr (with rain gauge) | Rain / Precipitation | CSV | Jun 2023 to Aug 2026 |
| Rain Gauge at Dyer Rd | Rain / Precipitation | CSV | Oct 2022 to Aug 2026 |
| Tassajara Creek below I-580 (with rain gauge) | Stream | CSV | Oct 2022 to Aug 2026 |
| Tassajara Creek below I-580 (with rain gauge) | Rain / Precipitation | CSV | Oct 2022 to Aug 2026 |

**Selection rationale:** these were the stations available/selected at the
time of download. This is a sample of Zone 7's network, not the full set.
For every combo station (has both a stream gauge and a rain gauge), both
the Stream and Rain/Precipitation exports were downloaded, even though (as
documented in `docs/data_quality_findings.md`) they turned out to contain
identical data. This was done for completeness before that redundancy was
discovered. `scripts/load_csvs.py` deduplicates them automatically.

**To extend this analysis:** additional stations can be downloaded and
dropped into `data/raw/`. `load_csvs.py` will pick up any CSV following
the site's filename convention without code changes. Results in
`docs/data_quality_findings.md` would need to be re-run to reflect the
larger station set.
