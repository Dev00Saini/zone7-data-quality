-- ============================================================
-- Zone 7 Data Quality Analysis (v2 — matches real wide schema)
-- Question: Which stations have the most data quality issues,
-- and what's a reliable way to detect and handle gaps?
--
-- Schema (from scripts/load_csvs.py): raw_readings has station_id,
-- station_name, station_type, has_rain_gauge, timestamp, source_file,
-- loaded_at, plus dynamically-added metric columns such as
-- stage_ft, flow_cfs, precipitation_in, h2o_temperature_c, quality.
-- Not every station has every metric column populated (NULL/empty
-- string where a sensor isn't present for that station).
-- ============================================================


-- 0. KNOWN STATION IDENTITY ISSUE
-- Dublin Creek at Interstate 680 was exported under two different
-- filenames/station_ids that are almost certainly the same physical
-- station (identical row counts). Decide whether to merge these
-- before running station-level rankings, or the split will distort
-- the results.
SELECT station_id, station_name, station_type, COUNT(*) AS n
FROM raw_readings
GROUP BY station_id, station_type
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
    CAST((JULIANDAY(last_reading) - JULIANDAY(first_reading)) * 96 AS INTEGER) AS expected_readings,
    ROUND(
        100.0 * actual_readings /
        NULLIF(CAST((JULIANDAY(last_reading) - JULIANDAY(first_reading)) * 96 AS INTEGER), 0),
        1
    ) AS pct_complete
FROM bounds
ORDER BY pct_complete ASC;


-- 3. GAP DETECTION (window functions)
-- Every individual gap where consecutive readings are more than one
-- expected interval (15 min) apart.
--
-- IMPORTANT: use a >20 (not >15) minute threshold here. JULIANDAY date
-- arithmetic introduces tiny floating-point error, so a normal back-to-back
-- 15-minute reading can compute as 15.00003 minutes — which is ">15" but
-- is NOT a real gap. Filtering at >15 produced ~380K false "gaps" that were
-- actually just floating-point noise around the expected cadence; >20
-- comfortably clears that noise while still catching every real missed
-- reading (real gaps cluster at 30, 45, 60+ minutes — see bucket query below).
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
        ROUND((JULIANDAY(timestamp) - JULIANDAY(prev_timestamp)) * 24 * 60, 1) AS gap_minutes
    FROM ordered
    WHERE prev_timestamp IS NOT NULL
      AND (JULIANDAY(timestamp) - JULIANDAY(prev_timestamp)) * 24 * 60 > 20
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
        ROUND((JULIANDAY(timestamp) - JULIANDAY(prev_timestamp)) * 24 * 60, 1) AS gap_minutes
    FROM ordered
    WHERE prev_timestamp IS NOT NULL
      AND (JULIANDAY(timestamp) - JULIANDAY(prev_timestamp)) * 24 * 60 > 20
)
SELECT
    station_id,
    station_name,
    COUNT(*) AS num_gaps,
    ROUND(SUM(gap_minutes), 0) AS total_missing_minutes,
    ROUND(SUM(gap_minutes) / 60.0, 1) AS total_missing_hours,
    ROUND(MAX(gap_minutes), 0) AS longest_gap_minutes
FROM gaps
GROUP BY station_id, station_name
ORDER BY total_missing_minutes DESC;


-- 5. METRIC-LEVEL NULLS (within rows that DO exist)
-- Distinct from timestamp gaps: a station can report on schedule but
-- have a specific broken sensor (e.g. Stage always blank). Check
-- PRAGMA table_info(raw_readings) if these column names don't match
-- what actually got created in your DB.
SELECT
    station_id,
    station_name,
    COUNT(*) AS total_rows,
    SUM(CASE WHEN stage_ft IS NULL OR stage_ft = '' THEN 1 ELSE 0 END) AS blank_stage,
    SUM(CASE WHEN flow_cfs IS NULL OR flow_cfs = '' THEN 1 ELSE 0 END) AS blank_flow,
    SUM(CASE WHEN precipitation_in IS NULL OR precipitation_in = '' THEN 1 ELSE 0 END) AS blank_precip,
    SUM(CASE WHEN h2o_temperature_c IS NULL OR h2o_temperature_c = '' THEN 1 ELSE 0 END) AS blank_temp
FROM raw_readings
GROUP BY station_id, station_name
ORDER BY station_name;


-- 6. RECOMMENDED GAP-HANDLING STRATEGY (reference, not a query)
-- Documented in docs/data_quality_findings.md:
--   - Short gaps (<= 30 min): linear interpolation is defensible —
--     streamflow/rainfall change gradually at this timescale.
--   - Medium gaps (up to a few hours): flag and exclude from daily
--     aggregates rather than interpolate — avoids false precision.
--   - Long gaps / sensor outages: exclude affected day(s) from that
--     station's rollups, and log it rather than silently drop it.
--   - Metric-level nulls (e.g. a sensor that's always blank): this is
--     a different failure mode than a timing gap — it means the sensor
--     itself isn't installed/working, not that data was lost in transit.
--     Flag these stations separately; interpolation doesn't apply.
