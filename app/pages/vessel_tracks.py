"""
Vessel Tracker - Tracks.

Full-width dash-leaflet map for the reception-room display:

- All vessels from the track database plotted at their latest position as a
  large dot with a permanent name label; a column on the right lists the
  same vessels with last-seen age, status and destination.
- Clicking a dot, its label, or the name in the column selects the vessel
  and shows its 30-day track (both sources); hovering the track points
  shows time, speed and status. Clicking the same vessel again, or an
  empty spot on the map, returns to the all-vessels view.
- Data refreshes every 15 minutes (kiosk mode); the selection survives a
  refresh. The map viewport only re-fits on selection changes, not on the
  background refresh, so a viewer panning the map is not interrupted.
- Marker clicks do not bubble to the map (bubblingMouseEvents=False), so
  select and deselect cannot fire in the same click.
- The sidebar toggle triggers a delayed invalidateSize so the map claims
  the extra width after the collapse animation (0.18 s) finishes.

Base layer is plain OSM for now; the EMODnet/OpenSeaMap layer stack from
the Copernicus page follows later.
"""
from datetime import datetime, timezone

import dash
import dash_leaflet as dl
from dash import html, dcc, Input, Output, State, callback, ctx, clientside_callback

from app.engines import ais_db

dash.register_page(__name__, path="/vessel-tracker/tracks", name="Tracks",
                   category="Vessel Tracker", order=2)

MUTED = "#6b7280"
LINE = "#d1d5db"
TEAL = "#0f766e"

# nav_status -> marker colour
STATUS_COLORS = {0: "#059669", 8: "#059669",   # underway
                 1: "#d97706",                  # at anchor
                 5: "#2563eb",                  # moored
                 3: "#7c3aed", 4: "#7c3aed"}    # restricted / constrained
DEFAULT_COLOR = "#6b7280"

MAP_HEIGHT = "calc(100vh - 175px)"


def _age(ts):
    s = (datetime.now(timezone.utc) - ts).total_seconds()
    if s < 90:
        return "now"
    if s < 3600:
        return f"{int(s // 60)}m"
    if s < 172800:
        return f"{s / 3600:.0f}h"
    return f"{int(s // 86400)}d"


def _color(nav_status):
    return STATUS_COLORS.get(nav_status if nav_status is None else int(nav_status),
                             DEFAULT_COLOR) if nav_status is not None else DEFAULT_COLOR


def _vessel_markers(rows):
    """Large labelled dot per vessel (all-vessels view)."""
    out = []
    for mmsi, name, ts, lat, lon, sog, nav_status, dest, _vtype in rows:
        out.append(dl.CircleMarker(
            center=[lat, lon], radius=9,
            color="white", weight=2,
            fillColor=_color(nav_status), fillOpacity=0.95,
            bubblingMouseEvents=False, n_clicks=0,
            id={"type": "vtt-dot", "mmsi": str(mmsi)},
            children=dl.Tooltip(name, permanent=True, direction="right",
                                offset=[10, 0],
                                className="vtt-label"),
        ))
    return out


def _track_layer(mmsi, name, points):
    """Polyline + hoverable points for the selected vessel."""
    if not points:
        return [], None
    latlons = [[p[1], p[2]] for p in points]
    children = [
        dl.Polyline(positions=latlons, color=TEAL, weight=2.5,
                    opacity=0.85, interactive=False),
        # direction-of-travel arrows along the line (MarineTraffic-style);
        # follows point order, independent of the vessel's heading
        dl.PolylineDecorator(positions=latlons, patterns=[dict(
            offset="18px", repeat="70px",
            arrowHead=dict(pixelSize=9, polygon=True,
                           pathOptions=dict(color=TEAL, fillOpacity=0.9,
                                            weight=1, stroke=True)))]),
    ]
    for ts, lat, lon, sog, nav_status, source in points:
        tip = (f"{ts.strftime('%d-%m %H:%M')} UTC · "
               f"{f'{sog:.1f} kn' if sog is not None else '— kn'} · "
               f"{ais_db.nav_status_label(nav_status)} ({source})")
        children.append(dl.CircleMarker(
            center=[lat, lon], radius=3.5,
            color=_color(nav_status), fillColor=_color(nav_status),
            fillOpacity=0.9, weight=1,
            bubblingMouseEvents=False, interactive=True,
            children=dl.Tooltip(tip),
        ))
    # latest position: big labelled dot on top (clickable to deselect)
    last = points[-1]
    children.append(dl.CircleMarker(
        center=[last[1], last[2]], radius=9, color="white", weight=2,
        fillColor=_color(last[4]), fillOpacity=0.95,
        bubblingMouseEvents=False, n_clicks=0,
        id={"type": "vtt-dot", "mmsi": str(mmsi)},
        children=dl.Tooltip(name, permanent=True, direction="right",
                            offset=[10, 0], className="vtt-label"),
    ))
    bounds = [[min(p[0] for p in latlons), min(p[1] for p in latlons)],
              [max(p[0] for p in latlons), max(p[1] for p in latlons)]]
    return children, bounds


def _pad_bounds(bounds, pad=0.05):
    (a, b), (c, d) = bounds
    if abs(c - a) < 2 * pad and abs(d - b) < 2 * pad:   # near-zero area
        return [[a - pad, b - pad], [c + pad, d + pad]]
    return bounds


def _vessel_button(row, selected):
    mmsi, name, ts, lat, lon, sog, nav_status, dest, _vtype = row
    is_sel = str(mmsi) == (selected or "")
    sub = f"{_age(ts)} \u00b7 {ais_db.nav_status_label(nav_status)}"
    if dest:
        sub += f" \u00b7 {dest}"
    return html.Button(
        [html.Div([
            html.Span("\u25cf", style={"color": _color(nav_status),
                                        "marginRight": "7px"}),
            html.Span(name, style={"fontWeight": "600"}),
         ]),
         html.Div(sub, style={"color": MUTED, "fontSize": "0.72rem",
                              "marginLeft": "17px", "whiteSpace": "nowrap",
                              "overflow": "hidden", "textOverflow": "ellipsis"})],
        id={"type": "vtt-sel", "mmsi": str(mmsi)}, n_clicks=0,
        style={"display": "block", "width": "100%", "textAlign": "left",
               "padding": "6px 10px", "border": "none",
               "borderBottom": f"1px solid {LINE}",
               "borderLeft": f"3px solid {TEAL if is_sel else 'transparent'}",
               "background": "#f0fdfa" if is_sel else "white",
               "cursor": "pointer", "fontSize": "0.82rem"})


def _vessel_list(rows, selected):
    """Vessel column, dynamically grouped by vessel type (DSV, PLB, ...).
    Groups come straight from the data; typeless vessels fall under
    'Other'. Rows arrive name-sorted, so groups stay name-sorted too."""
    if not rows:
        return [html.Div("No vessels in the track database yet.",
                         style={"color": MUTED, "padding": "12px",
                                "fontSize": "0.85rem"})]
    groups = {}
    for row in rows:
        groups.setdefault(row[8] or "Other", []).append(row)
    ordered = sorted(k for k in groups if k != "Other")
    if "Other" in groups:
        ordered.append("Other")

    items = []
    for gname in ordered:
        items.append(html.Div(
            f"{gname} ({len(groups[gname])})",
            style={"padding": "5px 10px", "fontSize": "0.72rem",
                   "fontWeight": "700", "letterSpacing": "0.06em",
                   "textTransform": "uppercase", "color": TEAL,
                   "background": "#f0fdfa",
                   "borderBottom": f"1px solid {LINE}",
                   "position": "sticky", "top": "0"}))
        items.extend(_vessel_button(row, selected) for row in groups[gname])
    return items


def _chip(label, value, active, count=None):
    text = f"{label} ({count})" if count is not None else label
    return html.Button(
        text, n_clicks=0, id={"type": "vtt-tf", "val": value},
        style={"padding": "3px 12px", "borderRadius": "999px",
               "fontSize": "0.78rem", "cursor": "pointer",
               "border": f"1.5px solid {TEAL if active else LINE}",
               "background": TEAL if active else "white",
               "color": "white" if active else "#374151",
               "fontWeight": "600" if active else "400"})


def _type_chips(rows, typefilter):
    """Filter chips above the map, derived from the data (dynamic groups)."""
    counts = {}
    for r in rows:
        counts[r[8] or "Other"] = counts.get(r[8] or "Other", 0) + 1
    if len(counts) < 2:
        return []
    ordered = sorted(k for k in counts if k != "Other")
    if "Other" in counts:
        ordered.append("Other")
    chips = [_chip("All", "__all__", typefilter is None, sum(counts.values()))]
    chips += [_chip(t, t, typefilter == t, counts[t]) for t in ordered]
    return chips


layout = html.Div(className="full-width-page", children=[
    html.Div([
        html.H3("Tracks", style={"margin": "0 12px 0 0", "display": "inline"}),
        html.Span(id="vtt-subtitle", style={"color": MUTED, "fontSize": "0.85rem"}),
    ], style={"marginBottom": "8px"}),
    dcc.Interval(id="vtt-tick", interval=900_000, n_intervals=0),  # 15 min kiosk refresh
    dcc.Store(id="vtt-selected", data=None),
    dcc.Store(id="vtt-typefilter", data=None),
    html.Div(id="vtt-chips", style={"margin": "0 0 8px",
                                    "display": "flex", "gap": "6px",
                                    "flexWrap": "wrap"}),
    html.Div([
        html.Div(
            dl.Map(id="vtt-map", preferCanvas=True,
                   center=[30, 10], zoom=3, n_clicks=0,
                   style={"width": "100%", "height": MAP_HEIGHT,
                          "borderRadius": "8px", "border": f"1px solid {LINE}"},
                   children=[
                       dl.TileLayer(url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                                    attribution="© OpenStreetMap contributors"),
                       dl.LayerGroup(id="vtt-layer"),
                   ]),
            style={"flex": "1 1 auto", "minWidth": "0"}),
        html.Div([
            html.Div(id="vtt-count",
                     style={"padding": "8px 10px", "fontWeight": "600",
                            "borderBottom": f"2px solid {TEAL}",
                            "fontSize": "0.85rem", "background": "#f8fafc"}),
            html.Div(id="vtt-list", style={"overflowY": "auto",
                                           "height": f"calc({MAP_HEIGHT} - 36px)"}),
        ], style={"flex": "0 0 290px", "border": f"1px solid {LINE}",
                  "borderRadius": "8px", "overflow": "hidden",
                  "background": "white"}),
    ], style={"display": "flex", "gap": "14px", "alignItems": "stretch"}),
])


@callback(
    Output("vtt-layer", "children"),
    Output("vtt-list", "children"),
    Output("vtt-count", "children"),
    Output("vtt-subtitle", "children"),
    Output("vtt-map", "viewport"),
    Output("vtt-selected", "data"),
    Output("vtt-chips", "children"),
    Output("vtt-typefilter", "data"),
    Input("vtt-tick", "n_intervals"),
    Input("vtt-map", "n_clicks"),
    Input({"type": "vtt-dot", "mmsi": dash.ALL}, "n_clicks"),
    Input({"type": "vtt-sel", "mmsi": dash.ALL}, "n_clicks"),
    Input({"type": "vtt-tf", "val": dash.ALL}, "n_clicks"),
    State("vtt-selected", "data"),
    State("vtt-typefilter", "data"),
)
def _render(_tick, _map_clicks, _dots, _sels, _chips, selected, typefilter):
    trig = ctx.triggered_id
    clicked = bool(ctx.triggered) and bool(ctx.triggered[0].get("value"))
    is_refresh = trig in (None, "vtt-tick")

    filter_changed = False
    if (clicked and isinstance(trig, dict) and trig.get("type") == "vtt-tf"):
        val = trig.get("val")
        new_filter = None if val in ("__all__", typefilter) else val
        filter_changed = new_filter != typefilter
        typefilter = new_filter

    new_selected = _resolve_selection(trig, clicked, selected)

    try:
        all_rows = ais_db.latest_positions()
    except ais_db.AisDbError as exc:
        empty = html.Div(str(exc), style={"color": "#b91c1c", "padding": "12px",
                                          "fontSize": "0.85rem"})
        return ([], empty, "Vessels", "", dash.no_update, new_selected,
                [], typefilter)

    chips = _type_chips(all_rows, typefilter)
    rows = [r for r in all_rows
            if typefilter is None or (r[8] or "Other") == typefilter]
    if filter_changed:
        new_selected = None            # filterwissel = terug naar overzicht

    mmsis = {str(r[0]) for r in rows}
    if new_selected not in mmsis:
        new_selected = None

    subtitle = ("click a vessel for its 30-day track"
                if new_selected is None else "click the map or the vessel to go back")
    count = (f"Vessels ({len(rows)})" if typefilter is None
             else f"{typefilter} ({len(rows)} of {len(all_rows)})")
    viewport = dash.no_update

    if new_selected is None:
        layer = _vessel_markers(rows)
        # re-fit on initial load, deselect and filter change - not on refresh
        if rows and (trig is None or not is_refresh or filter_changed):
            bounds = _pad_bounds(
                [[min(r[3] for r in rows), min(r[4] for r in rows)],
                 [max(r[3] for r in rows), max(r[4] for r in rows)]])
            viewport = {"bounds": bounds, "transition": "flyToBounds",
                        "options": {"padding": [40, 40]}}
    else:
        mmsi = int(new_selected)
        name = next((r[1] for r in rows if str(r[0]) == new_selected), new_selected)
        points = ais_db.track(mmsi, days=30)
        layer, bounds = _track_layer(mmsi, name, points)
        if bounds is not None and not is_refresh:
            viewport = {"bounds": _pad_bounds(bounds),
                        "transition": "flyToBounds",
                        "options": {"padding": [40, 40]}}
        subtitle = (f"{name} — {len(points)} points, last 30 days · " + subtitle)

    return (layer, _vessel_list(rows, new_selected), count, subtitle,
            viewport, new_selected, chips, typefilter)


def _resolve_selection(trig, clicked, current):
    """Pure selection logic: toggle on vessel click, clear on map click,
    keep on refresh."""
    if not clicked:
        return current
    if trig == "vtt-map":
        return None
    if isinstance(trig, dict) and trig.get("type") in ("vtt-dot", "vtt-sel"):
        mmsi = trig.get("mmsi")
        return None if mmsi == current else mmsi
    return current


# After the sidebar collapse animation (0.18 s), tell Leaflet the container
# size changed so the map claims the full width.
clientside_callback(
    """
    function(n) {
        return new Promise(function(resolve) {
            setTimeout(function() { resolve(Date.now()); }, 300);
        });
    }
    """,
    Output("vtt-map", "invalidateSize"),
    Input("nav-toggle", "n_clicks"),
    prevent_initial_call=True,
)
