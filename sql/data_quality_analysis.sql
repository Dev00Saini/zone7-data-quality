-- ============================================================
-- Zone 7 Data Quality Analysis
-- Question: Which stations have the most data quality issues,
-- and what's a reliable way to detect and handle gaps?
--
-- Assumes raw_readings(station_id, station_name, station_type,
-- timestamp, value, raw_payload, ingested_at) already populated
-- by scripts/ingest.py. Timestamps are ISO strings; expected
-- cadence is one reading every 15 minutes per station.
-- ============================================================


-- 1. DEDUPLICATION CHECK
-- Sensors can occasionally report the same timestamp twice (retries,
-- backfills). Find duplicates before anything else, since they'd
-- silently distort every downstream count.
SELECT station_id, timestamp, COUNT(*) AS n
FROM raw_readings
GROUP BY station_id, timestamp
HAVING COUNT(*) > 1;


-- 2. EXPECTED VS. ACTUAL READING COUNTS PER STATION
-- At a 15-minute cadence, a full day should have 96 readings.
-- Compare actual row counts against the theoretical maximum for
-- each station's active date range.
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
    -- expected readings = span in days * 96 (15-min intervals/day)
    CAST(
        (JULIANDAY(last_reading) - JULIANDAY(first_reading)) * 96
        AS INTEGER
    ) AS expected_readings,
    ROUND(
        100.0 * actual_readings /
        NULLIF(CAST((JULIANDAY(last_reading) - JULIANDAY(first_reading)) * 96 AS INTEGER), 0),
        1
    ) AS pct_complete
FROM bounds
ORDER BY pct_complete ASC;


-- 3. GAP DETECTION (window functions)
-- Find every individual gap: consecutive readings per station where
-- the time difference is more than one expected interval (15 min).
-- This is the core "reliable way to detect gaps" deliverable.
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
      AND (JULIANDAY(timestamp) - JULIANDAY(prev_timestamp)) * 24 * 60 > 15  -- more than one interval
)
SELECT *
FROM gaps
ORDER BY gap_minutes DESC;


-- 4. GAP SUMMARY BY STATION
-- Roll the individual gaps up into a per-station scorecard: total
-- gap count, total minutes of missing data, longest single outage.
-- This is the ranking that directly answers "which stations have
-- the most data quality issues."
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
      AND (JULIANDAY(timestamp) - JULIANDAY(prev_timestamp)) * 24 * 60 > 15
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


-- 5. OUT-OF-RANGE / SUSPICIOUS VALUES
-- Flag physically implausible readings (negative flow, extreme
-- outliers) as a second dimension of data quality beyond gaps.
-- Adjust thresholds per station_type once you've looked at the
-- real value distributions.
SELECT
    station_id,
    station_name,
    station_type,
    timestamp,
    value
FROM raw_readings
WHERE (station_type = 'stream' AND value < 0)
   OR (station_type = 'rain' AND value < 0)
ORDER BY station_id, timestamp;


-- 6. RECOMMENDED GAP-HANDLING STRATEGY (reference, not a query)
-- Documented in docs/data_quality_findings.md — summarize here for
-- convenience:
--   - Short gaps (<= 2 missed intervals, ~30 min): linear interpolation
--     is defensible for streamflow, which changes gradually.
--   - Medium gaps (up to a few hours): flag and exclude from
--     daily aggregates rather than interpolate — false precision risk.
--   - Long gaps / sensor outages (many hours+): exclude the affected
--     day(s) entirely from that station's rollups, and note it in the
--     data hygiene log rather than silently dropping it.
