"""
Zone 7 StreamTracker — Data Ingestion
======================================
Pulls raw 15-minute sensor data (streamflow + rainfall) from the Zone 7
Water Agency StreamTracker API and lands it UNTOUCHED into SQLite.

IMPORTANT: The exact API endpoint, query parameters, and station-list
endpoint are NOT fully documented in what's publicly fetchable — before
running this, open https://streamtracker.zone7waterca.gov/api/api.html
in a browser and check your browser's Network tab while using the
download form on https://streamtracker.zone7waterca.gov/api/download.html
to confirm the real request URL/params. Update `BASE_URL`, `STATIONS`,
and `fetch_station_data()` below to match what you find.

Design principle: this script does NOT clean anything. It just lands
raw data as-is, plus an ingestion log, so every downstream cleaning
decision in SQL is auditable against the original source.
"""

import sqlite3
import requests
import time
from datetime import datetime

DB_PATH = "../data/processed/zone7.db"

# TODO: confirm against the real API docs
BASE_URL = "https://streamtracker.zone7waterca.gov/api"

# TODO: replace with real station IDs pulled from the site's station list
STATIONS = {
    # "station_id": ("display_name", "type")  type = "stream" or "rain"
}

START_DATE = "2023-10-01"  # start of WY2023, first available data
END_DATE = "2024-09-30"    # one full water year


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_readings (
            station_id TEXT,
            station_name TEXT,
            station_type TEXT,
            timestamp TEXT,
            value REAL,
            raw_payload TEXT,
            ingested_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingestion_log (
            station_id TEXT,
            request_url TEXT,
            status_code INTEGER,
            rows_returned INTEGER,
            error TEXT,
            run_at TEXT
        )
    """)
    conn.commit()


def fetch_station_data(session, station_id, start, end):
    """Fetch raw data for one station. UPDATE this once you've confirmed
    the real endpoint shape from the browser Network tab."""
    params = {
        "station": station_id,
        "start": start,
        "end": end,
        "format": "json",
    }
    url = f"{BASE_URL}/data"  # placeholder path — confirm real path
    resp = session.get(url, params=params, timeout=30)
    return resp, url


def ingest_station(conn, session, station_id, meta):
    name, station_type = meta
    resp, url = fetch_station_data(session, station_id, START_DATE, END_DATE)
    now = datetime.utcnow().isoformat()

    rows_returned = 0
    error = None
    try:
        resp.raise_for_status()
        payload = resp.json()
        readings = payload if isinstance(payload, list) else payload.get("data", [])
        for r in readings:
            conn.execute(
                "INSERT INTO raw_readings VALUES (?, ?, ?, ?, ?, ?, ?)",
                (station_id, name, station_type, r.get("timestamp"), r.get("value"), str(r), now),
            )
        rows_returned = len(readings)
    except Exception as e:
        error = str(e)

    conn.execute(
        "INSERT INTO ingestion_log VALUES (?, ?, ?, ?, ?, ?)",
        (station_id, url, resp.status_code if resp is not None else None, rows_returned, error, now),
    )
    conn.commit()
    print(f"[{station_id}] {name}: {rows_returned} rows, error={error}")


def main():
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    session = requests.Session()

    if not STATIONS:
        print("STATIONS dict is empty — populate it with real station IDs "
              "from the site before running. See module docstring.")
        return

    for station_id, meta in STATIONS.items():
        ingest_station(conn, session, station_id, meta)
        time.sleep(1)  # be polite to a public agency's server

    conn.close()


if __name__ == "__main__":
    main()
