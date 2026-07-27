-- Migration: voyage data (ShipStaticData / AIS type 5)
-- The init/ directory only runs on an EMPTY volume, so apply this one
-- manually on the running DB (see README / chat instructions):
--   docker exec -i ais-db psql -U ais -d ais < /path/to/02_voyage.sql
-- (or paste the statements into a psql session)

-- Change-log: one row each time callsign/destination/eta/draught changes
CREATE TABLE IF NOT EXISTS voyage (
    ts          TIMESTAMPTZ NOT NULL,
    mmsi        BIGINT NOT NULL,
    callsign    TEXT,
    destination TEXT,
    eta         TEXT,              -- AIS ETA has no year: stored as 'MM-DD HH:MM'
    draught     REAL,              -- metres, MaximumStaticDraught
    ship_name   TEXT,
    source      TEXT NOT NULL DEFAULT 'aisstream'
);
CREATE INDEX IF NOT EXISTS idx_voyage_mmsi_ts ON voyage (mmsi, ts DESC);

-- Current values on latest for the map popup
ALTER TABLE latest ADD COLUMN IF NOT EXISTS callsign    TEXT;
ALTER TABLE latest ADD COLUMN IF NOT EXISTS destination TEXT;
ALTER TABLE latest ADD COLUMN IF NOT EXISTS eta         TEXT;
ALTER TABLE latest ADD COLUMN IF NOT EXISTS draught     REAL;
