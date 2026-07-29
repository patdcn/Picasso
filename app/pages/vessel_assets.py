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


def _build_table(pending_delete, can_edit, search, fcat, fregion):
    rows = asset_db.list_assets(category=fcat or None, region=fregion or None,
                                search=search or None)
    headers = ["Name", "Category", "Region", "Operator", "Geometry",
               "Source", "Updated", "Action"]
    body = []
    for (aid, cat, name, operator, region, gtype, geometry, _props,
         source, updated) in rows:
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
            html.Td(operator or "\u2014",
                    style={**_CELL, "maxWidth": "220px", "overflow": "hidden",
                           "textOverflow": "ellipsis"}, title=operator),
            html.Td(_geom_summary(gtype, geometry), style=_CELL),
            html.Td(source, style={**_CELL, "color": MUTED}),
            html.Td(updated.strftime("%d-%m-%y"), style=_CELL),
            html.Td(action, style=_CELL),
        ]))
    if not body:
        body = [html.Tr(html.Td("No assets match the current filters.",
                                colSpan=8,
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
                                  "GeoJSON geometry {\u2026}"),
                     style={**_IN, "width": "100%", "minHeight": "90px",
                            "fontFamily": "monospace"}),
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
    Output("vas-f-name", "value"),
    Output("vas-f-cat", "value"),
    Output("vas-f-region", "value"),
    Output("vas-f-operator", "value"),
    Output("vas-f-lat", "value"),
    Output("vas-f-lon", "value"),
    Output("vas-f-coords", "value"),
    Input("vas-refresh", "n_clicks"),
    Input("vas-add-open", "n_clicks"),
    Input("vas-f-save", "n_clicks"),
    Input("vas-f-cancel", "n_clicks"),
    Input("vas-search", "value"),
    Input("vas-fcat", "value"),
    Input("vas-fregion", "value"),
    Input({"type": "vas-edit", "aid": dash.ALL}, "n_clicks"),
    Input({"type": "vas-del", "aid": dash.ALL}, "n_clicks"),
    Input({"type": "vas-del-confirm", "aid": dash.ALL}, "n_clicks"),
    Input({"type": "vas-del-cancel", "aid": dash.ALL}, "n_clicks"),
    State("vas-f-name", "value"), State("vas-f-cat", "value"),
    State("vas-f-region", "value"), State("vas-f-operator", "value"),
    State("vas-f-lat", "value"), State("vas-f-lon", "value"),
    State("vas-f-coords", "value"),
    State("vas-pending-delete", "data"),
    State("vas-editing", "data"),
    State("vas-form-open", "data"),
)
def _actions(_r, _ao, _fs, _fc, search, fcat, fregion,
             _e, _d, _dc, _dx,
             f_name, f_cat, f_region, f_operator, f_lat, f_lon, f_coords,
             pending, editing, form_open):
    trig = ctx.triggered_id
    clicked = bool(ctx.triggered) and bool(ctx.triggered[0].get("value"))
    can_edit = auth.may_edit_params(auth.current_user(), PAGE_PATH)
    banner, ok = None, True
    new_pending, new_editing = None, editing
    new_open = bool(form_open) and can_edit
    form_vals = [dash.no_update] * 7

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
                    (_id, cat, name, operator, region, gtype, geometry,
                     _props, _src) = row
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
                                 lat, lon, coords]
                    new_editing, new_open = str(aid), True
        elif clicked and trig == "vas-add-open":
            new_open = not new_open
            if new_open:
                new_editing = None
                form_vals = ["", None, "", "", "", "", ""]
        elif clicked and trig == "vas-f-cancel":
            new_open, new_editing = False, None
        elif clicked and trig == "vas-f-save":
            name = (f_name or "").strip()
            if not name or not f_cat:
                banner, ok, new_open = "Name and category are mandatory.", \
                    False, True
            else:
                gtype, geom = asset_db.parse_geometry(
                    f_cat, lat=f_lat, lon=f_lon, text=f_coords)
                if editing:
                    asset_db.asset_update(int(editing), f_cat, name,
                                          f_operator, f_region, gtype, geom)
                    banner = f"{name} updated."
                else:
                    asset_db.asset_insert(f_cat, name, f_operator, f_region,
                                          gtype, geom)
                    banner = (f"{name} added - visible on the Tracker maps "
                              f"under '{asset_db.CATEGORIES[f_cat]['label']}'.")
                new_open, new_editing = False, None
    except ValueError as exc:
        banner, ok, new_open = str(exc), False, True
    except (ais_db.AisDbError,) as exc:
        banner, ok = str(exc), False
    except Exception as exc:  # never kill the page
        banner, ok = f"Unexpected error: {exc}", False

    try:
        table, counter = _build_table(new_pending, can_edit, search, fcat,
                                      fregion)
        region_opts = asset_db.regions()
    except Exception as exc:
        return (_banner(str(exc), ok=False), "", None, None, None, False,
                {"display": "none"}, "New asset", [], *[dash.no_update] * 7)

    style = {"display": "block"} if new_open else {"display": "none"}
    title = "Edit asset" if new_editing else "New asset"
    return (table, counter, _banner(banner, ok), new_pending, new_editing,
            new_open, style, title, region_opts, *form_vals)
