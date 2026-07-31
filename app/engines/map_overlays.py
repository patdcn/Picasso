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

RENDERING (phase 1, client-side): each category is ONE dl.GeoJSON
component. Per-feature display properties (__color, __dash, __shape,
__tip, __fill) are computed here and rendered by the generic functions in
app/assets/vt_overlays.js - Python stays the single source of truth for
styling, the browser does the drawing (canvas), which keeps large layers
(hundreds of routes) smooth. Long routes are decimated to chart-level
vertex counts before shipping.
"""
import html as _html
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


def _tooltip(name, operator, region, country, locode, props):
    parts = [name]
    props = props or {}
    code = locode or props.get("wpi_number")
    sub = " · ".join(x for x in (operator, region, country, code) if x)
    if sub:
        parts.append(sub)
    note = props.get("coordinate_quality") or props.get("source_note")
    if note:
        parts.append(f"({note})")
    return " | ".join(parts)


# point-marker shapes per category; default is a circle
POINT_SHAPES = {"platform": "square", "well": "pentagon"}

_MAX_VERTICES = 400          # decimate chart-level routes beyond this
_JS = {k: {"variable": f"vtOverlays.{k}"}
       for k in ("style", "pointToLayer", "onEachFeature")}


def _decimate(coords):
    n = len(coords)
    if n <= _MAX_VERTICES:
        return coords
    stride = -(-n // _MAX_VERTICES)
    out = coords[::stride]
    if out[-1] != coords[-1]:
        out.append(coords[-1])
    return out


def _decimate_geom(gtype, geom):
    try:
        if gtype == "LineString":
            return {"type": gtype,
                    "coordinates": _decimate(geom["coordinates"])}
        if gtype == "MultiLineString":
            return {"type": gtype,
                    "coordinates": [_decimate(l) for l in geom["coordinates"]]}
        if gtype == "Polygon":
            return {"type": gtype,
                    "coordinates": [_decimate(r) for r in geom["coordinates"]]}
        if gtype == "MultiPolygon":
            return {"type": gtype,
                    "coordinates": [[_decimate(r) for r in poly]
                                    for poly in geom["coordinates"]]}
    except (KeyError, TypeError):
        pass
    return geom


def _feature(category, meta, name, operator, region, country, locode,
             gtype, geom, props):
    display = {
        "__color": meta["color"],
        "__dash": meta.get("dash"),
        "__tip": _html.escape(_tooltip(name, operator, region, country,
                                       locode, props)),
        "__shape": POINT_SHAPES.get(category, "circle"),
    }
    if meta["kind"] == "polygon" and gtype in ("Polygon", "MultiPolygon"):
        display["__fill"] = 0.12
        display["__weight"] = 1.5
    return {"type": "Feature",
            "geometry": _decimate_geom(gtype, geom),
            "properties": display}


def _feature_collection(ovl):
    meta = asset_db.CATEGORIES[ovl["category"]]
    feats = []
    try:
        for (name, operator, region, country, locode, gtype, geom,
             props) in asset_db.assets_for_map(ovl["category"]):
            feats.append(_feature(ovl["category"], meta, name, operator,
                                  region, country, locode, gtype, geom,
                                  props))
    except AisDbError:
        return {"type": "FeatureCollection", "features": []}
    return {"type": "FeatureCollection", "features": feats}


def build_layer(ovl):
    """Children for one overlay's LayerGroup: one dl.GeoJSON per category,
    rendered client-side by app/assets/vt_overlays.js."""
    if ovl["kind"] == "tile":
        return [dl.TileLayer(url=ovl["url"], opacity=0.9,
                             attribution=ovl.get("attribution", ""))]
    fc = _feature_collection(ovl)
    if not fc["features"]:
        return []
    return [dl.GeoJSON(
        data=fc,
        style=_JS["style"],
        pointToLayer=_JS["pointToLayer"],
        onEachFeature=_JS["onEachFeature"],
        interactive=True,
        bubblingMouseEvents=False,
    )]


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
