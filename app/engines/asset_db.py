"""
Subsea/offshore asset store (map_asset table in the ais Postgres).

CATEGORIES is the taxonomy registry: add a category here and it appears
as an overlay chip on both Tracker maps and as an option in the Subsea
Assets management page. Each category declares its geometry kind:

  point    -> lat/lon (platforms/jackets, subsea wells; field centroids)
  line     -> route (power cables, telecom/fibre cables, pipelines)
  polygon  -> shape (windfarms, EEZ, fields)

Geometry is stored as a GeoJSON geometry object in JSONB - no PostGIS
needed for rendering, and the nightly pg_dump covers everything.
"""
import json

from app.engines.ais_db import AisDbError, q

CATEGORIES = {
    "platform":      {"label": "Platforms / Jackets", "kind": "point",
                      "color": "#374151"},
    "well":          {"label": "Subsea Wells", "kind": "point",
                      "color": "#0e7490"},
    "power_cable":   {"label": "Power Cables", "kind": "line",
                      "color": "#2563eb", "dash": "6 6"},
    "telecom_cable": {"label": "Telecom / Fibre", "kind": "line",
                      "color": "#7c3aed", "dash": "6 6"},
    "pipeline":      {"label": "Pipelines", "kind": "line",
                      "color": "#b45309", "dash": None},
    "windfarm":      {"label": "Windfarms", "kind": "polygon",
                      "color": "#059669"},
    "eez":           {"label": "EEZ", "kind": "polygon",
                      "color": "#9ca3af"},
    "field":         {"label": "Fields", "kind": "polygon",
                      "color": "#b45309"},
    "anchorage":     {"label": "Anchorage areas", "kind": "polygon",
                      "color": "#c026d3"},
    "port":          {"label": "Ports", "kind": "polygon",
                      "color": "#e11d48"},
}

_POINT_OK = {"Point"}
_LINE_OK = {"LineString", "MultiLineString"}
_POLY_OK = {"Polygon", "MultiPolygon"}
# fields arrive as centroids from public bundles: allow points there too
_ALLOWED = {"point": _POINT_OK, "line": _LINE_OK,
            "polygon": _POLY_OK | _POINT_OK}


# --- geometry parsing (management page input) --------------------------------
def parse_geometry(category, lat=None, lon=None, text=None):
    """Build (geom_type, geometry-dict) from form input, or raise ValueError.
    - point categories: lat + lon fields
    - line/polygon: textarea with one 'lat, lon' per line, OR a pasted
      GeoJSON geometry object (starts with '{'). Polygon rings are closed
      automatically."""
    kind = CATEGORIES[category]["kind"]
    text = (text or "").strip()
    if kind == "point" or (not text and lat not in (None, "") and lon not in (None, "")):
        try:
            la, lo = float(lat), float(lon)
        except (TypeError, ValueError):
            raise ValueError("Latitude and longitude must be numbers.")
        if not (-90 <= la <= 90 and -180 <= lo <= 180):
            raise ValueError("Lat/lon out of range.")
        return "Point", {"type": "Point", "coordinates": [lo, la]}

    if not text:
        raise ValueError("Provide coordinates: one 'lat, lon' per line, "
                         "or paste a GeoJSON geometry.")
    if text.startswith("{"):
        try:
            g = json.loads(text)
        except ValueError:
            raise ValueError("Invalid JSON in geometry field.")
        gtype = g.get("type")
        if gtype not in _ALLOWED[kind]:
            raise ValueError(f"Geometry type {gtype!r} not valid for "
                             f"{CATEGORIES[category]['label']}.")
        if not g.get("coordinates"):
            raise ValueError("GeoJSON geometry has no coordinates.")
        return gtype, {"type": gtype, "coordinates": g["coordinates"]}

    pts = []
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip().replace(";", ",")
        if not line:
            continue
        parts = [p for p in line.replace(",", " ").split() if p]
        if len(parts) < 2:
            raise ValueError(f"Line {i}: expected 'lat, lon'.")
        try:
            la, lo = float(parts[0]), float(parts[1])
        except ValueError:
            raise ValueError(f"Line {i}: expected numbers, got {line!r}.")
        if not (-90 <= la <= 90 and -180 <= lo <= 180):
            raise ValueError(f"Line {i}: lat/lon out of range.")
        pts.append([lo, la])
    if kind == "line":
        if len(pts) < 2:
            raise ValueError("A route needs at least 2 points.")
        return "LineString", {"type": "LineString", "coordinates": pts}
    if len(pts) < 3:
        raise ValueError("A shape needs at least 3 points.")
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return "Polygon", {"type": "Polygon", "coordinates": [pts]}


# --- queries -----------------------------------------------------------------
def list_assets(category=None, region=None, search=None, country=None):
    sql = """SELECT id, category, name, operator, region, country,
                    un_locode, geom_type, geometry, properties, source,
                    updated_at
             FROM map_asset WHERE active"""
    params = []
    if category:
        sql += " AND category=%s"; params.append(category)
    if region:
        sql += " AND region=%s"; params.append(region)
    if country:
        sql += " AND country=%s"; params.append(country)
    if search:
        sql += " AND (name ILIKE %s OR operator ILIKE %s)"
        params += [f"%{search}%", f"%{search}%"]
    sql += " ORDER BY category, name"
    return q(sql, params or None)


def assets_for_map(category):
    return q("""SELECT name, operator, region, country, un_locode,
                       geom_type, geometry, properties
                FROM map_asset WHERE active AND category=%s""", (category,))


def counts_by_category():
    return dict(q("""SELECT category, count(*) FROM map_asset
                     WHERE active GROUP BY category"""))


def countries():
    return [r[0] for r in q("""SELECT DISTINCT country FROM map_asset
                               WHERE active AND country IS NOT NULL
                               ORDER BY country""")]


def regions():
    return [r[0] for r in q("""SELECT DISTINCT region FROM map_asset
                               WHERE active AND region IS NOT NULL
                               ORDER BY region""")]


def _lift(properties):
    """Pop country/un_locode out of properties into columns; the AG
    bundle's 'jurisdiction' feeds country as fallback (and stays in
    properties as source data)."""
    props = dict(properties or {})
    country = props.pop("country", None) or props.get("jurisdiction")
    locode = props.pop("un_locode", None)
    return country, (locode.upper() if locode else None), props


def asset_insert(category, name, operator, region, geom_type, geometry,
                 properties=None, source="manual"):
    if category not in CATEGORIES:
        raise ValueError(f"Unknown category {category!r}")
    country, locode, props = _lift(properties)
    q("""INSERT INTO map_asset (category, name, operator, region, country,
                                un_locode, geom_type, geometry, properties,
                                source)
         VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)""",
      (category, name, operator or None, region or None, country, locode,
       geom_type, json.dumps(geometry), json.dumps(props), source))


def asset_update(asset_id, category, name, operator, region,
                 geom_type=None, geometry=None, properties=None):
    if properties is not None:
        country, locode, props = _lift(properties)
        q("""UPDATE map_asset SET properties=%s::jsonb, country=%s,
                 un_locode=%s, updated_at=now()
             WHERE id=%s""",
          (json.dumps(props), country, locode, asset_id))
    if geometry is not None:
        q("""UPDATE map_asset SET category=%s, name=%s, operator=%s,
                 region=%s, geom_type=%s, geometry=%s::jsonb, updated_at=now()
             WHERE id=%s""",
          (category, name, operator or None, region or None, geom_type,
           json.dumps(geometry), asset_id))
    else:
        q("""UPDATE map_asset SET category=%s, name=%s, operator=%s,
                 region=%s, updated_at=now() WHERE id=%s""",
          (category, name, operator or None, region or None, asset_id))


def asset_get(asset_id):
    rows = q("""SELECT id, category, name, operator, region, country,
                       un_locode, geom_type, geometry, properties, source
                FROM map_asset WHERE id=%s AND active""", (asset_id,))
    return rows[0] if rows else None


def asset_delete(asset_id):
    q("UPDATE map_asset SET active=FALSE, updated_at=now() WHERE id=%s",
      (asset_id,))


def replace_source(source, rows):
    """Bulk (re)import: deactivate everything from `source`, then insert
    the new rows [(category, name, operator, region, geom_type, geometry,
    properties)]. Manual assets are never touched."""
    q("UPDATE map_asset SET active=FALSE, updated_at=now() WHERE source=%s",
      (source,))
    n = 0
    for cat, name, operator, region, gtype, geom, props in rows:
        if cat not in CATEGORIES or not geom:
            continue
        asset_insert(cat, name, operator, region, gtype, geom, props, source)
        n += 1
    return n
