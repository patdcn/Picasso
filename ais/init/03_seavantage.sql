-- Migration: SeaVantage shipId mapping (second AIS source, satellite-backed)
-- Apply manually on the running DB (init/ only runs on an empty volume):
--   docker exec -it ais-db psql -U ais -d ais
--   then paste these statements.

CREATE TABLE IF NOT EXISTS sv_ship (
    imo         BIGINT PRIMARY KEY,          -- our fleet key
    mmsi        BIGINT,
    ship_id     TEXT NOT NULL,               -- SeaVantage UUID
    ship_name   TEXT,
    matched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
