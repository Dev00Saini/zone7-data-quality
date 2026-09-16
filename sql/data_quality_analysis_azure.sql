-- ============================================================
-- Zone 7 Data Quality Analysis — Azure SQL (T-SQL) version
-- Question: Which stations have the most data quality issues,
-- and what's a reliable way to detect and handle gaps?
--
-- See docs/azure_migration_plan.md for the full migration writeup.
-- The one dialect change that matters here: SQLite's JULIANDAY() has
-- no T-SQL equivalent, so gap detection uses DATEDIFF(minute, ...)
-- instead. DATEDIFF returns a clean integer number of minutes with no
-- floating-point rounding, which is why this version can go back to a
-- clean ">15" threshold instead of the ">20" workaround the SQLite
-- version needed to dodge ~380,000 floating-point-noise false gaps.
--
-- Schema (from scripts/load_csvs_azure.py): raw_readings has
-- station_id, station_name, station_type, has_rain_gauge, timestamp,
-- source_file, loaded_at, plus dynamically-added metric columns such as
-- stage_ft, flow_cfs, precipitation_in, h2o_temperature_c, quality.
-- timestamp is stored as NVARCHAR — DATEDIFF below relies on SQL Server
-- implicitly converting it to a datetime, which works for unambiguous
-- ISO-style ("YYYY-MM-DD HH:MM:SS") strings. If any query below throws
-- a conversion error, the fix is to inspect a sample timestamp value's
-- exact format and wrap the column in an explicit CONVERT(...).
-- ============================================================


-- 0. KNOWN STATION IDENTITY ISSUE
-- T-SQL note: unlike SQLite, T-SQL enforces the ANSI SQL standard strictly
-- here -- every non-aggregated selected column must appear in GROUP BY.
-- SQLite is lenient about this (it silently picks an arbitrary matching
-- row for a selected-but-ungrouped column), which is what the original
-- query relied on. station_name is functionally dependent on station_id
-- (one name per id), so adding it to GROUP BY is safe and correct.
SELECT station_id, station_name, station_type, COUNT(*) AS n
FROM raw_readings
GROUP BY station_id, station_name, station_type
ORDER BY station_name;


-- 1. DEDUPLICATION CHECK (exact timestamp duplicates within a station)
SELECT station_id, timestamp, COUNT(*) AS n
FROM raw_readings
GROUP BY station_id, timestamp
HAVING COUNT(*) > 1;


-- 2. EXPECTED VS. ACTUAL READING COUNTS PER STATION
-- At a 15-minute cadence, a full day should have 96 readings.
WITH bounds AS (
    SELECT
        station_id,
        station_name,
        MIN(timestamp) AS first_reading,
        MAX(timestamp) AS last_reading,
        COUNT(*) AS actual_readings
    FROM raw_readings
    GROUP BY station_id, station_name
)
SELECT
    station_id,
    station_name,
    first_reading,
    last_reading,
    actual_readings,
    DATEDIFF(minute, first_reading, last_reading) / 15 AS expected_readings,
    ROUND(
        100.0 * actual_readings /
        NULLIF(DATEDIFF(minute, first_reading, last_reading) / 15, 0),
        1
    ) AS pct_complete
FROM bounds
ORDER BY pct_complete ASC;


-- 3. GAP DETECTION (window functions)
-- Every individual gap where consecutive readings are more than one
-- expected interval (15 min) apart.
--
-- NOTE: unlike the SQLite version, no floating-point workaround needed
-- here — DATEDIFF(minute, ...) returns a clean integer, so a normal
-- back-to-back 15-minute reading is exactly 15, never 15.00003. That
-- means the >20 threshold the SQLite version needed is unnecessary;
-- this uses a clean >15.
WITH ordered AS (
    SELECT
        station_id,
        station_name,
        timestamp,
        LAG(timestamp) OVER (PARTITION BY station_id ORDER BY timestamp) AS prev_timestamp
    FROM raw_readings
),
gaps AS (
    SELECT
        station_id,
        station_name,
        prev_timestamp AS gap_start,
        timestamp AS gap_end,
        DATEDIFF(minute, prev_timestamp, timestamp) AS gap_minutes
    FROM ordered
    WHERE prev_timestamp IS NOT NULL
      AND DATEDIFF(minute, prev_timestamp, timestamp) > 15
)
SELECT *
FROM gaps
ORDER BY gap_minutes DESC;


-- 4. GAP SUMMARY BY STATION (the core "which stations are worst" answer)
WITH ordered AS (
    SELECT
        station_id,
        station_name,
        timestamp,
        LAG(timestamp) OVER (PARTITION BY station_id ORDER BY timestamp) AS prev_timestamp
    FROM raw_readings
),
gaps AS (
    SELECT
        station_id,
        station_name,
        DATEDIFF(minute, prev_timestamp, timestamp) AS gap_minutes
    FROM ordered
    WHERE prev_timestamp IS NOT NULL
      AND DATEDIFF(minute, prev_timestamp, timestamp) > 15
)
SELECT
    station_id,
    station_name,
    COUNT(*) AS num_gaps,
    SUM(gap_minutes) AS total_missing_minutes,
    ROUND(SUM(gap_minutes) / 60.0, 1) AS total_missing_hours,
    MAX(gap_minutes) AS longest_gap_minutes
FROM gaps
GROUP BY station_id, station_name
ORDER BY total_missing_minutes DESC;


-- 5. METRIC-LEVEL NULLS (within rows that DO exist)
-- Distinct from timestamp gaps: a station can report on schedule but
-- have a specific broken sensor (e.g. Stage always blank).
SELECT
    station_id,
    station_name,
    COUNT(*) AS total_rows,
    SUM(CASE WHEN [stage_ft] IS NULL OR [stage_ft] = '' THEN 1 ELSE 0 END) AS blank_stage,
    SUM(CASE WHEN [flow_cfs] IS NULL OR [flow_cfs] = '' THEN 1 ELSE 0 END) AS blank_flow,
    SUM(CASE WHEN [precipitation_in] IS NULL OR [precipitation_in] = '' THEN 1 ELSE 0 END) AS blank_precip,
    SUM(CASE WHEN [h2o_temperature_c] IS NULL OR [h2o_temperature_c] = '' THEN 1 ELSE 0 END) AS blank_temp
FROM raw_readings
GROUP BY station_id, station_name
ORDER BY station_name;


-- 6. RECOMMENDED GAP-HANDLING STRATEGY (reference, not a query)
-- Documented in docs/data_quality_findings.md:
--   - Short gaps (<= 2 hrs): linear interpolation is defensible —
--     streamflow/rainfall change gradually at this timescale.
--   - Medium gaps (up to a day): flag and exclude from daily
--     aggregates rather than interpolate — avoids false precision.
--   - Long gaps / sensor outages: exclude affected day(s) from that
--     station's rollups, and log it rather than silently drop it.
--   - Metric-level nulls (e.g. a sensor that's always blank): this is
--     a different failure mode than a timing gap — it means the sensor
--     itself isn't installed/working, not that data was lost in transit.
--     Flag these stations separately; interpolation doesn't apply.
