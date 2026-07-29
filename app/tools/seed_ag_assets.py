"""
One-time seed: Arabian Gulf public asset bundle (v0.1) -> map_asset table.

Run inside the PORTAL container:   python /app/app/tools/seed_ag_assets.py
Re-running replaces the 'ag_bundle_v0_1' source rows (manual assets are
never touched). After a confirmed seed the GeoJSON in app/data/ is
obsolete and may be deleted from the repo.
"""
import json
import os
import sys

sys.path.insert(0, "/app")
from app.engines import asset_db  # noqa: E402

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "Arabian_Gulf_Offshore_Assets_Public_v0_1.geojson")

CAT_MAP = {
    "Field / Discovery": "field",
    "Platform / Complex": "platform",
    "Telecom Cable Landing": "telecom_cable",
    "Power / Utility Cable": "power_cable",
    "LNG Terminal": "platform",
}

def main():
    feats = json.load(open(PATH, encoding="utf-8")).get("features", [])
    rows = []
    for f in feats:
        p = f.get("properties", {})
        geom = f.get("geometry") or {}
        cat = CAT_MAP.get(p.get("asset_category"))
        if not cat or geom.get("type") != "Point":
            continue
        props = {k: v for k, v in p.items() if v not in ("", None)}
        rows.append((cat, p.get("asset_name") or "Unknown",
                     p.get("operator_owner") or None, "AG",
                     "Point", geom, props))
    n = asset_db.replace_source("ag_bundle_v0_1", rows)
    print(f"seeded {n} assets from the AG bundle (source=ag_bundle_v0_1)")
    print("counts:", asset_db.counts_by_category())

if __name__ == "__main__":
    main()
