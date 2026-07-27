-- DSV Picasso Engineering Portal - AIS Vessel Tracker
-- TimescaleDB schema. Runs once on first container start (empty volume)
-- via /docker-entrypoint-initdb.d. For an existing volume, apply manually:
--   docker exec -i <db-container> psql -U ais -d ais < init/01_schema.sql

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------------------
-- Fleet: which vessels we track. Keyed on IMO (stable across reflags).
-- MMSI is what AIS actually transmits and may change over a vessel's life.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fleet (
    imo         BIGINT PRIMARY KEY,
    mmsi        BIGINT UNIQUE,              -- NULL allowed (newbuilds, e.g. Jana 201)
    name        TEXT NOT NULL,
    owner       TEXT,
    operator    TEXT,
    built       TEXT,
    flag        TEXT,
    region      TEXT,
    tier        TEXT,
    notes       TEXT,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Positions: append-only downsampled track history (hypertable).
-- One row per stored point after the collector's downsample rules.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS positions (
    ts          TIMESTAMPTZ NOT NULL,
    mmsi        BIGINT NOT NULL,
    lat         DOUBLE PRECISION NOT NULL,
    lon         DOUBLE PRECISION NOT NULL,
    sog         REAL,                        -- knots, NULL = not available
    cog         REAL,                        -- degrees, NULL = not available
    heading     SMALLINT,                    -- degrees true, NULL = not available (AIS 511)
    nav_status  SMALLINT,                    -- raw AIS code: 0 underway, 1 anchor, 5 moored...
    source      TEXT NOT NULL DEFAULT 'aisstream'
);

SELECT create_hypertable('positions', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_positions_mmsi_ts ON positions (mmsi, ts DESC);

-- Prevent exact duplicates when combining sources later (stream + satellite poll)
CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_dedupe
    ON positions (mmsi, ts, source);

-- ---------------------------------------------------------------------------
-- Latest: one row per vessel, upserted on (throttled) message arrival.
-- The map's "where is everyone now" view never scans the hypertable.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS latest (
    mmsi        BIGINT PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL,
    lat         DOUBLE PRECISION NOT NULL,
    lon         DOUBLE PRECISION NOT NULL,
    sog         REAL,
    cog         REAL,
    heading     SMALLINT,
    nav_status  SMALLINT,
    ship_name   TEXT                         -- name as broadcast in AIS metadata
);

-- ---------------------------------------------------------------------------
-- Hourly continuous aggregate: free long-range views later (months of track
-- without touching raw rows). No retention policy on raw data: data is heilig.
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS positions_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', ts) AS bucket,
    mmsi,
    last(lat, ts)        AS lat,
    last(lon, ts)        AS lon,
    avg(sog)             AS sog_avg,
    last(nav_status, ts) AS nav_status,
    count(*)             AS n_points
FROM positions
GROUP BY bucket, mmsi
WITH NO DATA;

SELECT add_continuous_aggregate_policy('positions_hourly',
    start_offset      => INTERVAL '3 hours',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE);
