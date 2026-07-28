-- Migration: SeaVantage registration tracking for the Fleet page.
-- Apply manually on the running DB (docker exec -it ais-db psql -U ais -d ais).
-- registered_at = when WE registered (or first saw) the vessel in the SVMP
-- workspace; drives the 7-day delete lock. match_result stores the last
-- /ship/match outcome for troubleshooting name mismatches.

ALTER TABLE sv_ship ADD COLUMN IF NOT EXISTS registered_at TIMESTAMPTZ;
ALTER TABLE sv_ship ADD COLUMN IF NOT EXISTS match_result TEXT;

-- Backfill: every existing sv_ship row was harvested from /fleet/snapshot,
-- i.e. the vessel IS registered; use first-seen as conservative clock start.
UPDATE sv_ship SET registered_at = matched_at WHERE registered_at IS NULL;
