"""
Arabian Gulf offshore assets overlay (public dataset v0.1).

63 point features: field centroids, platform complexes, telecom cable
landings, one LNG terminal and one power-cable marker, covering Dubai,
Saudi Arabia, Qatar, Bahrain and Kuwait. All geometries are POINTS -
generalized centroids and landing-city locations, NOT engineering
coordinates; every hover tooltip carries the dataset's own
coordinate-quality caveat. Actual pipeline/cable ROUTES are not in this
dataset (EMODnet WMS layers cover those separately).

Loaded once at import (84 kB); both the Tracks and Track Animated maps
build their overlay from build_markers().
"""
import json
import os

import dash_leaflet as dl

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "Arabian_Gulf_Offshore_Assets_Public_v0_1.geojson")

CATEGORY_STYLE = {
    "Field / Discovery":     {"color": "#b45309", "label": "Field"},
    "Platform / Complex":    {"color": "#374151", "label": "Platform"},
    "Telecom Cable Landing": {"color": "#7c3aed", "label": "Cable landing"},
    "Power / Utility Cable": {"color": "#2563eb", "label": "Power cable"},
    "LNG Terminal":          {"color": "#dc2626", "label": "LNG terminal"},
}
_DEFAULT = {"color": "#6b7280", "label": "Asset"}


def _load():
    try:
        with open(_PATH, encoding="utf-8") as fh:
            return json.load(fh).get("features", [])
    except (OSError, ValueError):
        return []


_FEATURES = _load()


def feature_count():
    return len(_FEATURES)


def build_markers():
    """Small category-coloured dots with informative hover tooltips.
    Non-clickable (no pattern ids), so they can never interfere with the
    vessel-selection callbacks; bubbling disabled so a click on an asset
    does not count as a map click either."""
    out = []
    for f in _FEATURES:
        geom = f.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        lon, lat = geom.get("coordinates", (None, None))[:2]
        if lat is None or lon is None:
            continue
        p = f.get("properties", {})
        style = CATEGORY_STYLE.get(p.get("asset_category"), _DEFAULT)
        tip = [f"{p.get('asset_name', 'Unknown')} — {style['label']}"]
        sub = " · ".join(x for x in (p.get("asset_subtype"),
                                     p.get("operator_owner"),
                                     p.get("status_as_of_2026_07_29")) if x)
        if sub:
            tip.append(sub)
        qual = p.get("coordinate_quality")
        if qual:
            tip.append(f"({qual})")
        out.append(dl.CircleMarker(
            center=[lat, lon], radius=4.5,
            color="white", weight=1,
            fillColor=style["color"], fillOpacity=0.85,
            bubblingMouseEvents=False, interactive=True,
            children=dl.Tooltip(" — ".join(tip[:1]) + (
                "\n" + " | ".join(tip[1:]) if len(tip) > 1 else ""))))
    return out
