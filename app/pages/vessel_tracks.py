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
from datetime import datetime, timedelta, timezone

import os

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


def _unwrap_lons(latlons):
    """Longitude-continuous display coords across the antimeridian (the
    Ever Shine Pacific crossing drew a line around the whole world)."""
    out, prev = [], None
    for la, lo in latlons:
        if prev is not None:
            while lo - prev > 180.0:
                lo -= 360.0
            while lo - prev < -180.0:
                lo += 360.0
        out.append([la, lo])
        prev = lo
    return out


def _track_layer(mmsi, name, points, _hdg=None, _cog=None, _len=None):
    """Polyline + hoverable points for the selected vessel."""
    if not points:
        return [], None
    latlons = _unwrap_lons([[p[1], p[2]] for p in points])
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
    for (ts, lat, lon, sog, nav_status, source), (lat, lon) in zip(
            points, latlons):
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


_INFO_CARD_H = 330       # vaste max-hoogte van de info-card (px)


_EARTH_NM = 3440.065        # earth radius in nautical miles
_EARTH_KM = 6371.0088       # earth radius in km


def _haversine_leg(lat1, lon1, lat2, lon2, radius):
    from math import radians, sin, cos, asin, sqrt
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * radius * asin(sqrt(a))


def _measure_features(fc):
    """EditControl.geojson may arrive as a FeatureCollection dict, a bare
    list of features, or None depending on state. Return a list of features
    in all cases."""
    if not fc:
        return []
    if isinstance(fc, dict):
        return fc.get("features") or []
    if isinstance(fc, list):
        return fc
    return []


def _line_length(coords):
    """Total great-circle length of a [[lon,lat],...] line, in (NM, km)."""
    nm = km = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
        nm += _haversine_leg(lat1, lon1, lat2, lon2, _EARTH_NM)
        km += _haversine_leg(lat1, lon1, lat2, lon2, _EARTH_KM)
    return nm, km


def _measure_card(features):
    """Info-corner card summarising drawn measure lines."""
    lines = []
    for f in (features or []):
        g = (f or {}).get("geometry") or {}
        if g.get("type") == "LineString" and len(g.get("coordinates", [])) >= 2:
            lines.append(g["coordinates"])
    if not lines:
        return {"display": "none"}, []
    total_nm = total_km = 0.0
    rows = []
    for i, coords in enumerate(lines, 1):
        nm, km = _line_length(coords)
        total_nm += nm
        total_km += km
        rows.append(html.Div(
            f"Line {i}: {nm:.2f} NM  ·  {km:.2f} km",
            style={"fontSize": "0.72rem", "padding": "1px 0"}))
    if len(lines) > 1:
        rows.append(html.Div(
            f"Total: {total_nm:.2f} NM  ·  {total_km:.2f} km",
            style={"fontSize": "0.74rem", "fontWeight": "700",
                   "color": TEAL, "borderTop": f"1px solid {LINE}",
                   "marginTop": "3px", "paddingTop": "3px"}))
    style = {"position": "absolute", "right": "10px", "bottom": "10px",
             "zIndex": 1000, "background": "rgba(255,255,255,0.97)",
             "border": f"1px solid {LINE}", "borderRadius": "8px",
             "padding": "8px 11px", "width": "210px",
             "boxShadow": "0 2px 10px rgba(0,0,0,0.18)"}
    header = html.Div(
        html.Span("Measured distance",
                  style={"fontWeight": "700", "fontSize": "0.74rem"}),
        style={"borderBottom": f"1px solid {LINE}", "paddingBottom": "4px",
               "marginBottom": "4px"})
    return style, [header, *rows]


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
    """Reported AIS destination as plain text (hyperlink removed by request:
    the LOCODE lookup pages added little and left the portal)."""
    return dest or "\u2014"


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
    name_children = [html.Span(info.get("name", ""),
                               style={"flex": "1 1 auto"})]
    if info.get("imo"):
        name_children.append(html.Button(
            "Info", n_clicks=0,
            id={"type": "vtt-specs-open", "imo": str(info["imo"])},
            title="Vessel details from the fleet database "
                  "(built, POB, deck, cranes, SAT system)",
            style={"padding": "1px 8px", "borderRadius": "6px",
                   "fontSize": "0.7rem", "cursor": "pointer",
                   "border": f"1px solid {LINE}", "background": "white",
                   "color": TEAL, "fontWeight": "600"}))
    name = html.Div(name_children,
                    style={"fontWeight": "700", "fontSize": "0.8rem",
                           "color": TEAL, "margin": "1px 0 4px",
                           "display": "flex", "alignItems": "center",
                           "gap": "6px"})
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
        html.Div(id="vtt-daterange-wrap", style={"display": "none"}, children=[
            dcc.RangeSlider(
                id="vtt-daterange", min=-90, max=0, step=1, value=[-30, 0],
                marks={-90: "90d", -60: "60d", -30: "30d", -14: "14d",
                       -7: "7d", 0: "now"},
                allowCross=False,
                tooltip={"placement": "bottom", "always_visible": False}),
        ]),
    ], style={"marginBottom": "8px", "display": "flex", "alignItems": "center",
              "flexWrap": "wrap", "gap": "4px 14px"}),
    dcc.Interval(id="vtt-tick", interval=900_000, n_intervals=0),  # 15 min kiosk refresh
    # vessel-details modal: permanent in the layout (hidden); populated by
    # its own callback so the big map callback stays untouched
    html.Div(id="vtt-specs-modal", style={"display": "none"}, children=[
        html.Div([
            html.Button("\u2715", id="vtt-specs-close", n_clicks=0,
                        title="Close",
                        style={"position": "absolute", "top": "8px",
                               "right": "10px", "border": "none",
                               "background": "none", "cursor": "pointer",
                               "color": "#94a3b8", "fontSize": "0.95rem",
                               "zIndex": 2, "padding": "2px 4px"}),
            html.Div(id="vtt-specs-body"),
        ], style={"position": "relative"}),
    ]),
    dcc.Store(id="vtt-specs-request", data=None),
    dcc.Store(id="vtt-selected", data=None),
    dcc.Store(id="vtt-mapclick", data=None),
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
                   zoomSnap=0.25,
                   style={"width": "100%", "height": MAP_HEIGHT,
                          "borderRadius": "8px", "border": f"1px solid {LINE}"},
                   children=[
                       dl.TileLayer(url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                                    attribution="© OpenStreetMap contributors"),
                       *[dl.LayerGroup(id={"type": "vtt-ovl-layer",
                                              "key": o["key"]})
                         for o in map_overlays.OVERLAYS],
                       dl.LayerGroup(id="vtt-layer"),
                       dl.FeatureGroup(id="vtt-measure-fg", children=[
                           dl.EditControl(
                               id="vtt-measure-edit",
                               position="topright",
                               draw={"polyline": True, "polygon": False,
                                     "rectangle": False, "circle": False,
                                     "marker": False, "circlemarker": False},
                               edit={"edit": True, "remove": True}),
                       ]),
                       # draw-props zijn STATISCH; de Leaflet.Draw polyline-knop
                       # staat permanent rechtsboven (zelfde patroon als de
                       # werkende Map Features kaart). Geen draw-prop toggling.
                   ], eventHandlers={
                       "mousemove": {"variable": "vtMeasure.onMove"},
                       "draw:drawstart": {"variable": "vtMeasure.onModeStart"},
                       "draw:drawstop": {"variable": "vtMeasure.onModeStop"},
                       "draw:editstart": {"variable": "vtMeasure.onModeStart"},
                       "draw:editstop": {"variable": "vtMeasure.onModeStop"},
                       "draw:deletestart": {"variable": "vtMeasure.onModeStart"},
                       "draw:deletestop": {"variable": "vtMeasure.onModeStop"},
                   }),
            html.Div(id="vtt-hovercoord",
                     style={"position": "absolute", "bottom": "6px",
                            "left": "50%", "transform": "translateX(-50%)",
                            "zIndex": 1000, "background": "rgba(255,255,255,0.9)",
                            "border": f"1px solid {LINE}", "borderRadius": "5px",
                            "padding": "2px 8px", "fontSize": "0.68rem",
                            "fontFamily": "monospace", "color": "#334155",
                            "pointerEvents": "none"}),
            html.Div(id="vtt-measure-card", style={"display": "none"}),
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
    Output("vtt-specs-request", "data"),
    Output("vtt-daterange-wrap", "style"),
    Input("vtt-tick", "n_intervals"),
    Input("vtt-search", "value"),
    Input("vtt-col-toggle", "n_clicks"),
    Input("vtt-col-toggle2", "n_clicks"),
    Input("vtt-mapclick", "data"),
    Input("vtt-info-close", "n_clicks"),
    Input({"type": "vtt-dot", "mmsi": dash.ALL}, "n_clicks"),
    Input({"type": "vtt-sel", "mmsi": dash.ALL}, "n_clicks"),
    Input({"type": "vtt-tf", "val": dash.ALL}, "n_clicks"),
    Input({"type": "vtt-grp", "name": dash.ALL}, "n_clicks"),
    Input({"type": "vtt-specs-open", "imo": dash.ALL}, "n_clicks"),
    Input("vtt-daterange", "value"),
    State("vtt-selected", "data"),
    State("vtt-typefilter", "data"),
    State("vtt-collapsed", "data"),
    State("vtt-col", "style"),
)
def _render(_tick, search, _colt, _colt2, _map_clicks, _infoclose, _dots,
            _sels, _chips, _grps, _specs, daterange,
            selected, typefilter, collapsed, col_style):
    trig = ctx.triggered_id
    clicked = bool(ctx.triggered) and bool(ctx.triggered[0].get("value"))
    specs_request = dash.no_update
    is_spec_click = (clicked and isinstance(trig, dict)
                     and trig.get("type") == "vtt-specs-open")
    if is_spec_click:
        # main callback receives the click (proven delivery path) and only
        # signals the details modal via its request store; keep the map
        # view exactly as it is.
        specs_request = {"imo": str(trig.get("imo")),
                         "n": ctx.triggered[0].get("value")}
    is_refresh = trig in (None, "vtt-tick") or is_spec_click
    # a date-range change re-renders the track and refits the view (it is
    # NOT a refresh), which is exactly what you want when scrubbing

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

    d_from, d_to = _range_days(daterange)
    try:
        if d_to == 0:
            # window ends now: use the real-time `latest` fixes (kiosk stays
            # live; `positions` is downsampled) and age-filter client-side
            cutoff = datetime.now(timezone.utc) - timedelta(days=d_from)
            all_rows = [r for r in ais_db.latest_positions()
                        if r[2] is not None and _as_utc(r[2]) >= cutoff]
        else:
            # window ends in the past: historical snapshot per vessel
            all_rows = ais_db.positions_within(d_from, d_to)
    except ais_db.AisDbError as exc:
        empty = html.Div(str(exc), style={"color": "#b91c1c", "padding": "12px",
                                          "fontSize": "0.85rem"})
        return ([], empty, "Vessels", "", dash.no_update, new_selected,
                [], typefilter, collapsed, col_style_out, reopen_style,
                {"display": "none"}, [], {"display": "none"}, specs_request,
                {"display": "none"})

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

    subtitle = (f"positions within {_range_label(daterange)} \u00b7 "
                f"click a vessel for its track"
                if new_selected is None
                else "click the map or the vessel to go back")
    count = (f"Vessels ({len(rows)})" if typefilter is None
             else f"{typefilter} ({len(rows)} of {len(all_rows)})")
    viewport = dash.no_update

    if new_selected is None:
        layer = _vessel_markers(rows)
        # Re-fit to all vessels ONLY on initial load or a filter change.
        # A deselect (clicking the map / sidebar to go back) keeps the
        # current view - the user stays zoomed where they were.
        deselect_triggers = ("vtt-mapclick", "vtt-info-close")
        was_deselect = trig in deselect_triggers or (
            isinstance(trig, dict) and trig.get("type") == "vtt-veslsel")
        if rows and (trig is None or filter_changed) and not was_deselect:
            bounds = _pad_bounds(
                [[min(r[3] for r in rows), min(r[4] for r in rows)],
                 [max(r[3] for r in rows), max(r[4] for r in rows)]])
            viewport = {"bounds": bounds, "transition": "flyToBounds",
                        "options": {"padding": [40, 40]}}
    else:
        mmsi = int(new_selected)
        name = next((r[1] for r in rows if str(r[0]) == new_selected), new_selected)
        points = ais_db.track(mmsi, days=d_from, days_until=d_to)
        sel_row = next((r for r in rows if str(r[0]) == new_selected), None)
        hdg, cg, ln = ((sel_row[9], sel_row[10], sel_row[11])
                       if sel_row else (None, None, None))
        layer, bounds = _track_layer(mmsi, name, points, hdg, cg, ln)
        if bounds is not None and not is_refresh:
            # Fit the whole track tightly so it fills the view. Small padding,
            # maxZoom high enough that a compact track still zooms right in.
            viewport = {"bounds": _pad_bounds(bounds),
                        "transition": "flyToBounds",
                        "options": {"padding": [25, 25], "maxZoom": 16}}
        subtitle = (f"{name} — {len(points)} points, {_range_label(daterange)}"
                    f" · " + subtitle)

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
    range_style = {"width": "340px", "maxWidth": "55vw",
                    "marginLeft": "auto"}
    return (layer, _vessel_list(rows, new_selected, collapsed), count,
            subtitle, viewport, new_selected, chips, typefilter, collapsed,
            col_style_out, reopen_style, info_style, info_children,
            close_style, specs_request, range_style)


def _as_utc(ts):
    """positions/latest timestamps are tz-aware; defend against naive ones
    (older rows) by assuming UTC."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _range_days(value):
    """RangeSlider value [-from, -to] (days ago) -> (days, days_until) for
    ais_db.track. Defends against None / inverted input."""
    try:
        lo, hi = sorted(int(v) for v in (value or (-30, 0)))
    except (TypeError, ValueError):
        lo, hi = -30, 0
    return (max(1, -lo), max(0, -hi))


def _range_label(value):
    d_from, d_to = _range_days(value)
    if d_to == 0:
        return f"last {d_from} days"
    return f"{d_from}\u2013{d_to} days ago"


def _resolve_selection(trig, clicked, current):
    """Pure selection logic: toggle on vessel click, clear on map click,
    keep on refresh."""
    if not clicked:
        return current
    if trig == "vtt-mapclick":
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





@callback(
    Output("vtt-measure-card", "style"),
    Output("vtt-measure-card", "children"),
    Input("vtt-measure-edit", "geojson"),
    Input("vtt-measure-edit", "action"),
    prevent_initial_call=True,
)
def _measure_result(fc, _action):
    feats = _measure_features(fc)
    style, children = _measure_card(feats)
    return style, children







# Map clicks are filtered client-side before they can deselect: while the
# measure tool is drawing/editing/deleting, or when the click landed on a
# marker, track line or drawn shape, the click is swallowed. Only a genuine
# empty-sea click reaches _render as a deselect.
clientside_callback(
    """
    function(n) {
        if (!n) { return window.dash_clientside.no_update; }
        var m = window.vtMeasure || {};
        if (m.drawing || m.clickOnFeature) {
            return window.dash_clientside.no_update;
        }
        return n;
    }
    """,
    Output("vtt-mapclick", "data"),
    Input("vtt-map", "n_clicks"),
    prevent_initial_call=True,
)


# --- vessel-details modal ----------------------------------------------------

_PHOTO_DIR = os.getenv("VESSEL_PHOTO_DIR", "/data/vessel_photos")
_PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def _photo_available(imo):
    try:
        return any(os.path.exists(os.path.join(_PHOTO_DIR, f"{imo}{e}"))
                   for e in _PHOTO_EXTS)
    except OSError:
        return False


_MODAL_STYLE = {"position": "fixed", "inset": "0", "zIndex": 1100,
                "background": "rgba(15,23,42,0.45)", "display": "flex",
                "alignItems": "center", "justifyContent": "center"}
_MODAL_CARD = {"background": "white", "borderRadius": "10px",
               "padding": "14px 18px", "width": "420px", "maxWidth": "92vw",
               "maxHeight": "82vh", "overflowY": "auto",
               "boxShadow": "0 8px 30px rgba(0,0,0,0.35)"}
_MROW_L = {"color": MUTED, "fontSize": "0.76rem", "flex": "0 0 140px"}
_MROW_V = {"fontSize": "0.76rem", "fontWeight": "600", "flex": "1 1 auto"}


def _mrow(label, value):
    return html.Div([html.Span(label, style=_MROW_L),
                     html.Span(value, style=_MROW_V)],
                    style={"display": "flex", "gap": "8px",
                           "padding": "2.5px 0",
                           "borderBottom": "1px solid #f1f5f9"})


def _mnum(v, unit="", dec=0):
    if v is None:
        return "\u2014"
    if isinstance(v, float) and dec == 0 and v == int(v):
        return f"{int(v)}{unit}"
    return f"{v:.{dec}f}{unit}" if dec else f"{v}{unit}"


def _sat_summary(card):
    st = card.get("sat_type")
    if st == "none":
        return "none"
    if not st and not card.get("sat_divers"):
        return "\u2014"
    parts = []
    if card.get("sat_divers"):
        parts.append(f"{int(card['sat_divers'])}-man")
    if st:
        parts.append(st)
    if card.get("bell_config") and card["bell_config"] != "none":
        parts.append(f"{card['bell_config']} bell")
    return " ".join(parts) or "\u2014"


def _specs_modal_body(imo, card):
    conf = card.get("spec_confidence")
    conf_dot = ""
    if conf:
        colors = {"high": "#047857", "medium": "#b45309", "low": "#b91c1c"}
        conf_dot = html.Span(f" \u25cf {conf}",
                             title=card.get("spec_source") or "",
                             style={"color": colors.get(conf, MUTED),
                                    "fontSize": "0.72rem", "cursor": "help"})
    dims = "\u2014"
    if card.get("length_m"):
        b = f" \u00d7 {card['beam_m']:.0f}" if card.get("beam_m") else ""
        dims = f"{card['length_m']:.0f}{b} m"
    owner = " / ".join(x for x in (card.get("owner"),
                                   card.get("operator")) if x) or "\u2014"
    rows = [
        _mrow("Type", card.get("vessel_type") or "\u2014"),
        _mrow("Owner / Operator", owner),
        _mrow("Built", card.get("built") or "\u2014"),
        _mrow("Flag", card.get("flag") or "\u2014"),
        _mrow("Region / Tier",
              "{} / {}".format(card.get("region") or "\u2014",
                               card.get("tier") or "\u2014")),
        _mrow("Dimensions", dims),
        _mrow("Deck space", _mnum(card.get("deck_space_m2"), " m\u00b2")),
        _mrow("Deck strength", _mnum(card.get("deck_strength_t_m2"),
                                     " t/m\u00b2")),
        _mrow("POB", _mnum(card.get("pob"))),
        _mrow("Crane 1", _mnum(card.get("crane1_swl_t"), " t")),
        _mrow("Crane 2", _mnum(card.get("crane2_swl_t"), " t")),
        _mrow("SAT system", _sat_summary(card)),
        _mrow("ROV hangar", _mnum(card.get("rov_hangar"))),
    ]
    if card.get("notes"):
        rows.append(_mrow("Notes", card["notes"]))
    header = html.Div([
        html.Div([html.Span(card.get("name") or str(imo),
                            style={"fontWeight": "700", "fontSize": "0.95rem",
                                   "color": TEAL}), conf_dot],
                 style={"flex": "1 1 auto"}),
    ], style={"display": "flex", "alignItems": "center",
              "marginBottom": "6px", "paddingRight": "18px"})
    sub = html.Div(f"IMO {imo} \u2014 fleet database",
                   style={"color": MUTED, "fontSize": "0.7rem",
                          "marginBottom": "8px"})
    photo = []
    if _photo_available(imo):
        photo = [html.Img(src=f"/vessel-photo/{imo}",
                          style={"width": "100%", "borderRadius": "8px",
                                 "marginBottom": "8px", "display": "block"})]
    return html.Div([header, sub, *photo, *rows], style=_MODAL_CARD)


def _specs_modal_missing(imo):
    header = html.Div([
        html.Span("Vessel details", style={"fontWeight": "700",
                                           "flex": "1 1 auto"}),
    ], style={"display": "flex", "alignItems": "center"})
    return html.Div([header,
                     html.Div(f"IMO {imo} not found in the fleet database.",
                              style={"fontSize": "0.8rem", "marginTop": "8px",
                                     "color": MUTED})],
                    style=_MODAL_CARD)


@callback(
    Output("vtt-specs-modal", "style"),
    Output("vtt-specs-body", "children"),
    Input("vtt-specs-request", "data"),
    Input("vtt-specs-close", "n_clicks"),
)
def _specs_modal(request, _close):
    trig = ctx.triggered_id
    clicked = bool(ctx.triggered) and bool(ctx.triggered[0].get("value"))
    hidden = {"display": "none"}
    if not clicked:
        return hidden, []
    if trig == "vtt-specs-close":
        return hidden, []
    if trig == "vtt-specs-request" and request:
        imo = request.get("imo")
        try:
            card = ais_db.vessel_card(int(imo))
        except (ais_db.AisDbError, ValueError, Exception):
            card = None
        body = (_specs_modal_body(imo, card) if card
                else _specs_modal_missing(imo))
        return _MODAL_STYLE, body
    return hidden, []
