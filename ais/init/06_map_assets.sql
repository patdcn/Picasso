-- Migration: subsea/offshore asset store for the Tracker map overlays and
-- the Subsea Assets management page.
-- Apply manually: docker exec -it ais-db psql -U ais -d ais
CREATE TABLE IF NOT EXISTS map_asset (
    id          BIGSERIAL PRIMARY KEY,
    category    TEXT NOT NULL,       -- platform|well|power_cable|telecom_cable|pipeline|windfarm|eez|field
    name        TEXT NOT NULL,
    operator    TEXT,
    region      TEXT,                -- AG, WAF, MED, Europe, ...
    geom_type   TEXT NOT NULL,       -- Point|LineString|MultiLineString|Polygon|MultiPolygon
    geometry    JSONB NOT NULL,      -- GeoJSON geometry object
    properties  JSONB NOT NULL DEFAULT '{}'::jsonb,
    source      TEXT NOT NULL DEFAULT 'manual',
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS map_asset_cat_idx ON map_asset (category, active);
CREATE INDEX IF NOT EXISTS map_asset_src_idx ON map_asset (source);
