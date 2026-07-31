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

from app import buildinfo
from app.engines import ais_db, map_overlays, vessel_icon

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
    """Ship-shaped marker per vessel: size scales with vessel length,
    rotation follows true heading (fallback COG)."""
    out = []
    for (mmsi, name, ts, lat, lon, sog, nav_status, dest, _vtype,
         heading, cog, length_m) in rows:
        html_icon, size, anchor = vessel_icon.ship_div(
            _color(nav_status), heading, cog, length_m)
        out.append(dl.DivMarker(
            position=[lat, lon],
            iconOptions=dict(html=html_icon, className="",
                             iconSize=size, iconAnchor=anchor),
            bubblingMouseEvents=False, n_clicks=0,
            id={"type": "vtt-dot", "mmsi": str(mmsi)},
            children=dl.Tooltip(name, permanent=True, direction="right",
                                offset=[size[0] / 2 + 2, 0],
                                className="vtt-label"),
        ))
    return out


def _track_layer(mmsi, name, points, _hdg=None, _cog=None, _len=None):
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
    # latest position: ship icon on top (clickable to deselect); heading
    # and length come from `latest` via the caller
    last = points[-1]
    html_icon, size, anchor = vessel_icon.ship_div(
        _color(last[4]), _hdg, _cog, _len)
    children.append(dl.DivMarker(
        position=[last[1], last[2]],
        iconOptions=dict(html=html_icon, className="",
                         iconSize=size, iconAnchor=anchor),
        bubblingMouseEvents=False, n_clicks=0,
        id={"type": "vtt-dot", "mmsi": str(mmsi)},
        children=dl.Tooltip(name, permanent=True, direction="right",
                            offset=[size[0] / 2 + 2, 0],
                            className="vtt-label"),
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
    (mmsi, name, ts, lat, lon, sog, nav_status, dest, _vtype,
     _hdg, _cog, _len) = row
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


def _vessel_list(rows, selected, collapsed=None):
    """Vessel column, dynamically grouped by vessel type (DSV, PLB, ...).
    Group headers are accordion toggles; collapsed groups (stored per group
    name) survive the 15-min kiosk refresh. Typeless vessels fall under
    'Other'; rows arrive name-sorted, so groups stay name-sorted too."""
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
        marker = "\u25b8" if is_collapsed else "\u25be"     # > / v
        items.append(html.Button(
            [html.Span(marker, style={"marginRight": "6px",
                                      "fontSize": "0.65rem"}),
             f"{gname} ({len(groups[gname])})"],
            n_clicks=0, id={"type": "vtt-grp", "name": gname},
            title="Click to collapse / expand this group",
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


_NAV_LABELS = {0: "Underway (engine)", 1: "At anchor", 2: "Not under command",
               3: "Restricted manoeuvrability", 4: "Constrained by draught",
               5: "Moored", 6: "Aground", 7: "Fishing",
               8: "Underway (sailing)", 15: "Undefined"}


# Destination hyperlink target. VesselFinder's public /ports page is
# searchable by UN/LOCODE; {loc} is substituted with the vessel's reported
# destination LOCODE. Change this single line to point elsewhere if needed.
PORT_LINK_TEMPLATE = "https://www.vesselfinder.com/ports/{loc}"

_INFO_CARD_H = 330       # vaste max-hoogte van de info-card (px)


def _looks_like_locode(dest):
    """AIS destination is a UN/LOCODE when it's 5 chars, letters, first two
    a country code. Free-text destinations (e.g. 'ABERDEEN') are not linked."""
    if not dest:
        return False
    d = dest.strip().upper()
    return len(d) == 5 and d.isalpha()


def _info_row(label, value):
    return html.Div([
        html.Span(label, style={"color": "#64748b", "fontSize": "0.64rem",
                                "flex": "0 0 100px"}),
        html.Span(value, style={"fontSize": "0.68rem", "fontWeight": "600",
                                "color": "#0f172a"}),
    ], style={"display": "flex", "alignItems": "baseline", "gap": "6px",
              "padding": "1px 0"})


def _fmt_age(ts):
    if ts is None:
        return "\u2014"
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    secs = int((now - ts).total_seconds())
    if secs < 90:
        return f"{secs}s ago"
    if secs < 5400:
        return f"{secs // 60} min ago"
    if secs < 172800:
        return f"{secs // 3600} h ago"
    return f"{secs // 86400} d ago"


def _destination_value(dest):
    """Plain text, or a hyperlink to the VesselFinder port page when the
    destination is a UN/LOCODE."""
    if not dest:
        return "\u2014"
    if _looks_like_locode(dest):
        return html.A(dest,
                      href=PORT_LINK_TEMPLATE.format(loc=dest.strip().upper()),
                      target="_blank", rel="noopener noreferrer",
                      style={"color": TEAL, "textDecoration": "underline",
                             "cursor": "pointer"})
    return dest


def _info_card(info):
    """SeaVantage-style latest-AIS card, shown above the legend when a
    vessel is selected."""
    if not info:
        return {"display": "none"}, []
    def num(v, unit="", dec=0):
        if v is None:
            return "\u2014"
        return (f"{v:.{dec}f}{unit}" if dec else f"{int(round(v))}{unit}")
    nav = _NAV_LABELS.get(info.get("nav_status"), "\u2014")
    rows = [
        _info_row("Navigational status", nav),
        _info_row("Position received", _fmt_age(info.get("ts"))),
        _info_row("Latitude / Longitude",
                  f"{info['lat']:.4f}, {info['lon']:.4f}"
                  if info.get("lat") is not None else "\u2014"),
        _info_row("Speed", num(info.get("sog"), " kn", 1)),
        _info_row("Course", num(info.get("cog"), " \u00b0")),
        _info_row("True heading", num(info.get("heading"), " \u00b0")),
        _info_row("Draught", num(info.get("draught"), " m", 1)),
        _info_row("Destination", _destination_value(info.get("destination"))),
        _info_row("Reported ETA", info.get("eta") or "\u2014"),
        _info_row("Call sign", info.get("callsign") or "\u2014"),
        _info_row("Type", info.get("vessel_type") or "\u2014"),
    ]
    dims = None
    if info.get("length_m") and info.get("beam_m"):
        dims = f"{info['length_m']:.0f} \u00d7 {info['beam_m']:.0f} m"
    if dims:
        rows.append(_info_row("Dimensions", dims))
    if info.get("imo"):
        rows.append(_info_row("IMO", str(info["imo"])))

    style = {"position": "absolute", "right": "10px", "bottom": "10px",
             "zIndex": 1000, "background": "rgba(255,255,255,0.97)",
             "border": f"1px solid {LINE}", "borderRadius": "8px",
             "padding": "8px 11px", "width": "248px",
             "boxShadow": "0 2px 10px rgba(0,0,0,0.18)",
             "maxHeight": f"{_INFO_CARD_H}px", "overflowY": "auto"}
    header = html.Div([
        html.Span("Latest AIS information",
                  style={"fontWeight": "700", "fontSize": "0.74rem",
                         "flex": "1 1 auto"}),
    ], style={"display": "flex", "alignItems": "center",
              "borderBottom": f"1px solid {LINE}", "paddingBottom": "4px",
              "marginBottom": "3px"})
    name = html.Div(info.get("name", ""),
                    style={"fontWeight": "700", "fontSize": "0.8rem",
                           "color": TEAL, "margin": "1px 0 4px"})
    return style, [header, name, *rows]


def _legend():
    """Compact asset legend, floating bottom-left on the map."""
    def swatch(color, shape, dashed):
        if shape == "square":
            st = {"width": "10px", "height": "10px", "background": color,
                  "border": "1px solid white"}
        elif shape == "triangle":
            st = {"width": "0", "height": "0",
                  "borderLeft": "5px solid transparent",
                  "borderRight": "5px solid transparent",
                  "borderBottom": f"10px solid {color}"}
        elif shape == "pentagon":
            st = {"width": "11px", "height": "11px", "background": color,
                  "clipPath":
                  "polygon(50% 0, 100% 38%, 82% 100%, 18% 100%, 0 38%)"}
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


layout = html.Div(className="full-width-page", children=[
    html.Div([
        html.H3("Tracks", style={"margin": "0 12px 0 0", "display": "inline"}),
        html.Span(id="vtt-subtitle", style={"color": MUTED, "fontSize": "0.85rem"}),
    ], style={"marginBottom": "8px"}),
    dcc.Interval(id="vtt-tick", interval=900_000, n_intervals=0),  # 15 min kiosk refresh
    dcc.Store(id="vtt-selected", data=None),
    dcc.Store(id="vtt-typefilter", data=None),
    dcc.Store(id="vtt-collapsed", data=[]),
    dcc.Store(id="vtt-overlays", data=map_overlays.default_state()),
    dcc.Store(id="vtt-mybuild", data=buildinfo.BUILD_ID),
    dcc.Store(id="vtt-srvbuild", data=None),
    dcc.Store(id="vtt-reload-sink", data=None),
    html.Div([
        html.Div([html.Button(map_overlays.chip_label(o), n_clicks=0,
                              id={"type": "vtt-ovl-chip", "key": o["key"]},
                              title=o.get("hint", ""))
                  for o in map_overlays.OVERLAYS],
                 style={"display": "flex", "gap": "6px", "flexWrap": "wrap"}),
        html.Div(id="vtt-chips",
                 style={"display": "flex", "gap": "6px", "flexWrap": "wrap",
                        "marginTop": "6px"}),
    ], style={"margin": "0 0 8px"}),
    html.Div([
        html.Div([
            dl.Map(id="vtt-map", preferCanvas=True,
                   center=[30, 10], zoom=3, n_clicks=0,
                   style={"width": "100%", "height": MAP_HEIGHT,
                          "borderRadius": "8px", "border": f"1px solid {LINE}"},
                   children=[
                       dl.TileLayer(url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                                    attribution="© OpenStreetMap contributors"),
                       *[dl.LayerGroup(id={"type": "vtt-ovl-layer",
                                              "key": o["key"]})
                         for o in map_overlays.OVERLAYS],
                       dl.LayerGroup(id="vtt-layer"),
                   ]),
            html.Div(id="vtt-info", style={"display": "none"}),
            html.Button("\u2715", id="vtt-info-close", n_clicks=0,
                        title="Close",
                        style={"display": "none"}),
            _legend()],
            style={"flex": "1 1 auto", "minWidth": "0",
                   "position": "relative"}),
        html.Button("\u25b8", id="vtt-col-toggle", n_clicks=0,
                    title="Show vessel list",
                    style={"display": "none"}),
        html.Div(id="vtt-col", children=[
            html.Div([
                html.Div(id="vtt-count", style={"fontWeight": "600",
                         "fontSize": "0.85rem", "flex": "1 1 auto"}),
                html.Button("\u25be", id="vtt-col-toggle2", n_clicks=0,
                            title="Hide vessel list",
                            style={"border": "none", "background": "none",
                                   "cursor": "pointer", "fontSize": "0.8rem",
                                   "color": TEAL, "padding": "0 4px"}),
            ], style={"display": "flex", "alignItems": "center",
                      "padding": "8px 10px", "borderBottom": f"2px solid {TEAL}",
                      "background": "#f8fafc"}),
            dcc.Input(id="vtt-search", value="", debounce=False, type="text",
                      placeholder="Filter by name\u2026",
                      style={"width": "100%", "boxSizing": "border-box",
                             "padding": "6px 10px", "fontSize": "0.8rem",
                             "border": "none",
                             "borderBottom": f"1px solid {LINE}"}),
            html.Div(id="vtt-list", style={"overflowY": "auto",
                     "height": f"calc({MAP_HEIGHT} - 72px)"}),
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
    Output("vtt-collapsed", "data"),
    Output("vtt-col", "style"),
    Output("vtt-col-toggle", "style"),
    Output("vtt-info", "style"),
    Output("vtt-info", "children"),
    Output("vtt-info-close", "style"),
    Input("vtt-tick", "n_intervals"),
    Input("vtt-search", "value"),
    Input("vtt-col-toggle", "n_clicks"),
    Input("vtt-col-toggle2", "n_clicks"),
    Input("vtt-map", "n_clicks"),
    Input("vtt-info-close", "n_clicks"),
    Input({"type": "vtt-dot", "mmsi": dash.ALL}, "n_clicks"),
    Input({"type": "vtt-sel", "mmsi": dash.ALL}, "n_clicks"),
    Input({"type": "vtt-tf", "val": dash.ALL}, "n_clicks"),
    Input({"type": "vtt-grp", "name": dash.ALL}, "n_clicks"),
    State("vtt-selected", "data"),
    State("vtt-typefilter", "data"),
    State("vtt-collapsed", "data"),
    State("vtt-col", "style"),
)
def _render(_tick, search, _colt, _colt2, _map_clicks, _infoclose, _dots,
            _sels, _chips, _grps, selected, typefilter, collapsed, col_style):
    trig = ctx.triggered_id
    clicked = bool(ctx.triggered) and bool(ctx.triggered[0].get("value"))
    is_refresh = trig in (None, "vtt-tick")

    # vessel-column collapse (mirrors the main nav toggle behaviour)
    col_hidden = bool((col_style or {}).get("display") == "none")
    if trig in ("vtt-col-toggle", "vtt-col-toggle2"):
        col_hidden = not col_hidden
    base_col_style = {"flex": "0 0 290px", "border": f"1px solid {LINE}",
                      "borderRadius": "8px", "overflow": "hidden",
                      "background": "white"}
    col_style_out = ({**base_col_style, "display": "none"} if col_hidden
                     else base_col_style)
    reopen_style = ({"padding": "6px 8px", "cursor": "pointer",
                     "border": f"1px solid {LINE}", "borderRadius": "6px",
                     "background": "white", "color": TEAL, "fontWeight": "700",
                     "alignSelf": "flex-start"} if col_hidden
                    else {"display": "none"})

    collapsed = list(collapsed or [])
    if (clicked and isinstance(trig, dict) and trig.get("type") == "vtt-grp"):
        g = trig.get("name")
        collapsed = ([c for c in collapsed if c != g] if g in collapsed
                     else collapsed + [g])

    filter_changed = False
    if (clicked and isinstance(trig, dict) and trig.get("type") == "vtt-tf"):
        val = trig.get("val")
        new_filter = None if val in ("__all__", typefilter) else val
        filter_changed = new_filter != typefilter
        typefilter = new_filter

    if trig == "vtt-info-close":
        new_selected = None
    else:
        new_selected = _resolve_selection(trig, clicked, selected)

    try:
        all_rows = ais_db.latest_positions()
    except ais_db.AisDbError as exc:
        empty = html.Div(str(exc), style={"color": "#b91c1c", "padding": "12px",
                                          "fontSize": "0.85rem"})
        return ([], empty, "Vessels", "", dash.no_update, new_selected,
                [], typefilter, collapsed, col_style_out, reopen_style,
                {"display": "none"}, [], {"display": "none"})

    chips = _type_chips(all_rows, typefilter)
    rows = [r for r in all_rows
            if typefilter is None or (r[8] or "Other") == typefilter]
    q = (search or "").strip().lower()
    if q:
        rows = [r for r in rows if q in (r[1] or "").lower()]
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
        sel_row = next((r for r in rows if str(r[0]) == new_selected), None)
        hdg, cg, ln = ((sel_row[9], sel_row[10], sel_row[11])
                       if sel_row else (None, None, None))
        layer, bounds = _track_layer(mmsi, name, points, hdg, cg, ln)
        if bounds is not None and not is_refresh:
            viewport = {"bounds": _pad_bounds(bounds),
                        "transition": "flyToBounds",
                        "options": {"padding": [40, 40]}}
        subtitle = (f"{name} — {len(points)} points, last 30 days · " + subtitle)

    if new_selected:
        try:
            info = ais_db.latest_info(int(new_selected))
        except (ais_db.AisDbError, ValueError, Exception):
            info = None
        info_style, info_children = _info_card(info)
    else:
        info_style, info_children = {"display": "none"}, []
    # card-top zit op bottom(10) + hoogte(330) = 340px vanaf de kaart-onderkant.
    # Sluitknop net binnen de rechterbovenhoek van de card.
    close_style = ({"position": "absolute", "right": "16px",
                    "bottom": f"{10 + _INFO_CARD_H - 24}px", "zIndex": 1001,
                    "border": "none", "background": "white",
                    "cursor": "pointer", "color": "#94a3b8",
                    "fontSize": "0.78rem", "borderRadius": "4px",
                    "padding": "1px 5px",
                    "boxShadow": "0 1px 4px rgba(0,0,0,0.2)"}
                   if info_style.get("display") != "none"
                   else {"display": "none"})
    return (layer, _vessel_list(rows, new_selected, collapsed), count,
            subtitle, viewport, new_selected, chips, typefilter, collapsed,
            col_style_out, reopen_style, info_style, info_children, close_style)


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


# ---- kiosk auto-reload after deploys ----------------------------------------
@callback(Output("vtt-srvbuild", "data"),
          Input("vtt-tick", "n_intervals"))
def _push_build(_n):
    return buildinfo.BUILD_ID


clientside_callback(
    """
    function(srv, mine) {
        if (srv && mine && srv !== mine) { window.location.reload(); }
        return window.dash_clientside.no_update;
    }
    """,
    Output("vtt-reload-sink", "data"),
    Input("vtt-srvbuild", "data"),
    State("vtt-mybuild", "data"),
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
    Output({"type": "vtt-ovl-layer", "key": dash.ALL}, "children"),
    Output({"type": "vtt-ovl-chip", "key": dash.ALL}, "style"),
    Output({"type": "vtt-ovl-chip", "key": dash.ALL}, "children"),
    Output("vtt-overlays", "data"),
    Input({"type": "vtt-ovl-chip", "key": dash.ALL}, "n_clicks"),
    State("vtt-overlays", "data"),
)
def _overlays(_clicks, state):
    state = {**map_overlays.default_state(), **(state or {})}
    trig = ctx.triggered_id
    if (ctx.triggered and ctx.triggered[0].get("value")
            and isinstance(trig, dict) and trig.get("type") == "vtt-ovl-chip"):
        k = trig.get("key")
        state[k] = not state.get(k, False)
    layers, styles, labels = [], [], []
    for o in map_overlays.OVERLAYS:          # zelfde volgorde als de layout
        on = state.get(o["key"], False)
        layers.append(map_overlays.build_layer(o) if on else [])
        styles.append(_overlay_chip_style(on))
        labels.append(map_overlays.chip_label(o))
    return layers, styles, labels, state


