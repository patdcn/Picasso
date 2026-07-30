"""
Fetch boundary polygons for a curated list of ports of interest (OSM via
Nominatim) and import them into the map_asset store (category 'port').

Run inside the PORTAL container:

    cd /code && python -m app.tools.fetch_ports

MAINTENANCE: edit the PORTS list below - one line per port. Re-running
replaces the 'osm_ports' source rows; ports added manually through the
Subsea Assets page are never touched. Ports that Nominatim cannot resolve
to a polygon are reported at the end - add those by hand (Subsea Assets
-> Add asset, category Ports, paste the shape).

Respects the Nominatim usage policy: identifying User-Agent and >= 1.5 s
between requests. Boundaries are OSM (ODbL), chart-level - harbour-master
charts remain authoritative.
"""
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from app.engines import asset_db  # noqa: E402

# ---- EDIT HERE: ports of interest ------------------------------------------
# (query, vrije naam, region, land, UN/LOCODE, officiele/WPI-naam)
# LOCODE/WPI-naam leeg laten waar onbekend; aanvullen kan altijd via de
# Subsea Assets-pagina (velden Country en Code) of hier + rerun.
PORTS = [
    ("Port of Amsterdam, Netherlands",      "Amsterdam / IJmuiden", "Europe", "Netherlands", "NLAMS", "Amsterdam"),
    ("Port of Rotterdam, Netherlands",      "Rotterdam",            "Europe", "Netherlands", "NLRTM", "Rotterdam"),
    ("Port of Den Helder, Netherlands",     "Den Helder",           "Europe", "Netherlands", "NLDHR", "Den Helder"),
    ("Port of Aberdeen, Scotland",          "Aberdeen",             "Europe", "United Kingdom", "GBABD", "Aberdeen"),
    ("Peterhead Port, Scotland",            "Peterhead",            "Europe", "United Kingdom", "GBPHD", "Peterhead"),
    ("Grand Harbour, Valletta, Malta",      "Valletta Grand Harbour", "Europe", "Malta", "MTMLA", "Valletta"),
    ("Jubail Commercial Port, Saudi Arabia", "Jubail",              "AG", "Saudi Arabia", "SAJUB", "Jubail"),
    ("King Abdulaziz Port Dammam, Saudi Arabia", "Dammam (King Abdulaziz)", "AG", "Saudi Arabia", "SADMM", "Ad Dammam"),
    ("Jebel Ali Port, Dubai",               "Jebel Ali",            "AG", "UAE", "AEJEA", "Jebel Ali"),
    ("Port Rashid, Dubai",                  "Port Rashid (Dubai)",  "AG", "UAE", "AEDXB", "Dubai"),
    ("Hamriyah Port, Sharjah",              "Hamriyah (Sharjah)",   "AG", "UAE", "", ""),
    ("Port of Ras Laffan, Qatar",           "Ras Laffan",           "AG", "Qatar", "", "Ras Laffan"),
    ("Hamad Port, Qatar",                   "Hamad Port (Doha)",    "AG", "Qatar", "", ""),
    ("Khalifa Bin Salman Port, Bahrain",    "Khalifa Bin Salman",   "AG", "Bahrain", "", ""),
    ("Shuwaikh Port, Kuwait",               "Shuwaikh (Kuwait)",    "AG", "Kuwait", "KWSWK", "Shuwaikh"),
    ("Mina Zayed, Abu Dhabi",               "Mina Zayed (Abu Dhabi)", "AG", "UAE", "", "Zayed Port"),
]
# -----------------------------------------------------------------------------

NOMINATIM = os.environ.get("NOMINATIM_URL",
                           "https://nominatim.openstreetmap.org/search")
HEADERS = {"User-Agent": "DCN-Picasso-portal/1.0 (engineering@dcndiving)"}


def lookup(query):
    """Best polygon for a query, or None. Prefers results that actually
    carry a Polygon/MultiPolygon (not a point pin)."""
    r = requests.get(NOMINATIM, headers=HEADERS, timeout=60, params={
        "q": query, "format": "jsonv2", "limit": 5,
        "polygon_geojson": 1, "extratags": 0})
    r.raise_for_status()
    for hit in r.json():
        gj = hit.get("geojson") or {}
        if gj.get("type") in ("Polygon", "MultiPolygon"):
            return gj
    return None


def main():
    rows, missing = [], []
    for query, name, region, country, locode, wpi_name in PORTS:
        try:
            geom = lookup(query)
        except requests.RequestException as exc:
            print(f"  {name}: request failed ({exc}); skipping")
            missing.append(name)
            time.sleep(1.5)
            continue
        if geom is None:
            print(f"  {name}: no polygon found")
            missing.append(name)
        else:
            npts = sum(len(r0) for r0 in geom["coordinates"]) \
                if geom["type"] == "Polygon" else \
                sum(len(r0) for poly in geom["coordinates"] for r0 in poly)
            print(f"  {name}: {geom['type']} ({npts} pts)")
            props = {"query": query,
                     "source_note": "OSM boundary via Nominatim (ODbL)"}
            if country:
                props["country"] = country
            if locode:
                props["un_locode"] = locode
            if wpi_name:
                props["wpi_name"] = wpi_name
            rows.append(("port", name, None, region, geom["type"], geom,
                         props))
        time.sleep(1.5)                     # Nominatim usage policy

    if not rows:
        sys.exit("no ports resolved - existing data left untouched")
    n = asset_db.replace_source("osm_ports", rows)
    print(f"\nimported {n} port polygons (source=osm_ports)")
    if missing:
        print("not found - add manually via Subsea Assets:")
        for m in missing:
            print(f"  - {m}")


if __name__ == "__main__":
    main()
