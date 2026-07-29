"""
Vessel Tracker - Track Animated.

Cinematic kiosk mode for the reception room. Looks like the Tracks page,
but instead of one selected vessel it runs a show:

- Click vessels (column or map dot) to toggle them into the playlist;
  the click order is the flight order and is shown as a number badge.
- Play: the map flies (birdseye zoom-out/in arc, ~4 s) to the first
  vessel and shows its 7-day track for 10 seconds, then flies to the
  next, looping endlessly after the last one.
- Stop returns to the overview of all vessels.

Implementation notes:
- All component ids use the `vta-` namespace. Reusing the Tracks page's
  `vtt-` pattern ids would make that page's callbacks fire on clicks
  here (pattern-matched inputs are app-wide), the same failure family as
  the phantom-input bug.
- The 60 s dwell is a dcc.Interval that only runs while playing; a
  separate 15-min interval keeps the vessel list fresh, and every hop
  re-queries the track, so the show never goes stale. Refresh ticks
  leave the viewport alone.
"""
from datetime import datetime, timezone

import dash
import dash_leaflet as dl
from dash import html, dcc, Input, Output, State, callback, ctx, clientside_callback

from app import buildinfo
from app.engines import ais_db, map_overlays, vessel_icon

dash.register_page(__name__, path="/vessel-tracker/animated", name="Track Animated",
                   category="Vessel Tracker", order=2.5)

MUTED = "#6b7280"
LINE = "#d1d5db"
TEAL = "#0f766e"
STATUS_COLORS = {0: "#059669", 8: "#059669", 1: "#d97706", 5: "#2563eb",
                 3: "#7c3aed", 4: "#7c3aed"}
DEFAULT_COLOR = "#6b7280"

MAP_HEIGHT = "calc(100vh - 175px)"
DWELL_SECONDS = 10
TRACK_DAYS = 7
FLY_SECONDS = 4


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
    return STATUS_COLORS.get(int(nav_status), DEFAULT_COLOR) \
        if nav_status is not None else DEFAULT_COLOR


def _pad_bounds(bounds, pad=0.05):
    (a, b), (c, d) = bounds
    if abs(c - a) < 2 * pad and abs(d - b) < 2 * pad:
        return [[a - pad, b - pad], [c + pad, d + pad]]
    return bounds


def _fly(bounds):
    return {"bounds": _pad_bounds(bounds), "transition": "flyToBounds",
            "options": {"padding": [60, 60], "duration": FLY_SECONDS}}


def _overview_markers(rows, selected):
    """Ship-shaped markers; playlist members get a teal glow ring.
    Size scales with vessel length, rotation follows heading/COG."""
    out = []
    for (mmsi, name, ts, lat, lon, sog, nav_status, dest, _vtype,
         heading, cog, length_m) in rows:
        in_sel = str(mmsi) in selected
        html_icon, size, anchor = vessel_icon.ship_div(
            _color(nav_status), heading, cog, length_m, selected=in_sel)
        out.append(dl.DivMarker(
            position=[lat, lon],
            iconOptions=dict(html=html_icon, className="",
                             iconSize=size, iconAnchor=anchor),
            bubblingMouseEvents=False, n_clicks=0,
            id={"type": "vta-dot", "mmsi": str(mmsi)},
            children=dl.Tooltip(name, permanent=True, direction="right",
                                offset=[size[0] / 2 + 2, 0],
                                className="vtt-label"),
        ))
    return out


def _show_layer(mmsi, name, points, latest_row):
    """7-day track + arrows for the spotlighted vessel; falls back to the
    latest position when the window holds no points."""
    if not points:
        if latest_row is None:
            return [], None
        lat, lon, nav_status = latest_row[3], latest_row[4], latest_row[6]
        html_icon, size, anchor = vessel_icon.ship_div(
            _color(nav_status), latest_row[9], latest_row[10], latest_row[11])
        marker = dl.DivMarker(
            position=[lat, lon],
            iconOptions=dict(html=html_icon, className="",
                             iconSize=size, iconAnchor=anchor),
            interactive=False,
            children=dl.Tooltip(name, permanent=True, direction="right",
                                offset=[size[0] / 2 + 2, 0],
                                className="vtt-label"))
        return [marker], [[lat, lon], [lat, lon]]

    latlons = [[p[1], p[2]] for p in points]
    children = [
        dl.Polyline(positions=latlons, color=TEAL, weight=2.5,
                    opacity=0.85, interactive=False),
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
            fillOpacity=0.9, weight=1, bubblingMouseEvents=False,
            children=dl.Tooltip(tip)))
    last = points[-1]
    _hdg = latest_row[9] if latest_row else None
    _cg = latest_row[10] if latest_row else None
    _ln = latest_row[11] if latest_row else None
    html_icon, size, anchor = vessel_icon.ship_div(
        _color(last[4]), _hdg, _cg, _ln)
    children.append(dl.DivMarker(
        position=[last[1], last[2]],
        iconOptions=dict(html=html_icon, className="",
                         iconSize=size, iconAnchor=anchor),
        interactive=False,
        children=dl.Tooltip(name, permanent=True, direction="right",
                            offset=[size[0] / 2 + 2, 0],
                            className="vtt-label")))
    bounds = [[min(p[0] for p in latlons), min(p[1] for p in latlons)],
              [max(p[0] for p in latlons), max(p[1] for p in latlons)]]
    return children, bounds


def _vessel_button(row, selected):
    (mmsi, name, ts, lat, lon, sog, nav_status, dest, _vtype,
     _hdg, _cog, _len) = row
    try:
        pos = selected.index(str(mmsi)) + 1
    except ValueError:
        pos = None
    badge = html.Span(
        str(pos) if pos else "+",
        style={"display": "inline-block", "minWidth": "18px", "height": "18px",
               "lineHeight": "18px", "textAlign": "center",
               "borderRadius": "50%", "marginRight": "7px",
               "fontSize": "0.68rem", "fontWeight": "700",
               "background": TEAL if pos else "#e5e7eb",
               "color": "white" if pos else MUTED})
    sub = f"{_age(ts)} · {ais_db.nav_status_label(nav_status)}"
    if dest:
        sub += f" · {dest}"
    return html.Button(
        [html.Div([badge, html.Span(name, style={"fontWeight": "600"})]),
         html.Div(sub, style={"color": MUTED, "fontSize": "0.72rem",
                              "marginLeft": "25px", "whiteSpace": "nowrap",
                              "overflow": "hidden", "textOverflow": "ellipsis"})],
        id={"type": "vta-sel", "mmsi": str(mmsi)}, n_clicks=0,
        style={"display": "block", "width": "100%", "textAlign": "left",
               "padding": "6px 10px", "border": "none",
               "borderBottom": f"1px solid {LINE}",
               "borderLeft": f"3px solid {TEAL if pos else 'transparent'}",
               "background": "#f0fdfa" if pos else "white",
               "cursor": "pointer", "fontSize": "0.82rem"})


def _vessel_list(rows, selected, collapsed):
    collapsed = set(collapsed or [])
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
        is_collapsed = gname in collapsed
        marker = "\u25b8" if is_collapsed else "\u25be"
        items.append(html.Button(
            [html.Span(marker, style={"marginRight": "6px",
                                      "fontSize": "0.65rem"}),
             f"{gname} ({len(groups[gname])})"],
            n_clicks=0, id={"type": "vta-grp", "name": gname},
            style={"display": "block", "width": "100%", "textAlign": "left",
                   "padding": "5px 10px", "fontSize": "0.72rem",
                   "fontWeight": "700", "letterSpacing": "0.06em",
                   "textTransform": "uppercase", "color": TEAL,
                   "background": "#f0fdfa", "cursor": "pointer",
                   "border": "none", "borderBottom": f"1px solid {LINE}",
                   "position": "sticky", "top": "0", "zIndex": "1"}))
        if not is_collapsed:
            items.extend(_vessel_button(row, selected)
                         for row in groups[gname])
    return items


def _legend():
    """Compact asset legend, floating bottom-left on the map (shared look
    with the Tracks page)."""
    def swatch(color, shape, dashed):
        if shape == "square":
            st = {"width": "10px", "height": "10px", "background": color,
                  "border": "1px solid white"}
        elif shape == "triangle":
            st = {"width": "0", "height": "0",
                  "borderLeft": "5px solid transparent",
                  "borderRight": "5px solid transparent",
                  "borderBottom": f"10px solid {color}"}
        elif shape == "line":
            st = {"width": "16px", "height": "0",
                  "borderTop": f"2.5px {'dashed' if dashed else 'solid'} {color}"}
        elif shape == "polygon":
            st = {"width": "12px", "height": "9px",
                  "background": color + "26",
                  "border": f"1.5px solid {color}"}
        else:
            st = {"width": "9px", "height": "9px", "borderRadius": "50%",
                  "background": color, "border": "1px solid white"}
        return html.Span(style={**st, "display": "inline-block",
                                "marginRight": "6px", "verticalAlign": "middle"})

    def ship_swatch(color):
        # ship outline as pure CSS (clip-path pentagon: pointed bow)
        return html.Span(style={
            "display": "inline-block", "width": "9px", "height": "15px",
            "background": color,
            "clipPath": "polygon(50% 0, 100% 28%, 100% 100%, 0 100%, 0 28%)",
            "marginRight": "6px", "verticalAlign": "middle",
            "outline": "1px solid white"})

    vessel_rows = [html.Div("Vessels",
                            style={"fontWeight": "700", "marginTop": "6px",
                                   "borderTop": f"1px solid {LINE}",
                                   "paddingTop": "5px"})]
    vessel_rows += [
        html.Div([ship_swatch(c),
                  html.Span(lbl, style={"verticalAlign": "middle"})],
                 style={"whiteSpace": "nowrap", "lineHeight": "1.5"})
        for lbl, c in (("Underway", "#059669"), ("At anchor", "#d97706"),
                       ("Moored", "#2563eb"),
                       ("Restricted / constrained", "#7c3aed"),
                       ("Other / unknown", "#6b7280"))]

    rows = [html.Div([swatch(c, shape, dashed),
                      html.Span(label, style={"verticalAlign": "middle"})],
                     style={"whiteSpace": "nowrap", "lineHeight": "1.5"})
            for label, c, shape, dashed in map_overlays.legend_items()]
    return html.Div(rows + vessel_rows, style={
        "position": "absolute", "bottom": "12px", "left": "12px",
        "zIndex": "1000", "background": "rgba(255,255,255,0.88)",
        "border": f"1px solid {LINE}", "borderRadius": "8px",
        "padding": "8px 12px", "fontSize": "0.72rem", "color": "#374151"})


_CTRL = {"padding": "5px 14px", "borderRadius": "6px", "fontSize": "0.82rem",
         "cursor": "pointer", "border": f"1px solid {LINE}",
         "background": "white", "fontWeight": "600"}

layout = html.Div(className="full-width-page", children=[
    html.Div([
        html.H3("Track Animated", style={"margin": "0 12px 0 0",
                                         "display": "inline"}),
        html.Span(id="vta-status", style={"color": MUTED,
                                          "fontSize": "0.85rem"}),
    ], style={"marginBottom": "8px"}),
    dcc.Interval(id="vta-step", interval=DWELL_SECONDS * 1000,
                 n_intervals=0, disabled=True),
    dcc.Interval(id="vta-refresh", interval=900_000, n_intervals=0),
    dcc.Store(id="vta-selected", data=[]),
    dcc.Store(id="vta-playing", data=False),
    dcc.Store(id="vta-index", data=0),
    dcc.Store(id="vta-collapsed", data=[]),
    dcc.Store(id="vta-overlays", data=map_overlays.default_state()),
    dcc.Store(id="vta-mybuild", data=buildinfo.BUILD_ID),
    dcc.Store(id="vta-srvbuild", data=None),
    dcc.Store(id="vta-reload-sink", data=None),
    html.Div([
        html.Div([
            dl.Map(id="vta-map", preferCanvas=True,
                   center=[30, 10], zoom=3, n_clicks=0,
                   style={"width": "100%", "height": MAP_HEIGHT,
                          "borderRadius": "8px", "border": f"1px solid {LINE}"},
                   children=[
                       dl.TileLayer(url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                                    attribution="© OpenStreetMap contributors"),
                       *[dl.LayerGroup(id={"type": "vta-ovl-layer",
                                              "key": o["key"]})
                         for o in map_overlays.OVERLAYS],
                       dl.LayerGroup(id="vta-layer"),
                   ]),
            _legend()],
            style={"flex": "1 1 auto", "minWidth": "0",
                   "position": "relative"}),
        html.Div([
            html.Div([
                html.Button("\u25b6 Play", id="vta-play", n_clicks=0,
                            style={**_CTRL, "color": TEAL,
                                   "borderColor": TEAL, "marginRight": "6px"}),
                html.Button("\u25a0 Stop", id="vta-stop", n_clicks=0,
                            style=_CTRL),
                *[html.Button(map_overlays.chip_label(o), n_clicks=0,
                              id={"type": "vta-ovl-chip", "key": o["key"]},
                              title=o.get("hint", ""),
                              style={"marginLeft": "6px"})
                  for o in map_overlays.OVERLAYS],
            ], style={"padding": "8px 10px", "background": "#f8fafc",
                      "borderBottom": f"2px solid {TEAL}"}),
            html.Div(id="vta-list", style={"overflowY": "auto",
                                           "height": f"calc({MAP_HEIGHT} - 52px)"}),
        ], style={"flex": "0 0 290px", "border": f"1px solid {LINE}",
                  "borderRadius": "8px", "overflow": "hidden",
                  "background": "white"}),
    ], style={"display": "flex", "gap": "14px", "alignItems": "stretch"}),
])


@callback(
    Output("vta-layer", "children"),
    Output("vta-list", "children"),
    Output("vta-status", "children"),
    Output("vta-map", "viewport"),
    Output("vta-selected", "data"),
    Output("vta-playing", "data"),
    Output("vta-index", "data"),
    Output("vta-step", "disabled"),
    Output("vta-collapsed", "data"),
    Input("vta-play", "n_clicks"),
    Input("vta-stop", "n_clicks"),
    Input("vta-step", "n_intervals"),
    Input("vta-refresh", "n_intervals"),
    Input({"type": "vta-sel", "mmsi": dash.ALL}, "n_clicks"),
    Input({"type": "vta-dot", "mmsi": dash.ALL}, "n_clicks"),
    Input({"type": "vta-grp", "name": dash.ALL}, "n_clicks"),
    State("vta-selected", "data"),
    State("vta-playing", "data"),
    State("vta-index", "data"),
    State("vta-collapsed", "data"),
)
def _render(_p, _s, _step, _ref, _sels, _dots, _grps,
            selected, playing, index, collapsed):
    trig = ctx.triggered_id
    clicked = bool(ctx.triggered) and bool(ctx.triggered[0].get("value"))
    selected = list(selected or [])
    collapsed = list(collapsed or [])
    playing = bool(playing)
    index = int(index or 0)
    move = False                     # does this event trigger a flight?
    notice = None

    if clicked and isinstance(trig, dict):
        kind = trig.get("type")
        if kind in ("vta-sel", "vta-dot"):
            m = trig["mmsi"]
            if m in selected:
                selected.remove(m)
            else:
                selected.append(m)
            if playing and not selected:
                playing = False
            index = min(index, max(len(selected) - 1, 0))
        elif kind == "vta-grp":
            g = trig.get("name")
            collapsed = ([c for c in collapsed if c != g] if g in collapsed
                         else collapsed + [g])
    elif clicked and trig == "vta-play":
        if selected:
            playing, index, move = True, 0, True
        else:
            notice = "Select at least one vessel first (click dots or names)."
    elif clicked and trig == "vta-stop":
        playing, move = False, True   # move = refit to overview
    elif clicked and trig == "vta-step" and playing and selected:
        index = (index + 1) % len(selected)
        move = True

    try:
        rows = ais_db.latest_positions()
    except ais_db.AisDbError as exc:
        err = html.Div(str(exc), style={"color": "#b91c1c", "padding": "12px",
                                        "fontSize": "0.85rem"})
        return ([], err, "", dash.no_update, selected, False, 0, True,
                collapsed)

    by_mmsi = {str(r[0]): r for r in rows}
    selected = [m for m in selected if m in by_mmsi]   # drop vanished vessels
    if playing and not selected:
        playing = False
    if selected:
        index %= len(selected)

    viewport = dash.no_update
    if playing:
        m = selected[index]
        row = by_mmsi[m]
        name = row[1]
        points = ais_db.track(int(m), days=TRACK_DAYS)
        layer, bounds = _show_layer(int(m), name, points, row)
        if move and bounds is not None:
            viewport = _fly(bounds)
        status = (f"\u25b6 {index + 1}/{len(selected)} · {name} — "
                  f"{TRACK_DAYS}-day track · next in {DWELL_SECONDS} s")
    else:
        layer = _overview_markers(rows, selected)
        if rows and (trig is None or move):
            viewport = _fly(
                [[min(r[3] for r in rows), min(r[4] for r in rows)],
                 [max(r[3] for r in rows), max(r[4] for r in rows)]])
        status = notice or (f"{len(selected)} of {len(rows)} vessels selected"
                            f" — click vessels, then \u25b6 Play")

    return (layer, _vessel_list(rows, selected, collapsed), status, viewport,
            selected, playing, index, not playing, collapsed)


clientside_callback(
    """
    function(n) {
        return new Promise(function(resolve) {
            setTimeout(function() { resolve(Date.now()); }, 300);
        });
    }
    """,
    Output("vta-map", "invalidateSize"),
    Input("nav-toggle", "n_clicks"),
    prevent_initial_call=True,
)


# ---- kiosk auto-reload after deploys ----------------------------------------
@callback(Output("vta-srvbuild", "data"),
          Input("vta-refresh", "n_intervals"))
def _push_build(_n):
    return buildinfo.BUILD_ID


clientside_callback(
    """
    function(srv, mine) {
        if (srv && mine && srv !== mine) { window.location.reload(); }
        return window.dash_clientside.no_update;
    }
    """,
    Output("vta-reload-sink", "data"),
    Input("vta-srvbuild", "data"),
    State("vta-mybuild", "data"),
    prevent_initial_call=True,
)


# ---- map overlays (registry-driven; see app/engines/map_overlays.py) --------
def _overlay_chip_style(on):
    return {"padding": "3px 12px", "borderRadius": "999px",
            "fontSize": "0.78rem", "cursor": "pointer",
            "border": f"1.5px solid {'#b45309' if on else LINE}",
            "background": "#b45309" if on else "white",
            "color": "white" if on else "#374151",
            "fontWeight": "600" if on else "400"}


@callback(
    Output({"type": "vta-ovl-layer", "key": dash.ALL}, "children"),
    Output({"type": "vta-ovl-chip", "key": dash.ALL}, "style"),
    Output({"type": "vta-ovl-chip", "key": dash.ALL}, "children"),
    Output("vta-overlays", "data"),
    Input({"type": "vta-ovl-chip", "key": dash.ALL}, "n_clicks"),
    State("vta-overlays", "data"),
)
def _overlays(_clicks, state):
    state = {**map_overlays.default_state(), **(state or {})}
    trig = ctx.triggered_id
    if (ctx.triggered and ctx.triggered[0].get("value")
            and isinstance(trig, dict) and trig.get("type") == "vta-ovl-chip"):
        k = trig.get("key")
        state[k] = not state.get(k, False)
    layers, styles, labels = [], [], []
    for o in map_overlays.OVERLAYS:          # zelfde volgorde als de layout
        on = state.get(o["key"], False)
        layers.append(map_overlays.build_layer(o) if on else [])
        styles.append(_overlay_chip_style(on))
        labels.append(map_overlays.chip_label(o))
    return layers, styles, labels, state
