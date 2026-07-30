-- Migration: promote country + UN/LOCODE from properties (JSONB) to real
-- columns on map_asset, with backfill. LOCODE becomes a match key for the
-- upcoming geofencing feature (arrival detection vs AIS destination).
-- Apply manually: docker exec -it ais-db psql -U ais -d ais
ALTER TABLE map_asset ADD COLUMN IF NOT EXISTS country TEXT;
ALTER TABLE map_asset ADD COLUMN IF NOT EXISTS un_locode TEXT;

-- backfill: explicit country first, else the AG bundle's jurisdiction
UPDATE map_asset
   SET country = COALESCE(properties->>'country', properties->>'jurisdiction')
 WHERE country IS NULL
   AND (properties ? 'country' OR properties ? 'jurisdiction');

UPDATE map_asset
   SET un_locode = upper(properties->>'un_locode')
 WHERE un_locode IS NULL AND properties ? 'un_locode';

-- lifted keys leave properties (jurisdiction stays: source data)
UPDATE map_asset
   SET properties = properties - 'country' - 'un_locode'
 WHERE properties ?| array['country','un_locode'];

CREATE INDEX IF NOT EXISTS map_asset_locode_idx
    ON map_asset (un_locode) WHERE un_locode IS NOT NULL;
