-- Migration: vessel dimensions on `latest` (AIS Dimension A+B / C+D),
-- used to scale the ship icons on the Tracker maps.
-- Apply manually: docker exec -it ais-db psql -U ais -d ais
ALTER TABLE latest ADD COLUMN IF NOT EXISTS length_m REAL;
ALTER TABLE latest ADD COLUMN IF NOT EXISTS beam_m REAL;
