"""
Vessel Tracker - Subsea Assets.

Management app for the map_asset store behind the Tracker map overlays:
platforms/jackets, subsea wells, power/telecom cables, pipelines,
windfarms, EEZ, fields, anchorage areas and ports - across all regions
(AG, WAF, MED, Europe, ...).

- Table with search + category + region filters; source column shows
  where each asset came from (manual, ag_bundle_v0_1, osm_overpass).
- Add/Edit through one form (permanently in the layout, hidden - the
  phantom-input lesson): point categories take lat/lon, routes and
  shapes take one 'lat, lon' pair per line or a pasted GeoJSON geometry.
  Polygon rings close themselves.
- Delete is a two-step in-row confirm and soft (active=FALSE) - data is
  heilig.
- Edit rights reuse the param_modules mechanism: the "edit subsea
  assets" checkbox in Admin -> Users; admins implicit; everyone else
  view-only (enforced server-side as well).
"""
import json

import dash
from dash import html, dcc, Input, Output, State, callback, ctx

from app import auth
import dash_leaflet as dl

from app.engines import ais_db, asset_db

PAGE_PATH = "/vessel-tracker/assets"

dash.register_page(__name__, path=PAGE_PATH, name="Subsea Assets",
                   category="Vessel Tracker", order=1.5)

MUTED = "#6b7280"
LINE = "#d1d5db"
HEAD_BG = "#f8fafc"
GREEN = "#047857"
RED = "#b91c1c"
TEAL = "#0f766e"

_CELL = {"padding": "4px 8px", "borderBottom": f"1px solid {LINE}",
         "fontSize": "0.8rem", "whiteSpace": "nowrap"}
_TH = {**_CELL, "textAlign": "left", "background": HEAD_BG, "color": MUTED,
       "fontWeight": "600", "position": "sticky", "top": "0", "zIndex": "1"}
_BTN = {"padding": "3px 10px", "borderRadius": "6px", "fontSize": "0.78rem",
        "cursor": "pointer", "border": f"1px solid {LINE}", "background": "white"}
_IN = {"fontSize": "0.8rem", "padding": "4px 8px",
       "border": f"1px solid {LINE}", "borderRadius": "6px"}

_CAT_OPTIONS = [{"label": m["label"], "value": k}
                for k, m in asset_db.CATEGORIES.items()]


def _geom_centroid_zoom(gtype, geometry):
    """Rough centroid + a sensible zoom for a geometry, to frame it on the
    draw map."""
    def pts(coords):
        # a coordinate pair is [num, num]; recurse only into nesting
        if coords and isinstance(coords[0], (int, float)):
            yield coords
            return
        for c in coords:
            yield from pts(c)
    try:
        xs = list(pts(geometry["coordinates"]))
        lons = [p[0] for p in xs]; lats = [p[1] for p in xs]
        center = [sum(lats) / len(lats), sum(lons) / len(lons)]
        span = max(max(lons) - min(lons), max(lats) - min(lats), 0.001)
        # crude: smaller span -> higher zoom
        zoom = 6 if span > 2 else 8 if span > 0.3 else 11 if span > 0.03 else 13
        return center, zoom
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return [52.45, 4.6], 8


def _geom_summary(geom_type, geometry):
    try:
        if geom_type == "Point":
            lon, lat = geometry["coordinates"][:2]
            return f"{lat:.4f}, {lon:.4f}"
        if geom_type == "LineString":
            return f"route · {len(geometry['coordinates'])} pts"
        if geom_type == "MultiLineString":
            return f"route · {sum(len(l) for l in geometry['coordinates'])} pts"
        if geom_type == "Polygon":
            return f"shape · {len(geometry['coordinates'][0])} pts"
        if geom_type == "MultiPolygon":
            return f"shape · {len(geometry['coordinates'])} parts"
    except (KeyError, IndexError, TypeError):
        pass
    return geom_type


def _build_table(pending_delete, can_edit, search, fcat, fregion,
                 fcountry=None):
    rows = asset_db.list_assets(category=fcat or None, region=fregion or None,
                                search=search or None,
                                country=fcountry or None)
    headers = ["Name", "Category", "Region", "Country", "Geometry",
               "Operator", "Source", "Updated", "Action"]
    body = []
    for (aid, cat, name, operator, region, country, locode, gtype,
         geometry, _props, source, updated) in rows:
        meta = asset_db.CATEGORIES.get(cat, {"label": cat, "color": MUTED})
        if not can_edit:
            action = html.Span("\u2014", style={"color": "#c0c5cc"},
                               title="View-only; ask an admin for "
                                     "'edit subsea assets' rights")
        elif pending_delete == str(aid):
            action = html.Span([
                html.Button("Confirm", n_clicks=0,
                            id={"type": "vas-del-confirm", "aid": str(aid)},
                            style={**_BTN, "background": "#fef2f2",
                                   "borderColor": "#fecaca", "color": RED,
                                   "marginRight": "5px"}),
                html.Button("Cancel", n_clicks=0,
                            id={"type": "vas-del-cancel", "aid": str(aid)},
                            style=_BTN)])
        else:
            action = html.Span([
                html.Button("Edit", n_clicks=0,
                            id={"type": "vas-edit", "aid": str(aid)},
                            style={**_BTN, "marginRight": "5px"}),
                html.Button("Delete", n_clicks=0,
                            id={"type": "vas-del", "aid": str(aid)},
                            style=_BTN)])
        body.append(html.Tr([
            html.Td(name, style=_CELL),
            html.Td([html.Span("\u25cf ", style={"color": meta["color"]}),
                     meta["label"]], style=_CELL),
            html.Td(region or "\u2014", style=_CELL),
            html.Td(country or "\u2014", style=_CELL,
                    title=f"UN/LOCODE: {locode}" if locode else None),
            html.Td(_geom_summary(gtype, geometry), style=_CELL),
            html.Td(operator or "\u2014",
                    style={**_CELL, "maxWidth": "200px", "overflow": "hidden",
                           "textOverflow": "ellipsis"}, title=operator),
            html.Td(source, style={**_CELL, "color": MUTED}),
            html.Td(updated.strftime("%d-%m-%y"), style=_CELL),
            html.Td(action, style=_CELL),
        ]))
    if not body:
        body = [html.Tr(html.Td("No assets match the current filters.",
                                colSpan=9,
                                style={**_CELL, "color": MUTED}))]
    table = html.Div(
        html.Table([html.Thead(html.Tr([html.Th(h, style=_TH)
                                        for h in headers])),
                    html.Tbody(body)],
                   style={"borderCollapse": "collapse", "width": "100%"}),
        style={"maxHeight": "62vh", "overflow": "auto",
               "border": f"1px solid {LINE}", "borderRadius": "8px"})
    counter = f"{len(rows)} assets shown"
    return table, counter


def _banner(msg, ok=True):
    if not msg:
        return None
    return html.Div(msg, style={
        "border": f"1px solid {'#bbf7d0' if ok else '#fecaca'}",
        "background": "#f0fdf4" if ok else "#fef2f2",
        "color": GREEN if ok else RED,
        "borderRadius": "8px", "padding": "8px 14px", "margin": "8px 0",
        "fontSize": "0.85rem"})


layout = html.Div(className="full-width-page", children=[
    html.H3("Subsea Assets"),
    html.P("Platforms, wells, cables, pipelines, windfarms, EEZ, fields, "
           "anchorages and ports - the data behind the Tracker map "
           "overlays. Chart-level positions: never a substitute for the "
           "project survey.",
           style={"color": MUTED, "maxWidth": "760px"}),
    html.Div([
        html.Button("+ Add asset", id="vas-add-open", n_clicks=0,
                    style={**_BTN, "padding": "6px 14px",
                           "fontWeight": "600"}),
        html.Button("Refresh", id="vas-refresh", n_clicks=0,
                    style={**_BTN, "padding": "6px 14px",
                           "marginLeft": "8px"}),
        dcc.Input(id="vas-search", value="", debounce=True, type="text",
                  placeholder="Search name / operator\u2026",
                  style={**_IN, "width": "200px", "marginLeft": "14px"}),
        dcc.Dropdown(id="vas-fcat", options=_CAT_OPTIONS, placeholder="Category",
                     clearable=True,
                     style={"width": "180px", "display": "inline-block",
                            "verticalAlign": "middle", "marginLeft": "8px",
                            "fontSize": "0.8rem"}),
        dcc.Dropdown(id="vas-fregion", placeholder="Region", clearable=True,
                     style={"width": "130px", "display": "inline-block",
                            "verticalAlign": "middle", "marginLeft": "8px",
                            "fontSize": "0.8rem"}),
        dcc.Dropdown(id="vas-fcountry", placeholder="Country", clearable=True,
                     style={"width": "150px", "display": "inline-block",
                            "verticalAlign": "middle", "marginLeft": "8px",
                            "fontSize": "0.8rem"}),
        html.Span(id="vas-counter",
                  style={"marginLeft": "14px", "color": MUTED}),
    ], style={"margin": "6px 0 4px", "display": "flex",
              "alignItems": "center", "flexWrap": "wrap", "gap": "2px"}),
    # add/edit form: permanently present, hidden (phantom-input lesson)
    html.Div(id="vas-form", style={"display": "none"}, children=html.Div([
        html.Div(id="vas-form-title", children="New asset",
                 style={"fontWeight": "600", "marginBottom": "6px",
                        "fontSize": "0.85rem"}),
        html.Div([
            dcc.Input(id="vas-f-name", value="", placeholder="Name *",
                      style={**_IN, "width": "200px",
                             "borderColor": "#f59e0b"}),
            dcc.Dropdown(id="vas-f-cat", options=_CAT_OPTIONS,
                         placeholder="Category *", clearable=False,
                         style={"width": "190px", "display": "inline-block",
                                "verticalAlign": "middle",
                                "fontSize": "0.8rem"}),
            dcc.Input(id="vas-f-region", value="",
                      placeholder="Region (AG/WAF/MED/\u2026)",
                      style={**_IN, "width": "150px"}),
            dcc.Input(id="vas-f-operator", value="", placeholder="Operator",
                      style={**_IN, "width": "180px"}),
            dcc.Input(id="vas-f-country", value="", placeholder="Country",
                      style={**_IN, "width": "130px"}),
            dcc.Input(id="vas-f-code", value="",
                      placeholder="Code (UN/LOCODE / WPI)",
                      style={**_IN, "width": "160px"}),
        ], style={"display": "flex", "flexWrap": "wrap", "gap": "6px",
                  "alignItems": "center", "marginBottom": "6px"}),
        html.Div([
            dcc.Input(id="vas-f-lat", value="", placeholder="Lat",
                      style={**_IN, "width": "110px"}),
            dcc.Input(id="vas-f-lon", value="", placeholder="Lon",
                      style={**_IN, "width": "110px"}),
            html.Span("point categories", style={"color": MUTED,
                                                 "fontSize": "0.72rem"}),
        ], style={"display": "flex", "gap": "6px", "alignItems": "center",
                  "marginBottom": "6px"}),
        dcc.Textarea(id="vas-f-coords", value="",
                     placeholder=("Route/shape: one 'lat, lon' per line "
                                  "(polygon closes itself), or paste a "
                                  "GeoJSON geometry {\u2026}, or use "
                                  "\u201cDraw on map\u201d below"),
                     style={**_IN, "width": "100%", "minHeight": "70px",
                            "fontFamily": "monospace"}),
        html.Div([
            html.Button("\u270e Draw on map", id="vas-draw-toggle",
                        n_clicks=0, style={**_BTN, "marginTop": "6px"}),
            html.Span(id="vas-draw-hint", style={"marginLeft": "10px",
                      "color": MUTED, "fontSize": "0.72rem"}),
        ]),
        html.Div(id="vas-draw-wrap", style={"display": "none"}, children=[
            dl.Map(id="vas-draw-map", center=[52.45, 4.6], zoom=8,
                   style={"height": "340px", "width": "100%",
                          "marginTop": "8px", "borderRadius": "8px"},
                   children=[
                       dl.LayersControl(position="topleft", children=[
                           dl.BaseLayer(dl.TileLayer(), name="OpenStreetMap",
                                        checked=True),
                           dl.BaseLayer(
                               dl.TileLayer(
                                   url="https://server.arcgisonline.com/ArcGIS/"
                                       "rest/services/Ocean/World_Ocean_Base/"
                                       "MapServer/tile/{z}/{y}/{x}",
                                   attribution="Esri Ocean"),
                               name="Esri Ocean", checked=False),
                           dl.Overlay(
                               dl.TileLayer(
                                   url="https://tiles.openseamap.org/seamark/"
                                       "{z}/{x}/{y}.png",
                                   attribution="© OpenSeaMap"),
                               name="Seamarks", checked=True),
                           dl.Overlay(dl.LayerGroup(id="vas-draw-context"),
                                      name="Existing assets", checked=True),
                       ]),
                       dl.FeatureGroup(id="vas-draw-fg", children=[
                           dl.EditControl(
                               id="vas-draw-edit",
                               position="topright",
                               draw={"polygon": True, "polyline": True,
                                     "marker": True, "rectangle": False,
                                     "circle": False, "circlemarker": False},
                               edit={"edit": True, "remove": True}),
                       ]),
                   ]),
            html.Div("Draw a polygon, route or point; it fills the "
                     "geometry field above. Toggle Seamarks or Esri Ocean "
                     "as backdrop via the layers control (top-left). When "
                     "editing, the existing shape is loaded for adjustment; "
                     "if it does not appear, the text field still holds it. "
                     "Use the trash tool to clear.",
                     style={"color": MUTED, "fontSize": "0.72rem",
                            "marginTop": "4px"}),
        ]),
        html.Div([
            html.Button("Save asset", id="vas-f-save", n_clicks=0,
                        style={**_BTN, "background": "#f0fdf4",
                               "borderColor": "#bbf7d0", "color": GREEN,
                               "marginRight": "6px"}),
            html.Button("Cancel", id="vas-f-cancel", n_clicks=0, style=_BTN),
        ], style={"marginTop": "8px"}),
    ], style={"border": f"1px solid {LINE}", "borderRadius": "8px",
              "padding": "10px 14px", "margin": "6px 0",
              "background": "#f8fafc"})),
    html.Div(id="vas-banner"),
    dcc.Store(id="vas-pending-delete", data=None),
    dcc.Store(id="vas-editing", data=None),     # asset id under edit, or None
    dcc.Store(id="vas-form-open", data=False),
    dcc.Store(id="vas-draw-open", data=False),
    dcc.Store(id="vas-draw-seed", data=None),   # geometry to preload on edit
    dcc.Store(id="vas-draw-clearn", data=0),    # monotonic clear-all counter
    dcc.Loading(html.Div(id="vas-content"), type="default"),
])


@callback(
    Output("vas-content", "children"),
    Output("vas-counter", "children"),
    Output("vas-banner", "children"),
    Output("vas-pending-delete", "data"),
    Output("vas-editing", "data"),
    Output("vas-form-open", "data"),
    Output("vas-form", "style"),
    Output("vas-form-title", "children"),
    Output("vas-fregion", "options"),
    Output("vas-fcountry", "options"),
    Output("vas-draw-context", "children"),
    Output("vas-draw-map", "viewport"),
    Output("vas-draw-edit", "editToolbar"),
    Output("vas-draw-clearn", "data"),
    Output("vas-f-name", "value"),
    Output("vas-f-cat", "value"),
    Output("vas-f-region", "value"),
    Output("vas-f-operator", "value"),
    Output("vas-f-lat", "value"),
    Output("vas-f-lon", "value"),
    Output("vas-f-coords", "value"),
    Output("vas-f-country", "value"),
    Output("vas-f-code", "value"),
    Input("vas-refresh", "n_clicks"),
    Input("vas-add-open", "n_clicks"),
    Input("vas-f-save", "n_clicks"),
    Input("vas-f-cancel", "n_clicks"),
    Input("vas-search", "value"),
    Input("vas-fcat", "value"),
    Input("vas-fregion", "value"),
    Input("vas-fcountry", "value"),
    Input({"type": "vas-edit", "aid": dash.ALL}, "n_clicks"),
    Input({"type": "vas-del", "aid": dash.ALL}, "n_clicks"),
    Input({"type": "vas-del-confirm", "aid": dash.ALL}, "n_clicks"),
    Input({"type": "vas-del-cancel", "aid": dash.ALL}, "n_clicks"),
    State("vas-f-name", "value"), State("vas-f-cat", "value"),
    State("vas-f-region", "value"), State("vas-f-operator", "value"),
    State("vas-f-lat", "value"), State("vas-f-lon", "value"),
    State("vas-f-coords", "value"),
    State("vas-f-country", "value"), State("vas-f-code", "value"),
    State("vas-pending-delete", "data"),
    State("vas-editing", "data"),
    State("vas-form-open", "data"),
    State("vas-draw-clearn", "data"),
)
def _actions(_r, _ao, _fs, _fc, search, fcat, fregion, fcountry,
             _e, _d, _dc, _dx,
             f_name, f_cat, f_region, f_operator, f_lat, f_lon, f_coords,
             f_country, f_code,
             pending, editing, form_open, clear_n):
    trig = ctx.triggered_id
    clicked = bool(ctx.triggered) and bool(ctx.triggered[0].get("value"))
    can_edit = auth.may_edit_params(auth.current_user(), PAGE_PATH)
    banner, ok = None, True
    new_pending, new_editing = None, editing
    new_open = bool(form_open) and can_edit
    form_vals = [dash.no_update] * 9
    ref_children = dash.no_update       # reference shape shown under drawing
    map_viewport = dash.no_update
    clear_drawn = dash.no_update         # editToolbar "clear all" payload

    _MUT = ("vas-edit", "vas-del", "vas-del-confirm")
    try:
        if (clicked and not can_edit
                and ((isinstance(trig, dict) and trig.get("type") in _MUT)
                     or trig in ("vas-add-open", "vas-f-save"))):
            banner, ok = ("You have view-only access to subsea assets; ask "
                          "an admin for 'edit subsea assets' rights.", False)
        elif clicked and isinstance(trig, dict):
            aid = int(trig["aid"])
            kind = trig["type"]
            if kind == "vas-del":
                new_pending, new_open = str(aid), False
            elif kind == "vas-del-cancel":
                new_pending = None
            elif kind == "vas-del-confirm":
                row = asset_db.asset_get(aid)
                asset_db.asset_delete(aid)
                banner = f"{row[2] if row else aid} deleted." if row else \
                    "Asset deleted."
            elif kind == "vas-edit":
                row = asset_db.asset_get(aid)
                if row:
                    (_id, cat, name, operator, region, country, locode,
                     gtype, geometry, _props, _src) = row
                    lat = lon = ""
                    coords = ""
                    if gtype == "Point":
                        lon_v, lat_v = geometry["coordinates"][:2]
                        lat, lon = f"{lat_v}", f"{lon_v}"
                    else:
                        coords = json.dumps(
                            {"type": gtype,
                             "coordinates": geometry["coordinates"]})
                    form_vals = [name, cat, region or "", operator or "",
                                 lat, lon, coords, country or "",
                                 locode or (_props or {}).get("wpi_number",
                                                              "")]
                    ref_children = _reference_layer(gtype, geometry)
                    _c, _z = _geom_centroid_zoom(gtype, geometry)
                    map_viewport = {"center": _c, "zoom": _z,
                                    "transition": "flyTo"}
                    clear_n = (clear_n or 0) + 1
                    clear_drawn = {"action": "clear all", "mode": "remove", "n_clicks": clear_n}
                    new_editing, new_open = str(aid), True
        elif clicked and trig == "vas-add-open":
            new_open = not new_open
            if new_open:
                new_editing = None
                form_vals = ["", None, "", "", "", "", "", "", ""]
                ref_children = []
                clear_n = (clear_n or 0) + 1
                clear_drawn = {"action": "clear all", "mode": "remove", "n_clicks": clear_n}
        elif clicked and trig == "vas-f-cancel":
            new_open, new_editing = False, None
            ref_children = []
            clear_n = (clear_n or 0) + 1
            clear_drawn = {"action": "clear all", "mode": "remove", "n_clicks": clear_n}
        elif clicked and trig == "vas-f-save":
            name = (f_name or "").strip()
            if not name or not f_cat:
                banner, ok, new_open = "Name and category are mandatory.", \
                    False, True
            else:
                gtype, geom = asset_db.parse_geometry(
                    f_cat, lat=f_lat, lon=f_lon, text=f_coords)
                meta = {}
                if (f_country or "").strip():
                    meta["country"] = f_country.strip()
                code = (f_code or "").strip().upper()
                if code:
                    key = ("un_locode" if len(code) == 5 and code.isalpha()
                           else "wpi_number")
                    meta[key] = code
                if editing:
                    row = asset_db.asset_get(int(editing))
                    props = dict(row[9] or {}) if row else {}
                    props.pop("wpi_number", None)
                    props.pop("jurisdiction", None)   # country is nu leidend
                    props.update(meta)
                    asset_db.asset_update(int(editing), f_cat, name,
                                          f_operator, f_region, gtype, geom,
                                          properties=props)
                    banner = f"{name} updated."
                else:
                    asset_db.asset_insert(f_cat, name, f_operator, f_region,
                                          gtype, geom, properties=meta)
                    banner = (f"{name} added - visible on the Tracker maps "
                              f"under '{asset_db.CATEGORIES[f_cat]['label']}'.")
                new_open, new_editing = False, None
                ref_children = []          # wis de referentie-mal
                clear_n = (clear_n or 0) + 1
                clear_drawn = {"action": "clear all", "mode": "remove", "n_clicks": clear_n}   # wis de getekende laag
    except ValueError as exc:
        banner, ok, new_open = str(exc), False, True
    except (ais_db.AisDbError,) as exc:
        banner, ok = str(exc), False
    except Exception as exc:  # never kill the page
        banner, ok = f"Unexpected error: {exc}", False

    try:
        table, counter = _build_table(new_pending, can_edit, search, fcat,
                                      fregion, fcountry)
        region_opts = asset_db.regions()
        country_opts = asset_db.countries()
    except Exception as exc:
        return (_banner(str(exc), ok=False), "", None, None, None, False,
                {"display": "none"}, "New asset", [], [], dash.no_update,
                dash.no_update, dash.no_update,
                dash.no_update, *[dash.no_update] * 9)

    style = {"display": "block"} if new_open else {"display": "none"}
    title = "Edit asset" if new_editing else "New asset"
    return (table, counter, _banner(banner, ok), new_pending, new_editing,
            new_open, style, title, region_opts, country_opts, ref_children,
            map_viewport, clear_drawn, clear_n, *form_vals)


def _reference_layer(gtype, geometry):
    """The asset's current shape, shown as a dashed highlight on the draw
    map so the user can trace or adjust over it (EditControl.geojson is
    read-only, so the original points are not draggable - this is the
    visible guide)."""
    ref = "#dc2626"
    tip = dl.Tooltip("current shape (reference)")
    if gtype == "Point":
        lon, lat = geometry["coordinates"][:2]
        return [dl.CircleMarker(center=[lat, lon], radius=8, color=ref,
                                weight=2, fillColor=ref, fillOpacity=0.3,
                                interactive=False, children=tip)]
    if gtype in ("LineString", "MultiLineString"):
        lines = ([geometry["coordinates"]] if gtype == "LineString"
                 else geometry["coordinates"])
        out = []
        for line in lines:
            out.append(dl.Polyline(positions=[[c[1], c[0]] for c in line],
                                   color=ref, weight=3, opacity=0.7,
                                   dashArray="6 6", interactive=False,
                                   children=tip))
        return out
    if gtype in ("Polygon", "MultiPolygon"):
        polys = ([geometry["coordinates"]] if gtype == "Polygon"
                 else geometry["coordinates"])
        out = []
        for rings in polys:
            if rings:
                out.append(dl.Polygon(
                    positions=[[c[1], c[0]] for c in rings[0]], color=ref,
                    weight=2, opacity=0.8, fillColor=ref, fillOpacity=0.1,
                    dashArray="6 6", interactive=False, children=tip))
        return out
    return []


# --- draw-on-map panel -------------------------------------------------------
# The EditControl returns drawn features as a FeatureCollection in its
# `geojson` prop. We take the LAST drawn feature's geometry and write it,
# as a compact GeoJSON geometry object, into the coords textarea - which the
# existing parse_geometry() already understands (it detects a leading '{').

@callback(
    Output("vas-draw-wrap", "style"),
    Output("vas-draw-open", "data"),
    Output("vas-draw-toggle", "children"),
    Input("vas-draw-toggle", "n_clicks"),
    State("vas-draw-open", "data"),
    prevent_initial_call=True,
)
def _toggle_draw(n, is_open):
    is_open = not bool(is_open)
    style = {"display": "block"} if is_open else {"display": "none"}
    label = "\u2715 Close map" if is_open else "\u270e Draw on map"
    return style, is_open, label


@callback(
    Output("vas-f-coords", "value", allow_duplicate=True),
    Output("vas-draw-hint", "children"),
    Input("vas-draw-edit", "geojson"),
    State("vas-draw-edit", "action"),
    State("vas-draw-open", "data"),
    prevent_initial_call=True,
)
def _drawn_to_coords(fc, action, is_open):
    # Only react to genuine user drawing/editing, not to the seed that the
    # main callback writes into `geojson` when opening the form for edit.
    # A user draw/edit/delete sets EditControl.action; a programmatic
    # geojson-set does not.
    if not action:
        return dash.no_update, dash.no_update
    if not is_open or not fc:
        return dash.no_update, dash.no_update
    feats = (fc or {}).get("features") or []
    if not feats:
        return dash.no_update, "Cleared - draw a new shape."
    geom = (feats[-1] or {}).get("geometry") or {}
    gtype = geom.get("type")
    if gtype not in ("Point", "LineString", "Polygon"):
        return dash.no_update, dash.no_update
    n = 1
    if gtype == "LineString":
        n = len(geom.get("coordinates", []))
    elif gtype == "Polygon":
        rings = geom.get("coordinates", [[]])
        n = len(rings[0]) if rings else 0
    hint = f"{gtype} captured ({n} pts) \u2192 geometry field filled."
    if len(feats) > 1:
        hint += f"  (using the last of {len(feats)} shapes)"
    return json.dumps(geom), hint


# grey-tiles fix: Leaflet must recalculate its size once the (previously
# display:none) map panel becomes visible, otherwise only a grey strip of
# tiles renders. This clientside callback fires on panel open and pokes the
# map via a window resize event, which dash-leaflet listens to.
dash.clientside_callback(
    """
    function(is_open) {
        if (is_open) {
            setTimeout(function() {
                window.dispatchEvent(new Event('resize'));
            }, 120);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("vas-draw-map", "id"),
    Input("vas-draw-open", "data"),
    prevent_initial_call=True,
)
