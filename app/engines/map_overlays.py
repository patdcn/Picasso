"""
Map overlay registry for the Vessel Tracker maps (Tracks + Track Animated).

v2: database-driven. One overlay chip per asset category from
app/engines/asset_db.py (CATEGORIES is the single source of truth) plus
the OpenSeaMap seamarks tile layer. Counts refresh on every overlay
render; a category's chip shows (0) until its first asset exists.

MAINTENANCE:
- add/remove an overlay CATEGORY -> edit asset_db.CATEGORIES
- add/remove ASSETS -> Subsea Assets page, or the importers in app/tools/
The map pages themselves never change.
"""
import dash_leaflet as dl

from app.engines import asset_db
from app.engines.ais_db import AisDbError

_SEAMARKS = {
    "key": "seamarks",
    "label": "Seamarks",
    "kind": "tile",
    "url": "https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png",
    "attribution": "© OpenSeaMap contributors",
    "default_on": True,
    "hint": "Charted cables, pipelines, buoyage (symbols from ~zoom 9)",
}

OVERLAYS = [_SEAMARKS] + [
    {"key": key, "label": meta["label"], "kind": "db", "category": key,
     "default_on": key != "eez",       # EEZ shapes are large; opt-in
     "hint": "Managed on the Subsea Assets page"}
    for key, meta in asset_db.CATEGORIES.items()
]


def _tooltip(name, operator, region, props):
    parts = [name]
    sub = " · ".join(x for x in (operator, region) if x)
    if sub:
        parts.append(sub)
    note = (props or {}).get("coordinate_quality") or \
           (props or {}).get("source_note")
    if note:
        parts.append(f"({note})")
    return " | ".join(parts)


# point-marker shapes per category; default is a circle
POINT_SHAPES = {"platform": "square", "well": "triangle"}

_SHAPE_HTML = {
    "square": ('<div style="width:9px;height:9px;background:{c};'
               'border:1.5px solid white;box-shadow:0 0 1px #0006;"></div>',
               [12, 12], [6, 6]),
    "triangle": ('<div style="width:0;height:0;'
                 'border-left:6px solid transparent;'
                 'border-right:6px solid transparent;'
                 'border-bottom:11px solid {c};'
                 'filter:drop-shadow(0 0 1px white);"></div>',
                 [12, 12], [6, 7]),
}


def _point_marker(category, color, lat, lon, tip):
    shape = POINT_SHAPES.get(category)
    if shape:
        html, size, anchor = _SHAPE_HTML[shape]
        return dl.DivMarker(
            position=[lat, lon],
            iconOptions=dict(html=html.format(c=color), className="",
                             iconSize=size, iconAnchor=anchor),
            bubblingMouseEvents=False, interactive=True, children=tip)
    return dl.CircleMarker(
        center=[lat, lon], radius=4.5, color="white", weight=1,
        fillColor=color, fillOpacity=0.85,
        bubblingMouseEvents=False, interactive=True, children=tip)


def _render_asset(meta, name, operator, region, gtype, geom, props,
                  category=None):
    color = meta["color"]
    tip = [dl.Tooltip(_tooltip(name, operator, region, props))]
    out = []
    if gtype == "Point":
        lon, lat = geom["coordinates"][:2]
        out.append(_point_marker(category, color, lat, lon, tip))
    elif gtype in ("LineString", "MultiLineString"):
        lines = ([geom["coordinates"]] if gtype == "LineString"
                 else geom["coordinates"])
        for line in lines:
            latlons = [[c[1], c[0]] for c in line if len(c) >= 2]
            if len(latlons) >= 2:
                out.append(dl.Polyline(
                    positions=latlons, color=color, weight=1.6, opacity=0.75,
                    dashArray=meta.get("dash"),
                    bubblingMouseEvents=False, interactive=True, children=tip))
    elif gtype in ("Polygon", "MultiPolygon"):
        polys = ([geom["coordinates"]] if gtype == "Polygon"
                 else geom["coordinates"])
        for rings in polys:
            if not rings:
                continue
            latlons = [[c[1], c[0]] for c in rings[0] if len(c) >= 2]
            if len(latlons) >= 3:
                out.append(dl.Polygon(
                    positions=latlons, color=color, weight=1.5, opacity=0.7,
                    fillColor=color, fillOpacity=0.12,
                    bubblingMouseEvents=False, interactive=True, children=tip))
    return out


def build_layer(ovl):
    """Children for one overlay's LayerGroup."""
    if ovl["kind"] == "tile":
        return [dl.TileLayer(url=ovl["url"], opacity=0.9,
                             attribution=ovl.get("attribution", ""))]
    meta = asset_db.CATEGORIES[ovl["category"]]
    children = []
    try:
        for name, operator, region, gtype, geom, props in \
                asset_db.assets_for_map(ovl["category"]):
            children.extend(_render_asset(meta, name, operator, region,
                                          gtype, geom, props,
                                          category=ovl["category"]))
    except AisDbError:
        return []                     # DB briefly down: keep the map alive
    return children


def chip_label(ovl):
    if ovl["kind"] == "tile":
        return ovl["label"]
    try:
        n = asset_db.counts_by_category().get(ovl["category"], 0)
    except AisDbError:
        return ovl["label"]
    return f"{ovl['label']} ({n})"


def default_state():
    return {o["key"]: bool(o.get("default_on")) for o in OVERLAYS}


def by_key(key):
    for o in OVERLAYS:
        if o["key"] == key:
            return o
    return None


def legend_items():
    """(label, swatch-style dict, shape) per category for the map legend."""
    out = []
    for key, meta in asset_db.CATEGORIES.items():
        shape = POINT_SHAPES.get(key) or \
            ("line" if meta["kind"] == "line" else
             "polygon" if meta["kind"] == "polygon" else "circle")
        out.append((meta["label"], meta["color"], shape,
                    meta.get("dash") is not None))
    return out
