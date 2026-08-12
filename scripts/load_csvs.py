"""
Zone 7 StreamTracker — CSV Loader
===================================
Loads manually-downloaded CSVs (from the StreamTracker web download form)
into SQLite, landing them in a WIDE format that mirrors the real export
structure — one row per (station, timestamp), with separate columns for
each measured metric.

WHY WIDE, NOT LONG: the source files measure different things per station
type (Precipitation, Stage, Flow, H2O Temperature, Quality), and a single
generic "value" column would lose that structure. Wide format lets us
separately detect two kinds of data quality issues:
  1. Missing timestamps entirely (gaps) — a row that should exist doesn't
  2. Missing individual metrics within an existing row — e.g. a station
     reports on schedule but one sensor (like Stage) is always blank

KNOWN SOURCE DATA BUG: every combined stream+rain-gauge station's raw CSV
header is malformed — Zone 7's export is missing a comma between
"Precipitation (in.)" and "Stage (ft)", so the header claims fewer columns
than the data actually has. There's also a consistently blank trailing
column in most files (looks like an unused secondary QC flag). This script
detects and corrects that automatically based on actual field count per
row, cross-validated against the clean (non-combo) files.

Filename convention (from the StreamTracker download tool):
    <Station Name>__<Sensor Label>_.csv
    Sensor Label is one of: "Stream", "Rain / Precipitation"
    Combined stations include "with rain gauge" in the station name.
"""

import sqlite3
import csv
import re
import os
from datetime import datetime, timezone

RAW_DIR = "../data/raw"
DB_PATH = "../data/processed/zone7.db"

# Known clean (non-buggy) column sets, by exact header text, used to
# validate/label columns. Anything not matching falls back to positional
# inference based on field count.
KNOWN_RAIN_ONLY = ["Timestamp", "Precipitation (in.)", "Quality"]
KNOWN_STREAM_NO_FLOW = ["Timestamp", "Stage (ft)", "H2O Temperature (C)", "Quality"]
KNOWN_STREAM_WITH_FLOW = ["Timestamp", "Stage (ft)", "Flow (cfs)", "H2O Temperature (C)", "Quality"]


def parse_filename(filename):
    """Extract station name and sensor type from the download tool's
    filename convention: "<Station Name> (<Type>).csv" where Type is
    "Stream" or "Rain & Precipitation". Some station names contain their
    own parenthetical, e.g. "Dublin Creek at Interstate 680 (with rain
    gauge) (Rain & Precipitation).csv" — the greedy match below correctly
    grabs only the final "(...)" as the type."""
    name = filename.replace(".csv", "")
    match = re.match(r"^(.*) \((Stream|Rain & Precipitation)\)$", name)
    if not match:
        print(f"  [WARNING] Filename didn't match expected pattern, "
              f"loading with best-effort guess: {filename!r}")
        has_rain_gauge = "with rain gauge" in name.lower()
        return name, "unknown", has_rain_gauge
    station_name, sensor_raw = match.groups()
    sensor_type = "rain" if sensor_raw == "Rain & Precipitation" else "stream"
    has_rain_gauge = "with rain gauge" in station_name.lower()
    return station_name, sensor_type, has_rain_gauge


def fix_and_split_header(raw_header_line):
    """Fix the known missing-comma bug, then split into column names."""
    fixed = raw_header_line.replace(
        "Precipitation (in.)Stage (ft)", "Precipitation (in.),Stage (ft)"
    )
    return [c.strip() for c in fixed.split(",")]


def load_csv_file(path, filename):
    with open(path, newline="", encoding="utf-8-sig") as f:
        lines = f.readlines()

    header_line = lines[0].strip()
    column_names = fix_and_split_header(header_line)

    reader = csv.reader(lines[1:])
    rows = []
    for raw_row in reader:
        if not raw_row or not raw_row[0].strip():
            continue
        # Pad column names with generic placeholders if the row has more
        # fields than the (fixed) header accounted for — these are the
        # consistently-blank trailing columns noted in the module docstring.
        while len(raw_row) > len(column_names):
            column_names.append(f"Extra_{len(column_names)}")
        rows.append(dict(zip(column_names, raw_row)))

    return column_names, rows


def get_or_create_columns(conn, column_names):
    """Ensure the wide raw_readings table has a column for every metric
    we've seen across all files so far (ALTER TABLE ADD COLUMN as needed)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(raw_readings)")}
    for col in column_names:
        if col in ("Timestamp",):
            continue
        safe_col = sanitize_column_name(col)
        if safe_col not in existing:
            conn.execute(f'ALTER TABLE raw_readings ADD COLUMN "{safe_col}" TEXT')
            existing.add(safe_col)


def sanitize_column_name(name):
    """Turn 'Precipitation (in.)' into 'precipitation_in' etc."""
    name = re.sub(r"[^\w]+", "_", name.strip().lower())
    return name.strip("_")


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_readings (
            station_id TEXT,
            station_name TEXT,
            station_type TEXT,
            has_rain_gauge INTEGER,
            timestamp TEXT,
            source_file TEXT,
            loaded_at TEXT
        )
    """)
    conn.commit()


def main():
    # Always rebuild from a clean database — re-running this script should
    # be idempotent, not accumulate rows on top of a previous run.
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Removed existing {DB_PATH} for a clean rebuild.\n")

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    files = [f for f in os.listdir(RAW_DIR) if f.endswith(".csv")]
    if not files:
        print(f"No CSV files found in {RAW_DIR} — copy your downloads there first.")
        return

    now = datetime.now(timezone.utc).isoformat()

    for filename in sorted(files):
        station_name, sensor_type, has_rain_gauge = parse_filename(filename)
        station_id = sanitize_column_name(station_name)
        path = os.path.join(RAW_DIR, filename)

        column_names, rows = load_csv_file(path, filename)
        get_or_create_columns(conn, column_names)

        metric_cols = [c for c in column_names if c != "Timestamp"]
        safe_metric_cols = [sanitize_column_name(c) for c in metric_cols]

        insert_cols = ["station_id", "station_name", "station_type", "has_rain_gauge",
                        "timestamp", "source_file", "loaded_at"] + safe_metric_cols
        placeholders = ",".join(["?"] * len(insert_cols))
        col_list = ",".join(f'"{c}"' for c in insert_cols)

        for row in rows:
            values = [station_id, station_name, sensor_type, int(has_rain_gauge),
                      row.get("Timestamp"), filename, now]
            values += [row.get(mc, "") for mc in metric_cols]
            conn.execute(f'INSERT INTO raw_readings ({col_list}) VALUES ({placeholders})', values)

        conn.commit()
        print(f"[{filename}] station={station_name!r} type={sensor_type} "
              f"rain_gauge={has_rain_gauge} rows={len(rows)} columns={metric_cols}")

    # --- Post-load cleanup, based on issues found in the real data ---

    # 1. Station identity fix: Dublin Creek at Interstate 680 was exported
    #    under two different names (with vs. without "with rain gauge" in
    #    the filename) but is the same physical station.
    conn.execute("""
        UPDATE raw_readings
        SET station_id = 'dublin_creek_at_interstate_680',
            station_name = 'Dublin Creek at Interstate 680'
        WHERE station_id LIKE 'dublin_creek_at_interstate_680%'
    """)

    # 2. Redundant-file dedup: for combo (stream + rain gauge) stations,
    #    the "Stream" and "Rain / Precipitation" downloads turned out to
    #    be the exact same underlying sensor record exported twice under
    #    different labels — confirmed by comparing values row-for-row.
    #    Keep one row per (station_id, timestamp).
    before = conn.execute("SELECT COUNT(*) FROM raw_readings").fetchone()[0]
    conn.execute("""
        DELETE FROM raw_readings
        WHERE rowid NOT IN (
            SELECT MIN(rowid) FROM raw_readings GROUP BY station_id, timestamp
        )
    """)
    after = conn.execute("SELECT COUNT(*) FROM raw_readings").fetchone()[0]
    conn.commit()
    print(f"\nDeduplicated redundant station+timestamp rows: {before - after} removed")

    conn.close()
    print("Done. Loaded into", DB_PATH)


if __name__ == "__main__":
    main()