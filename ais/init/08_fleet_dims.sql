-- Migration: vessel dimensions on `fleet`, auto-filled from AIS
-- (latest.length_m/beam_m) every time the Fleet page loads.
-- Apply manually: docker exec -it ais-db psql -U ais -d ais
ALTER TABLE fleet ADD COLUMN IF NOT EXISTS length_m REAL;
ALTER TABLE fleet ADD COLUMN IF NOT EXISTS beam_m REAL;
