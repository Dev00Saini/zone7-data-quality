"""
Zone 7 StreamTracker — CSV Loader (Azure SQL Database version)
================================================================
Same loader as scripts/load_csvs.py, adapted to write into Azure SQL
Database instead of local SQLite. See docs/azure_migration_plan.md for
the full migration plan and rationale.

DIALECT DIFFERENCES FROM THE SQLITE VERSION (this is the point of this
file — these are genuine T-SQL vs. SQLite differences, not just a
find-and-replace):

  1. Schema reset: SQLite version deleted the .db file to rebuild clean.
     You can't delete a hosted database, so this uses
     `IF OBJECT_ID('raw_readings','U') IS NOT NULL DROP TABLE raw_readings`
     instead.
  2. Column types: SQLite is dynamically typed, so every metric column
     was bare TEXT. Azure SQL is strongly typed — TEXT is a deprecated
     type there, so these are NVARCHAR(50) instead.
  3. Column introspection: `PRAGMA table_info(...)` is SQLite-only.
     Replaced with a query against INFORMATION_SCHEMA.COLUMNS, the
     ANSI-standard way to inspect a table's columns.
  4. Dedup logic: the SQLite version deleted duplicate rows using the
     implicit `rowid` every SQLite table has. Azure SQL has no such
     concept, so this uses ROW_NUMBER() OVER (PARTITION BY ...) inside a
     CTE, then deletes through the CTE — a different, more broadly
     "standard SQL" way to solve the same problem.
  5. Bulk inserts: the SQLite version's row-by-row conn.execute() calls
     are effectively free — no network involved. Over a real network
     connection to Azure SQL, one round-trip per row is impractically
     slow at this row count. This version batches each file's rows with
     pyodbc's fast_executemany, which is not a SQLite-vs-T-SQL dialect
     issue exactly, but a genuine "local file vs. networked database"
     consideration you don't hit until you migrate off local SQLite.

Everything else (filename parsing, header-bug fix, column sanitizing) is
identical to the original — those were never SQLite-specific.
"""

import pyodbc
import csv
import re
import os
from datetime import datetime, timezone

RAW_DIR = "../data/raw"

# --- Azure SQL connection ---
# Password is read from an environment variable so it's never hardcoded
# or committed to git. Set it in your terminal session before running:
#   PowerShell:  $env:AZURE_SQL_PASSWORD = "your_password_here"
AZURE_SERVER = "zone7analysis.database.windows.net"
AZURE_DATABASE = "zone7"
AZURE_UID = "DSaini17"
AZURE_PWD = os.environ.get("AZURE_SQL_PASSWORD")

if not AZURE_PWD:
    raise RuntimeError(
        "Set the AZURE_SQL_PASSWORD environment variable before running this script.\n"
        'PowerShell:  $env:AZURE_SQL_PASSWORD = "your_password_here"'
    )

CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={AZURE_SERVER},1433;"
    f"DATABASE={AZURE_DATABASE};"
    f"UID={AZURE_UID};"
    f"PWD={AZURE_PWD};"
    "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
)

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
        while len(raw_row) > len(column_names):
            column_names.append(f"Extra_{len(column_names)}")
        rows.append(dict(zip(column_names, raw_row)))

    return column_names, rows


def get_or_create_columns(conn, column_names):
    """Ensure the wide raw_readings table has a column for every metric
    we've seen across all files so far (ALTER TABLE ADD as needed).
    T-SQL note: no PRAGMA here — INFORMATION_SCHEMA.COLUMNS is the
    standard way to introspect a table's columns."""
    cur = conn.cursor()
    cur.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'raw_readings'
    """)
    existing = {row[0] for row in cur.fetchall()}
    for col in column_names:
        if col in ("Timestamp",):
            continue
        safe_col = sanitize_column_name(col)
        if safe_col not in existing:
            cur.execute(f'ALTER TABLE raw_readings ADD [{safe_col}] NVARCHAR(50)')
            conn.commit()
            existing.add(safe_col)


def sanitize_column_name(name):
    """Turn 'Precipitation (in.)' into 'precipitation_in' etc."""
    name = re.sub(r"[^\w]+", "_", name.strip().lower())
    return name.strip("_")


def init_db(conn):
    cur = conn.cursor()
    cur.execute("IF OBJECT_ID('raw_readings', 'U') IS NOT NULL DROP TABLE raw_readings")
    conn.commit()
    cur.execute("""
        CREATE TABLE raw_readings (
            station_id NVARCHAR(100),
            station_name NVARCHAR(200),
            station_type NVARCHAR(20),
            has_rain_gauge INT,
            timestamp NVARCHAR(50),
            source_file NVARCHAR(200),
            loaded_at NVARCHAR(50)
        )
    """)
    conn.commit()


def main():
    conn = pyodbc.connect(CONN_STR)
    cur = conn.cursor()
    init_db(conn)
    print(f"Connected to {AZURE_SERVER}/{AZURE_DATABASE}, raw_readings table (re)created.\n")

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
        col_list = ",".join(f"[{c}]" for c in insert_cols)

        # Build all rows for this file as a list of tuples, then send them
        # in one batched round-trip instead of one execute() per row.
        batch = []
        for row in rows:
            values = [station_id, station_name, sensor_type, int(has_rain_gauge),
                      row.get("Timestamp"), filename, now]
            values += [row.get(mc, "") for mc in metric_cols]
            batch.append(tuple(values))

        cur.fast_executemany = True
        cur.executemany(f'INSERT INTO raw_readings ({col_list}) VALUES ({placeholders})', batch)

        conn.commit()
        print(f"[{filename}] station={station_name!r} type={sensor_type} "
              f"rain_gauge={has_rain_gauge} rows={len(rows)} columns={metric_cols}")

    # --- Post-load cleanup, based on issues found in the real data ---

    # 1. Station identity fix (same as original — plain UPDATE, no dialect change needed).
    cur.execute("""
        UPDATE raw_readings
        SET station_id = 'dublin_creek_at_interstate_680',
            station_name = 'Dublin Creek at Interstate 680'
        WHERE station_id LIKE 'dublin_creek_at_interstate_680%'
    """)
    conn.commit()

    # 2. Redundant-file dedup. T-SQL has no implicit rowid like SQLite, so this
    #    uses ROW_NUMBER() OVER a partition to find and delete the duplicates.
    cur.execute("SELECT COUNT(*) FROM raw_readings")
    before = cur.fetchone()[0]

    cur.execute("""
        ;WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY station_id, timestamp ORDER BY (SELECT NULL)
            ) AS rn
            FROM raw_readings
        )
        DELETE FROM ranked WHERE rn > 1
    """)
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM raw_readings")
    after = cur.fetchone()[0]
    print(f"\nDeduplicated redundant station+timestamp rows: {before - after} removed")

    conn.close()
    print("Done. Loaded into Azure SQL Database:", AZURE_DATABASE)


if __name__ == "__main__":
    main()
