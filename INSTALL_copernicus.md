# Weather Stats — "Copernicus" page · install into picasso

Purely additive except requirements.txt. Nothing existing is overwritten besides
requirements.txt (3 lines added).

## 1. Merge files into the repo
Extract and merge the `app/` folder into your picasso repo `app/` (Windows will
ask to merge — yes). It only ADDS:
  app/engines/metocean/     (the engine: fetch, climatology, workability, cache)
  app/pages/copernicus.py   (the page — self-registers in the menu)
Then replace `requirements.txt` at the repo root with the one in this zip
(adds: pandas, dash-leaflet, copernicusmarine).

## 2. Menu
No nav.py edit needed. The page registers with category="Weather Stats",
name="Copernicus", so a new "Weather Stats" group with a "Copernicus" link
appears automatically. As an admin you see it immediately; grant the module
path `/weather/copernicus` to other users via Admin → Users as usual.

## 3. Credentials (Dokploy environment)
Add these to the picasso service environment so live reanalysis works:
  CMEMS_USERNAME = p.feeleus@dcndiving.com
  CMEMS_PASSWORD = <your Copernicus password>
Until set, the page runs on synthetic DEMO data (amber banner). Never commit the
password — it lives only in the Dokploy environment.

## 4. Cache (optional but recommended)
The reanalysis is cached to /data/metocean_cache (your existing data volume) so
the first assessment per location is slow (~minutes) and the rest instant.
Override with METOCEAN_CACHE if you prefer another path.

## 5. Push
Commit via GitHub Desktop and push; Dokploy autodeploys. First build is longer
(copernicusmarine pulls xarray/zarr/etc).

## Verified
Built and run-tested on your pinned stack: Dash 2.18.2, plotly 5.24.1,
numpy 2.1.3. No scipy / no pyarrow (trend p-value is numpy-only, validated
against scipy to 1e-13; cache uses pickle). Page registers, both modes assess
and render, charts build.

## Caveat
Currents use daily-mean reanalysis (GLORYS) which doesn't resolve the tidal
cycle; the page auto-selects the tide-resolving IBI product for North Sea sites,
but confirm slack against tide tables. CMEMS variable short-names are centralised
in app/engines/metocean/products.py — confirm on first live run.
