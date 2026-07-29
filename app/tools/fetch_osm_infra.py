"""
Fetch charted submarine pipelines and cables for a region from
OpenStreetMap (Overpass) and import them into the map_asset table.

Run inside the PORTAL container:   cd /code && python -m app.tools.fetch_osm_infra
Re-running replaces the 'osm_overpass' source rows; manual assets are
never touched. Default bbox is the Arabian Gulf; override for other
regions, e.g.:

    OSM_BBOX="3.5,-1.5,62,9" OSM_REGION="Europe" cd /code && python -m app.tools.fetch_osm_infra

Data is chart-level (ODbL) - never a substitute for the project survey.
"""
import os
import sys

import requests

# repo-root (bevat het "app"-package) afleiden uit de eigen locatie,
# zodat dit script werkt ongeacht WORKDIR of image-layout
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from app.engines import asset_db  # noqa: E402

BBOX = tuple(float(x) for x in os.environ.get(
    "OSM_BBOX", "23.5,46.5,30.7,57.5").split(","))   # south,west,north,east
REGION = os.environ.get("OSM_REGION", "AG")
OVERPASS = os.environ.get("OVERPASS_URL",
                          "https://overpass-api.de/api/interpreter")

QUERY = f"""
[out:json][timeout:240];
(
  way["seamark:type"="cable_submarine"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["seamark:type"="pipeline_submarine"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["man_made"="pipeline"]["location"~"underwater|seabed|sea"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["communication"~"line|cable"]["location"~"underwater|seabed|sea"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  node["seamark:type"~"platform|production_area"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["seamark:type"~"platform|production_area"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  node["man_made"="offshore_platform"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["man_made"="offshore_platform"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);
out geom tags;
"""

def classify(tags):
    st = tags.get("seamark:type", "")
    if "platform" in st or "production_area" in st \
            or tags.get("man_made") == "offshore_platform":
        return "platform"
    if "pipeline" in st or tags.get("man_made") == "pipeline":
        return "pipeline"
    if tags.get("power") or "power" in (tags.get("cable", "") or ""):
        return "power_cable"
    return "telecom_cable"


def platform_point(el):
    """Point for a platform element: node lat/lon, or the centroid of a
    way footprint."""
    if el.get("type") == "node":
        if el.get("lat") is None:
            return None
        return [el["lon"], el["lat"]]
    geom = el.get("geometry") or []
    if not geom:
        return None
    return [sum(p["lon"] for p in geom) / len(geom),
            sum(p["lat"] for p in geom) / len(geom)]

def main():
    print(f"querying Overpass, bbox={BBOX}, region tag={REGION!r} ...")
    r = requests.post(OVERPASS, data={"data": QUERY}, timeout=300,
                      headers={"User-Agent": "DCN-Picasso-portal/1.0"})
    r.raise_for_status()
    rows = []
    for el in r.json().get("elements", []):
        tags = el.get("tags", {})
        cat = classify(tags)
        name = (tags.get("seamark:name") or tags.get("name")
                or f"unnamed {cat.replace('_', ' ')}")
        operator = tags.get("operator") or tags.get("owner") or None
        props = {"osm_id": el.get("id"),
                 "substance": tags.get("substance", ""),
                 "source_note": "OSM (ODbL), chart-level geometry"}
        if cat == "platform":
            pt = platform_point(el)
            if pt is None:
                continue
            rows.append((cat, name, operator, REGION, "Point",
                         {"type": "Point", "coordinates": pt}, props))
            continue
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        rows.append((cat, name, operator, REGION, "LineString",
                     {"type": "LineString",
                      "coordinates": [[p["lon"], p["lat"]] for p in geom]},
                     props))
    if not rows:
        sys.exit("no features returned - existing data left untouched")
    n = asset_db.replace_source("osm_overpass", rows)
    kinds = {}
    for row in rows:
        kinds[row[0]] = kinds.get(row[0], 0) + 1
    print(f"imported {n} routes ({kinds}) as source=osm_overpass")
    print("The Tracker maps pick this up on the next overlay render.")

if __name__ == "__main__":
    main()
