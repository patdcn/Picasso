-- Migration 09: vessel capability specs on `fleet`
-- (deck space/strength, POB, cranes, SAT system, bell config, ROV hangar)
--
-- Apply manually via Dokploy Open Terminal on the ais-db container:
--   docker exec -it <ais-db> psql -U ais -d ais < ais/init/09_fleet_specs.sql
--
-- Then import the data (see bottom of this file).

ALTER TABLE fleet ADD COLUMN IF NOT EXISTS deck_space_m2      REAL;
ALTER TABLE fleet ADD COLUMN IF NOT EXISTS deck_strength_t_m2 REAL;
ALTER TABLE fleet ADD COLUMN IF NOT EXISTS pob                INTEGER;
ALTER TABLE fleet ADD COLUMN IF NOT EXISTS crane1_swl_t       REAL;
ALTER TABLE fleet ADD COLUMN IF NOT EXISTS crane2_swl_t       REAL;
ALTER TABLE fleet ADD COLUMN IF NOT EXISTS sat_type           TEXT
    CHECK (sat_type IS NULL OR sat_type IN ('integrated','deck','none'));
ALTER TABLE fleet ADD COLUMN IF NOT EXISTS sat_divers         INTEGER;
ALTER TABLE fleet ADD COLUMN IF NOT EXISTS bell_config        TEXT
    CHECK (bell_config IS NULL OR bell_config IN ('single','twin','none'));
ALTER TABLE fleet ADD COLUMN IF NOT EXISTS rov_hangar         INTEGER
    CHECK (rov_hangar IS NULL OR rov_hangar BETWEEN 0 AND 2);
ALTER TABLE fleet ADD COLUMN IF NOT EXISTS spec_confidence    TEXT
    CHECK (spec_confidence IS NULL OR spec_confidence IN ('high','medium','low'));
ALTER TABLE fleet ADD COLUMN IF NOT EXISTS spec_source        TEXT;

-- ---------------------------------------------------------------------------
-- IMPORT (run inside a psql session on ais-db, with fleet_specs.csv copied
-- to the container, e.g. docker cp fleet_specs.csv <ais-db>:/tmp/):
--
--   CREATE TEMP TABLE fleet_specs_stg (
--     imo TEXT, name TEXT, built_year TEXT, deck_space_m2 REAL, deck_strength_t_m2 REAL,
--     pob INTEGER, crane1_swl_t REAL, crane2_swl_t REAL, sat_type TEXT,
--     sat_divers INTEGER, bell_config TEXT, rov_hangar INTEGER,
--     confidence TEXT, source_note TEXT);
--
--   \copy fleet_specs_stg FROM '/tmp/fleet_specs.csv' WITH (FORMAT csv, HEADER true, NULL '')
--
--   UPDATE fleet f SET
--     built              = CASE WHEN f.built IS NULL OR f.built = ''
--                               THEN NULLIF(s.built_year, '') ELSE f.built END,
--     deck_space_m2      = s.deck_space_m2,
--     deck_strength_t_m2 = s.deck_strength_t_m2,
--     pob                = s.pob,
--     crane1_swl_t       = s.crane1_swl_t,
--     crane2_swl_t       = s.crane2_swl_t,
--     sat_type           = NULLIF(s.sat_type, ''),
--     sat_divers         = s.sat_divers,
--     bell_config        = NULLIF(s.bell_config, ''),
--     rov_hangar         = s.rov_hangar,
--     spec_confidence    = NULLIF(s.confidence, ''),
--     spec_source        = NULLIF(s.source_note, '')
--   FROM fleet_specs_stg s
--   WHERE f.imo::text = s.imo;
--
--   -- expect 133 (or however many IMOs match):
--   SELECT count(*) FROM fleet f JOIN fleet_specs_stg s ON f.imo::text = s.imo;
-- ---------------------------------------------------------------------------
