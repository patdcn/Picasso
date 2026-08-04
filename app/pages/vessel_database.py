"""
Vessel Tracker - Database.

Quality-control browser over the raw AIS `positions` table: filter by
vessel, date range and source, sort on any column, and surface corrupt
fixes with the implied-speed detector (distance/time versus the vessel's
previous fix - a Gulf->Peru decode glitch implies thousands of knots).
Admins can delete individual faulty rows; the `latest` snapshot is
repaired automatically when its fix is removed.

The nightly-backup download box is unchanged.

All data access is wrapped in try/except: if the AIS database is
unreachable the page shows an explanatory card instead of failing.
"""
import glob
import os
from datetime import datetime, timedelta, timezone

import dash
import dash_leaflet as dl
from dash import (html, dcc, Input, Output, State, callback,
                  clientside_callback, ctx, no_update)
from dash.exceptions import PreventUpdate

from app import auth
from app.engines import ais_db

BACKUP_DIR = os.environ.get("AIS_BACKUP_DIR", "/data/backups")
PAGE_PATH = "/vessel-tracker/database"
_PAGE_SIZE = 200


def _list_backups():
    """Nightly pg_dump files, newest first: (path, filename, size, mtime)."""
    out = []
    for p in glob.glob(os.path.join(BACKUP_DIR, "ais_*.dump")):
        try:
            st = os.stat(p)
        except OSError:
            continue
        out.append((p, os.path.basename(p), st.st_size,
                    datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)))
    out.sort(key=lambda t: t[1], reverse=True)
    return out


def _fmt_size(n):
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n / 1.0:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"

dash.register_page(__name__, path=PAGE_PATH, name="Database",
                   category="Vessel Tracker", order=3)

INK = "#1f2937"
MUTED = "#6b7280"
TEAL = "#0f766e"
LINE = "#d1d5db"
HEAD_BG = "#f8fafc"
RED = "#b91c1c"
RED_BG = "#fef2f2"

_CELL = {"padding": "5px 9px", "borderBottom": f"1px solid {LINE}",
         "fontSize": "0.82rem", "whiteSpace": "nowrap"}
_TH = {**_CELL, "textAlign": "left", "background": HEAD_BG, "color": MUTED,
       "fontWeight": "600", "position": "sticky", "top": "0"}
_BTN = {"padding": "5px 12px", "borderRadius": "8px",
        "border": f"1px solid {LINE}", "background": "white",
        "cursor": "pointer", "fontSize": "0.8rem"}
_MINI = {"padding": "2px 9px", "borderRadius": "6px", "cursor": "pointer",
         "fontSize": "0.75rem", "border": f"1px solid {LINE}",
         "background": "white"}


def _fmt_ts(ts):
    if ts is None:
        return "—"
    return ts.strftime("%d-%m %H:%M")


def _error_card(msg):
    return html.Div(
        [
            html.Div("AIS database not available", style={"fontWeight": "600",
                                                          "color": RED}),
            html.Div(str(msg), style={"color": MUTED, "fontSize": "0.85rem",
                                      "marginTop": "6px", "maxWidth": "720px"}),
        ],
        style={"border": "1px solid #fecaca", "background": RED_BG,
               "borderRadius": "10px", "padding": "14px 18px"},
    )


def _banner(msg, ok=True):
    if not msg:
        return None
    return html.Div(msg, style={
        "padding": "8px 14px", "borderRadius": "8px", "margin": "8px 0",
        "fontSize": "0.85rem",
        "border": f"1px solid {'#bbf7d0' if ok else '#fecaca'}",
        "background": "#f0fdf4" if ok else RED_BG,
        "color": "#166534" if ok else RED})


def _parse_bounds(b):
    """dl.Map bounds [[south, west], [north, east]] -> normalised
    (lat_min, lat_max, lon_min, lon_max), or None."""
    try:
        (a, b_), (c, d) = b
        la0, la1 = sorted((float(a), float(c)))
        lo0, lo1 = sorted((float(b_), float(d)))
        return la0, la1, lo0, lo1
    except Exception:
        return None


def _checked_rids(states_list):
    """rids of ticked row-checkboxes from ctx.states_list (the single
    pattern-ALL State in this callback)."""
    for st in (states_list or []):
        if isinstance(st, list):
            return [e["id"]["rid"] for e in st
                    if isinstance(e.get("id"), dict)
                    and e["id"].get("type") == "vtdb-chk" and e.get("value")]
    return []


def _bulk_delete(rids):
    """Delete a list of fixes; returns (n_ok, first_error)."""
    n, err = 0, None
    for rid in rids:
        try:
            mmsi, ts, src = _parse_rid(rid)
            ais_db.position_delete(mmsi, ts, src)
            n += 1
        except Exception as exc:
            err = err or str(exc)
    return n, err


def _rid(mmsi, ts, source):
    return f"{mmsi}|{ts.isoformat()}|{source}"


def _parse_rid(rid):
    mmsi, ts, source = rid.split("|", 2)
    return int(mmsi), datetime.fromisoformat(ts), source


def _qc_table(rows, can_edit, pending, threshold):
    headers = (["Sel"] if can_edit else []) + [
        "Time (UTC)", "Vessel", "Lat", "Lon", "SOG",
        "\u0394 prev", "\u0394t", "Implied", "Action"]
    body = []
    for (ts, mmsi, name, lat, lon, sog, nav, source,
         dist_nm, dt_min, impl_kn, suspect) in rows:
        rid = _rid(mmsi, ts, source)
        if can_edit:
            if pending == rid:
                action = html.Span([
                    html.Button("Confirm", n_clicks=0,
                                id={"type": "vtdb-delc", "rid": rid},
                                style={**_MINI, "border": f"1px solid {RED}",
                                       "color": "white", "background": RED,
                                       "marginRight": "5px"}),
                    html.Button("Cancel", n_clicks=0,
                                id={"type": "vtdb-delx", "rid": rid},
                                style=_MINI),
                ])
            else:
                action = html.Button("Delete", n_clicks=0,
                                     id={"type": "vtdb-del", "rid": rid},
                                     style={**_MINI, "color": RED,
                                            "border": f"1px solid {RED}"})
        else:
            action = html.Span("—", style={"color": MUTED})
        hl = {"background": RED_BG} if suspect else {}
        cells = []
        if can_edit:
            cells.append(html.Td(dcc.Checklist(
                id={"type": "vtdb-chk", "rid": rid},
                options=[{"label": "", "value": "x"}], value=[],
                style={"margin": "0"}), style={**_CELL, **hl,
                                               "width": "30px"}))
        body.append(html.Tr(cells + [
            html.Td(_fmt_ts(ts), style={**_CELL, **hl}),
            html.Td(name or "—", style={**_CELL, **hl}),
            html.Td(f"{lat:.5f}", style={**_CELL, **hl}),
            html.Td(f"{lon:.5f}", style={**_CELL, **hl}),
            html.Td(f"{sog:.1f}" if sog is not None else "—",
                    style={**_CELL, **hl}),
            html.Td(f"{dist_nm:,.1f} NM" if dist_nm is not None else "—",
                    style={**_CELL, **hl}),
            html.Td(f"{dt_min:,.0f} min" if dt_min is not None else "—",
                    style={**_CELL, **hl}),
            html.Td(f"{impl_kn:,.0f} kn" if impl_kn is not None else "—",
                    style={**_CELL, **hl,
                           **({"color": RED, "fontWeight": "700"}
                              if suspect else {})}),
            html.Td(action, style={**_CELL, **hl}),
        ]))
    head = html.Tr([html.Th(h, style=_TH) for h in headers])
    return html.Table([html.Thead(head), html.Tbody(body)],
                      style={"borderCollapse": "collapse", "width": "100%"})


def _build_qc(vessel, d_from, d_to, source, suspect_on, kn, sort, mode,
              page, can_edit, pending, bbox=None):
    t_from = datetime.fromisoformat(d_from) if d_from else None
    t_to = (datetime.fromisoformat(d_to) + timedelta(days=1)) if d_to else None
    kn = float(kn) if kn not in (None, "") else 30.0
    kw = dict(mmsi=vessel or None, t_from=t_from, t_to=t_to,
              source=source or None,
              threshold_kn=kn, suspect_only=bool(suspect_on),
              mode=(mode if mode in ("chain", "spike", "any") else "chain"),
              bbox=bbox, sort=sort or "ts_desc", page_size=_PAGE_SIZE)
    page = max(1, int(page or 1))
    rows, total = ais_db.positions_qc(page=page, **kw)
    if not rows and page > 1:
        rows, total = ais_db.positions_qc(page=1, **kw)
        page = max(1, -(-total // _PAGE_SIZE))
        if page > 1:
            rows, total = ais_db.positions_qc(page=page, **kw)
    pages = max(1, -(-total // _PAGE_SIZE))
    if total <= _PAGE_SIZE:
        counter = f"{total} fixes shown"
    else:
        start = (page - 1) * _PAGE_SIZE + 1
        counter = (f"{start}\u2013{start + len(rows) - 1} of {total:,} fixes"
                   f" \u00b7 page {page}/{pages}")
    return _qc_table(rows, can_edit, pending, kn), counter, page


_MAP_MAX_MARKERS = 1500     # boven dit aantal: accepted-punten uitdunnen
_MAP_LABEL_LIMIT = 150      # permanente tijdlabels zolang de set klein is


def _pad_bounds(bounds, pad=0.02):
    (a, b), (c, d) = bounds
    if abs(c - a) < 2 * pad and abs(d - b) < 2 * pad:
        return [[a - pad, b - pad], [c + pad, d + pad]]
    return bounds


def _build_map(vessel, d_from, d_to, source, kn, mode):
    """Track map for the QC verdict: teal line through ACCEPTED fixes,
    red markers on rejected ones (with time + implied speed), fitted to
    the whole set. Only rendered when a vessel filter is active."""
    hint_on = {"position": "absolute", "top": "12px", "left": "54px",
               "zIndex": 1000, "padding": "6px 12px",
               "borderRadius": "8px", "background": "rgba(255,255,255,0.92)",
               "border": f"1px solid {LINE}", "color": MUTED,
               "fontSize": "0.82rem"}
    if not vessel:
        return [], no_update, hint_on
    t_from = datetime.fromisoformat(d_from) if d_from else None
    t_to = (datetime.fromisoformat(d_to) + timedelta(days=1)) if d_to else None
    rows, _tot = ais_db.positions_qc(
        mmsi=vessel, t_from=t_from, t_to=t_to, source=source or None,
        threshold_kn=float(kn) if kn not in (None, "") else 30.0,
        mode=(mode if mode in ("chain", "spike", "any") else "chain"),
        sort="ts", page=1, page_size=200000)
    if not rows:
        hint_on["children"] = "No fixes in the selected range."
        return [], no_update, {**hint_on}
    accepted = [r for r in rows if not r[11]]
    suspects = [r for r in rows if r[11]]
    # uitdunnen van accepted-markers bij enorme sets (lijn blijft volledig)
    step = max(1, -(-len(accepted) // _MAP_MAX_MARKERS))
    shown_accepted = accepted[::step]
    permanent = (len(shown_accepted) + len(suspects)) <= _MAP_LABEL_LIMIT
    children = []
    if len(accepted) >= 2:
        children.append(dl.Polyline(
            positions=[[r[3], r[4]] for r in accepted],
            color=TEAL, weight=2, opacity=0.85))
    for r in shown_accepted:
        label = r[0].strftime("%d-%m %H:%M")
        children.append(dl.CircleMarker(
            center=[r[3], r[4]], radius=3, color=TEAL, fillColor=TEAL,
            fillOpacity=0.9, weight=1,
            children=[dl.Tooltip(label, permanent=permanent,
                                 direction="top")]))
    for r in suspects:
        impl = f" \u00b7 {r[10]:,.0f} kn" if r[10] is not None else ""
        label = r[0].strftime("%d-%m %H:%M") + impl
        children.append(dl.CircleMarker(
            center=[r[3], r[4]], radius=6, color=RED, fillColor=RED,
            fillOpacity=0.85, weight=2,
            children=[dl.Tooltip(label, permanent=True,
                                 direction="top")]))
    lats = [r[3] for r in rows]
    lons = [r[4] for r in rows]
    viewport = {"bounds": _pad_bounds([[min(lats), min(lons)],
                                       [max(lats), max(lons)]]),
                "transition": "flyToBounds",
                "options": {"padding": [25, 25], "maxZoom": 15}}
    note = ""
    if step > 1:
        note = (f"Showing 1/{step} of accepted fixes as dots "
                f"(all {len(suspects)} suspects shown, line complete).")
    hint = ({**hint_on, "children": note} if note
            else {"display": "none"})
    return children, viewport, hint


def layout():
    today = datetime.now(timezone.utc).date()
    return html.Div(
    [
        html.H3("Database"),
        html.P("Raw contents of the AIS positions table. Filter, sort and "
               "hunt corrupt fixes. Default detection: chain mode - every "
               "fix is gated against the last ACCEPTED fix, so a corrupt "
               "excursion is rejected in full against the trusted cluster "
               "instead of validating itself. Admins can delete faulty "
               "rows.",
               style={"color": MUTED, "maxWidth": "760px"}),
        html.Div(
            [
                html.Button("Refresh", id="vtdb-refresh", n_clicks=0,
                            style=_BTN),
                dcc.Dropdown(id="vtdb-vessel", placeholder="Vessel",
                             clearable=True,
                             style={"width": "210px", "fontSize": "0.82rem",
                                    "display": "inline-block",
                                    "verticalAlign": "middle",
                                    "marginLeft": "10px"}),
                dcc.DatePickerRange(id="vtdb-dates",
                                    display_format="DD-MM-YYYY",
                                    start_date=(today - timedelta(days=7))
                                    .isoformat(),
                                    end_date=today.isoformat(),
                                    style={"marginLeft": "10px",
                                           "verticalAlign": "middle"}),
                dcc.Dropdown(id="vtdb-source", placeholder="Source",
                             clearable=True,
                             style={"width": "140px", "fontSize": "0.82rem",
                                    "display": "inline-block",
                                    "verticalAlign": "middle",
                                    "marginLeft": "10px"}),
                dcc.Dropdown(id="vtdb-sort", clearable=False, value="ts_desc",
                             options=[
                                 {"label": "Sort: newest first",
                                  "value": "ts_desc"},
                                 {"label": "Sort: oldest first", "value": "ts"},
                                 {"label": "Sort: implied speed",
                                  "value": "speed_desc"},
                                 {"label": "Sort: jump distance",
                                  "value": "dist_desc"},
                                 {"label": "Sort: vessel", "value": "vessel"},
                                 {"label": "Sort: lat \u2191", "value": "lat"},
                                 {"label": "Sort: lat \u2193",
                                  "value": "lat_desc"},
                                 {"label": "Sort: lon \u2191", "value": "lon"},
                                 {"label": "Sort: lon \u2193",
                                  "value": "lon_desc"},
                                 {"label": "Sort: SOG", "value": "sog_desc"},
                             ],
                             style={"width": "185px", "fontSize": "0.82rem",
                                    "display": "inline-block",
                                    "verticalAlign": "middle",
                                    "marginLeft": "10px"}),
            ],
            style={"margin": "6px 0 8px", "display": "flex",
                   "alignItems": "center", "flexWrap": "wrap", "gap": "2px"},
        ),
        html.Div(
            [
                dcc.Checklist(id="vtdb-suspect",
                              options=[{"label": " suspect fixes only",
                                        "value": "on"}],
                              value=[],
                              style={"display": "inline-block",
                                     "fontSize": "0.85rem"}),
                dcc.Dropdown(id="vtdb-mode", clearable=False, value="chain",
                             options=[
                                 {"label": "chain (cluster reference)",
                                  "value": "chain"},
                                 {"label": "spike (one-off glitch)",
                                  "value": "spike"},
                                 {"label": "any fast leg (excursions)",
                                  "value": "any"},
                             ],
                             style={"width": "195px", "fontSize": "0.8rem",
                                    "display": "inline-block",
                                    "verticalAlign": "middle",
                                    "marginLeft": "10px"}),
                html.Span("threshold", style={"color": MUTED,
                                              "fontSize": "0.8rem",
                                              "marginLeft": "12px"}),
                dcc.Input(id="vtdb-kn", type="number", value=30, min=1,
                          style={"width": "70px", "marginLeft": "6px",
                                 "padding": "3px 6px", "fontSize": "0.82rem"}),
                html.Span("kn implied speed", style={"color": MUTED,
                                                     "fontSize": "0.8rem",
                                                     "marginLeft": "6px"}),
                dcc.Checklist(id="vtdb-viewfilter",
                              options=[{"label": " limit table to map view",
                                        "value": "on"}],
                              value=[],
                              style={"display": "inline-block",
                                     "fontSize": "0.85rem",
                                     "marginLeft": "14px"}),
                html.Button("Select all", id="vtdb-selall", n_clicks=0,
                            style={**_BTN, "marginLeft": "14px"}),
                html.Button("Delete selected", id="vtdb-delsel", n_clicks=0,
                            style={**_BTN, "marginLeft": "5px",
                                   "color": RED,
                                   "border": f"1px solid {RED}"}),
                html.Button("", id="vtdb-delselc", n_clicks=0,
                            style={"display": "none"}),
                html.Button("Cancel", id="vtdb-delselx", n_clicks=0,
                            style={"display": "none"}),
                html.Button("\u2039 Prev", id="vtdb-prev", n_clicks=0,
                            style={**_BTN, "marginLeft": "18px"}),
                html.Button("Next \u203a", id="vtdb-next", n_clicks=0,
                            style={**_BTN, "marginLeft": "5px"}),
                html.Span(id="vtdb-count",
                          style={"marginLeft": "14px", "color": MUTED,
                                 "fontSize": "0.85rem"}),
                html.Span(id="vtdb-stamp", style={"color": MUTED,
                                                  "fontSize": "0.8rem",
                                                  "marginLeft": "14px"}),
            ],
            style={"margin": "0 0 10px", "display": "flex",
                   "alignItems": "center", "flexWrap": "wrap"},
        ),
        html.Div(id="vtdb-banner"),
        html.Div(
            [
                html.Div(id="vtdb-qc",
                         style={"flex": "1 1 54%", "minWidth": "540px",
                                "maxHeight": "620px", "overflow": "auto",
                                "border": f"1px solid {LINE}",
                                "borderRadius": "8px"}),
                html.Div(
                    [
                        dl.Map(id="vtdb-map", zoomSnap=0.25,
                               center=[29, 49], zoom=6,
                               style={"width": "100%", "height": "620px",
                                      "borderRadius": "8px",
                                      "border": f"1px solid {LINE}"},
                               children=[
                                   dl.TileLayer(),
                                   dl.LayerGroup(id="vtdb-map-layer"),
                               ]),
                        html.Div("Filter on a vessel to see its track "
                                 "with the QC verdict per fix.",
                                 id="vtdb-map-hint",
                                 style={"position": "absolute",
                                        "top": "12px", "left": "54px",
                                        "zIndex": 1000,
                                        "padding": "6px 12px",
                                        "borderRadius": "8px",
                                        "background":
                                            "rgba(255,255,255,0.92)",
                                        "border": f"1px solid {LINE}",
                                        "color": MUTED,
                                        "fontSize": "0.82rem"}),
                    ],
                    style={"flex": "1 1 46%", "minWidth": "420px",
                           "position": "relative"}),
            ],
            style={"display": "flex", "gap": "12px",
                   "alignItems": "flex-start", "width": "100%",
                   "flexWrap": "wrap"}),
        dcc.Store(id="vtdb-page", data=1),
        dcc.Store(id="vtdb-pending", data=None),
        dcc.Store(id="vtdb-bulk", data=None),
        dcc.Interval(id="vtdb-tick", interval=60_000, n_intervals=0),
        html.Div(id="vtdb-backup-box", style={"display": "none"}, children=html.Div(
            [
                html.Div("Backups", style={"fontWeight": "600",
                                           "marginBottom": "6px"}),
                html.Div("Nightly pg_dump of the complete AIS database "
                         "(03:00 UTC, 14-day rotation). Restore requires the "
                         "TimescaleDB pre/post-restore ritual - see the README.",
                         style={"color": MUTED, "fontSize": "0.78rem",
                                "marginBottom": "8px", "maxWidth": "620px"}),
                html.Div([
                    dcc.Dropdown(id="vtdb-backup-select", clearable=False,
                                 style={"width": "340px", "fontSize": "0.85rem",
                                        "display": "inline-block",
                                        "verticalAlign": "middle"}),
                    html.Button("\u2b07 Download", id="vtdb-backup-dl", n_clicks=0,
                                style={"padding": "6px 14px", "borderRadius": "8px",
                                       "border": f"1px solid {TEAL}", "color": TEAL,
                                       "background": "white", "cursor": "pointer",
                                       "fontWeight": "600", "marginLeft": "10px",
                                       "verticalAlign": "middle"}),
                ]),
                dcc.Download(id="vtdb-backup-file"),
            ],
            style={"border": f"1px solid {LINE}", "borderRadius": "10px",
                   "padding": "12px 16px", "background": "white",
                   "marginTop": "16px", "maxWidth": "720px"})),
    ]
    )


clientside_callback(
    """
    function(n, vals) {
        if (!n) { return window.dash_clientside.no_update; }
        vals = vals || [];
        var anyUnchecked = vals.some(function (v) {
            return !v || !v.length;
        });
        return vals.map(function () {
            return anyUnchecked ? ["x"] : [];
        });
    }
    """,
    Output({"type": "vtdb-chk", "rid": dash.ALL}, "value"),
    Input("vtdb-selall", "n_clicks"),
    State({"type": "vtdb-chk", "rid": dash.ALL}, "value"),
    prevent_initial_call=True,
)


@callback(
    Output("vtdb-backup-box", "style"),
    Output("vtdb-backup-select", "options"),
    Output("vtdb-backup-select", "value"),
    Input("vtdb-tick", "n_intervals"),
    Input("vtdb-refresh", "n_clicks"),
    State("vtdb-backup-select", "value"),
)
def _backup_box(_t, _c, current):
    user = auth.current_user()
    if not (user and user.get("is_admin")):
        return {"display": "none"}, [], None
    backups = _list_backups()
    if not backups:
        return {"display": "none"}, [], None
    options = [{"label": f"{name}  ({_fmt_size(size)}, "
                         f"{mts.strftime('%d-%m-%Y %H:%M')} UTC)",
                "value": name}
               for _p, name, size, mts in backups]
    valid = {o["value"] for o in options}
    value = current if current in valid else options[0]["value"]
    return {"display": "block"}, options, value


@callback(
    Output("vtdb-backup-file", "data"),
    Input("vtdb-backup-dl", "n_clicks"),
    State("vtdb-backup-select", "value"),
    prevent_initial_call=True,
)
def _backup_download(n, name):
    if not n or not name:
        return no_update
    user = auth.current_user()
    if not (user and user.get("is_admin")):        # server-side guard
        return no_update
    # pad-vergrendeling: alleen bestandsnamen uit de backup-map zelf
    safe = os.path.basename(name)
    path = os.path.join(BACKUP_DIR, safe)
    if not (safe.startswith("ais_") and safe.endswith(".dump")
            and os.path.isfile(path)):
        return no_update
    return dcc.send_file(path)


@callback(
    Output("vtdb-qc", "children"),
    Output("vtdb-count", "children"),
    Output("vtdb-banner", "children"),
    Output("vtdb-page", "data"),
    Output("vtdb-pending", "data"),
    Output("vtdb-stamp", "children"),
    Output("vtdb-vessel", "options"),
    Output("vtdb-source", "options"),
    Output("vtdb-map-layer", "children"),
    Output("vtdb-map", "viewport"),
    Output("vtdb-map-hint", "style"),
    Output("vtdb-bulk", "data"),
    Output("vtdb-delselc", "children"),
    Output("vtdb-delselc", "style"),
    Output("vtdb-delselx", "style"),
    Input("vtdb-refresh", "n_clicks"),
    Input("vtdb-vessel", "value"),
    Input("vtdb-dates", "start_date"),
    Input("vtdb-dates", "end_date"),
    Input("vtdb-source", "value"),
    Input("vtdb-suspect", "value"),
    Input("vtdb-kn", "value"),
    Input("vtdb-sort", "value"),
    Input("vtdb-mode", "value"),
    Input("vtdb-prev", "n_clicks"),
    Input("vtdb-next", "n_clicks"),
    Input({"type": "vtdb-del", "rid": dash.ALL}, "n_clicks"),
    Input({"type": "vtdb-delc", "rid": dash.ALL}, "n_clicks"),
    Input({"type": "vtdb-delx", "rid": dash.ALL}, "n_clicks"),
    Input("vtdb-viewfilter", "value"),
    Input("vtdb-map", "bounds"),
    Input("vtdb-delsel", "n_clicks"),
    Input("vtdb-delselc", "n_clicks"),
    Input("vtdb-delselx", "n_clicks"),
    State("vtdb-page", "data"),
    State("vtdb-pending", "data"),
    State({"type": "vtdb-chk", "rid": dash.ALL}, "value"),
    State("vtdb-bulk", "data"),
)
def _qc(_r, vessel, d_from, d_to, source, suspect, kn, sort, mode,
        _pp, _pn, _d, _dc, _dx, viewfilter, map_bounds,
        _ds, _dsc, _dsx, page, pending, _chk, bulk):
    trig = ctx.triggered_id
    clicked = bool(ctx.triggered) and bool(ctx.triggered[0].get("value"))
    stamp = "updated " + datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    user = auth.current_user()
    can_edit = bool(user and user.get("is_admin"))
    banner, ok = None, True

    # default date range: last 7 days (bounds the window query)
    today = datetime.now(timezone.utc).date()
    if not d_from:
        d_from = (today - timedelta(days=7)).isoformat()
    if not d_to:
        d_to = today.isoformat()

    # map-pan/zoom zonder actief viewfilter: niets te doen (en NOOIT een
    # nieuwe viewport terugsturen op een bounds-trigger - feedback-lus)
    if trig == "vtdb-map" and not viewfilter:
        raise PreventUpdate

    _BULK_ON = {**_BTN, "marginLeft": "5px", "color": "white",
                "background": RED, "border": f"1px solid {RED}"}
    _BULK_X_ON = {**_BTN, "marginLeft": "5px"}
    # Pending bulk-confirm survives triggers that don't invalidate the
    # selection (map bounds, paging, per-row delete flow). It is cleared by
    # Cancel, by execution, and by any filter change further below.
    _RESET_BULK = ("vtdb-vessel", "vtdb-dates", "vtdb-source", "vtdb-suspect",
                   "vtdb-kn", "vtdb-sort", "vtdb-mode", "vtdb-refresh",
                   "vtdb-viewfilter", "vtdb-delselx", "vtdb-delselc",
                   "vtdb-delsel")
    if bulk and trig not in _RESET_BULK:
        new_bulk = bulk
        bulk_label = f"Confirm delete {len(bulk)}"
        bulk_c_style, bulk_x_style = _BULK_ON, _BULK_X_ON
    else:
        new_bulk, bulk_label = None, ""
        bulk_c_style = bulk_x_style = {"display": "none"}

    new_pending = pending
    if trig == "vtdb-delsel" and clicked and can_edit:
        rids = _checked_rids(ctx.states_list)
        if not rids:
            banner, ok = "No fixes selected.", False
        else:
            new_bulk = rids
            bulk_label = f"Confirm delete {len(rids)}"
            bulk_c_style, bulk_x_style = _BULK_ON, _BULK_X_ON
    elif trig == "vtdb-delselc" and clicked and can_edit and bulk:
        n_del, err = _bulk_delete(bulk)
        banner = f"Deleted {n_del} fixes."
        if err:
            banner, ok = f"Deleted {n_del} fixes; first error: {err}", False
    elif trig == "vtdb-delselx":
        pass                                   # bulk vervalt (blijft None)
    elif isinstance(trig, dict) and clicked:
        rid = trig.get("rid")
        kind = trig.get("type")
        if kind == "vtdb-del":
            new_pending = rid
        elif kind == "vtdb-delx":
            new_pending = None
        elif kind == "vtdb-delc" and can_edit and rid == pending:
            try:
                mmsi, ts, src = _parse_rid(rid)
                ais_db.position_delete(mmsi, ts, src)
                banner = (f"Deleted fix {ts.strftime('%d-%m %H:%M')} UTC "
                          f"for MMSI {mmsi} ({src}).")
            except Exception as exc:
                banner, ok = f"Delete failed: {exc}", False
            new_pending = None

    page = max(1, int(page or 1))
    if trig in ("vtdb-vessel", "vtdb-dates", "vtdb-source", "vtdb-suspect",
                "vtdb-kn", "vtdb-sort", "vtdb-mode", "vtdb-refresh",
                "vtdb-viewfilter", "vtdb-map"):
        page = 1
        new_pending = None
    elif trig == "vtdb-prev":
        page = max(1, page - 1)
    elif trig == "vtdb-next":
        page = page + 1

    try:
        v_opts = [{"label": name, "value": str(mmsi)}
                  for mmsi, name in ais_db.qc_vessels()]
        s_opts = [{"label": s, "value": s} for s in ais_db.qc_sources()]
        bbox = (_parse_bounds(map_bounds)
                if (viewfilter and map_bounds) else None)
        table, counter, page = _build_qc(vessel, d_from, d_to, source,
                                         bool(suspect), kn, sort, mode, page,
                                         can_edit, new_pending, bbox=bbox)
        if bbox:
            counter = f"{counter} \u00b7 map view"
        _MAP_SCOPE = (None, "vtdb-refresh", "vtdb-vessel", "vtdb-dates",
                      "vtdb-source", "vtdb-kn", "vtdb-mode")
        deleted_now = (trig == "vtdb-delselc"
                       or (isinstance(trig, dict)
                           and trig.get("type") == "vtdb-delc"))
        if trig in _MAP_SCOPE:
            # data-scope veranderd: lagen + her-fit
            map_children, map_viewport, hint_style = _build_map(
                vessel, d_from, d_to, source, kn, mode)
        elif deleted_now:
            # na een delete: lagen verversen maar NIET her-fitten, zodat de
            # gebruiker ingezoomd blijft en er geen bounds-event afgaat dat
            # de bulk-flow zou onderbreken
            map_children, map_viewport, hint_style = _build_map(
                vessel, d_from, d_to, source, kn, mode)
            map_viewport = no_update
        else:
            # bounds/paginering/sort/selectie: kaart blijft onaangeroerd
            map_children = map_viewport = hint_style = no_update
    except ais_db.AisDbError as exc:
        return (_error_card(exc), "", None, page, None, stamp, [], [],
                [], no_update, no_update, None, "", {"display": "none"},
                {"display": "none"})
    except Exception as exc:  # never kill the page
        return (_error_card(f"Unexpected error: {exc}"), "", None, page,
                None, stamp, [], [], [], no_update, no_update, None, "",
                {"display": "none"}, {"display": "none"})

    return (table, counter, _banner(banner, ok), page, new_pending, stamp,
            v_opts, s_opts, map_children, map_viewport, hint_style,
            new_bulk, bulk_label, bulk_c_style, bulk_x_style)
