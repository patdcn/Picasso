# Weather Stats — "Copernicus" page · install into picasso

## Files in this zip (merge into the repo root, preserving paths)
  app/engines/metocean/      NEW — engine (fetch, climatology, workability, cache)
  app/pages/copernicus.py    NEW — the page (self-registers in the menu)
  requirements.txt           REPLACES root file (adds pandas, dash-leaflet, copernicusmarine)
  docker-compose.yml         REPLACES root file (adds CMEMS_* + METOCEAN_CACHE passthrough)

Only requirements.txt and docker-compose.yml overwrite existing files; both diffs
are small and reviewable in GitHub Desktop. Everything under app/ is additive.

## 1. Merge
Extract into the picasso repo root so paths merge. Windows will ask to merge the
`app` folder — yes. Let requirements.txt and docker-compose.yml replace the root
copies.

## 2. Menu — nothing to do
The page registers with category="Weather Stats", name="Copernicus", so a new
"Weather Stats" group with a "Copernicus" link appears automatically. Admins see
it at once; grant module path `/weather/copernicus` to other users via Admin → Users.

## 3. Credentials (Dokploy → Environment page)
Add these two, formatted EXACTLY like your other vars — no spaces around `=`,
no quotes:
    CMEMS_USERNAME=p.feeleus@dcndiving.com
    CMEMS_PASSWORD=<your Copernicus password>
The updated docker-compose.yml forwards them into the container (this was the
missing piece). Until they resolve, the page shows synthetic DEMO data (amber
banner); once live it turns green.

## 4. Push
Commit via GitHub Desktop and push; Dokploy autodeploys. First build is longer
(copernicusmarine pulls xarray/zarr/etc). To verify the passthrough, open the
Dokploy container terminal and run:  echo "$CMEMS_USERNAME"  — it should print
your email with no leading space.

## Cache
Reanalysis is cached to /data/metocean_cache on the existing picasso_data volume,
so the first assessment per location is slow (~minutes) and the rest instant, and
the cache survives redeploys.

## Verified
Built and run-tested on your pinned stack (Dash 2.18.2, plotly 5.24.1,
numpy 2.1.3). No scipy / no pyarrow (trend p-value numpy-only, validated vs scipy
to 1e-13; cache uses pickle). Page registers, both modes assess and render, charts
build, compose YAML parses.

## Caveat
Currents use daily-mean reanalysis (GLORYS) which doesn't resolve the tidal cycle;
the page auto-selects the tide-resolving IBI product for North Sea sites, but
confirm slack against tide tables. CMEMS variable short-names are centralised in
app/engines/metocean/products.py — confirm on first live run.

---

## ERA5 second-source comparison (optional)

The page can overlay ERA5 (ECMWF) waves & wind as an independent cross-check via
the "Compare Hs & wind vs ERA5" checkbox. ERA5 is on the Copernicus CLIMATE Data
Store (CDS) — a different service from the Marine store — so it needs its own
credential:

1. Register / sign in at https://cds.climate.copernicus.eu (your ECMWF login
   works via SSO).
2. Profile page → copy your **Personal Access Token** (this is the key, NOT your
   password).
3. Accept the licence on the ERA5 dataset page once, or downloads fail.
4. In the Dokploy Environment page add (no spaces around =):
       CDS_KEY=<your personal access token>
   (CDS_URL defaults to the right endpoint; only set it to override.)

Notes:
- The CDS API is a queued batch system, so the FIRST ERA5 pull per location is
  slow (minutes). It's cached to /data afterwards, and it only runs when the
  checkbox is ticked — normal runs are unaffected.
- ERA5 provides waves & wind only (no currents); the overlay appears on the Hs
  and wind panels as a dashed line. If the token is missing or a pull fails, the
  CMEMS result is kept and a note explains why.
- New dependencies: cdsapi, netCDF4 (already in requirements.txt).
- The ERA5 fetch could not be tested against the live CDS from the build
  environment — treat the first ticked comparison as a shakedown.
