-- Migration: vessel grouping (DSV / PLB / OSV / ...) for the Fleet page.
-- Apply manually: docker exec -it ais-db psql -U ais -d ais
ALTER TABLE fleet ADD COLUMN IF NOT EXISTS vessel_type TEXT;
UPDATE fleet SET vessel_type = 'DSV' WHERE vessel_type IS NULL;
