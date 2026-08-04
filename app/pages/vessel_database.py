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
from dash import html, dcc, Input, Output, State, callback, ctx, no_update

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


def _rid(mmsi, ts, source):
    return f"{mmsi}|{ts.isoformat()}|{source}"


def _parse_rid(rid):
    mmsi, ts, source = rid.split("|", 2)
    return int(mmsi), datetime.fromisoformat(ts), source


def _qc_table(rows, can_edit, pending, threshold):
    headers = ["Time (UTC)", "Vessel", "MMSI", "Lat", "Lon", "SOG",
               "\u0394 prev", "\u0394t", "Implied", "Source", "Action"]
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
        body.append(html.Tr([
            html.Td(_fmt_ts(ts), style={**_CELL, **hl}),
            html.Td(name or "—", style={**_CELL, **hl}),
            html.Td(str(mmsi), style={**_CELL, **hl, "color": MUTED}),
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
            html.Td(source, style={**_CELL, **hl, "color": MUTED}),
            html.Td(action, style={**_CELL, **hl}),
        ]))
    head = html.Tr([html.Th(h, style=_TH) for h in headers])
    return html.Table([html.Thead(head), html.Tbody(body)],
                      style={"borderCollapse": "collapse", "width": "100%"})


def _build_qc(vessel, d_from, d_to, source, suspect_on, kn, sort, mode,
              page, can_edit, pending):
    t_from = datetime.fromisoformat(d_from) if d_from else None
    t_to = (datetime.fromisoformat(d_to) + timedelta(days=1)) if d_to else None
    kn = float(kn) if kn not in (None, "") else 30.0
    kw = dict(mmsi=vessel or None, t_from=t_from, t_to=t_to,
              source=source or None,
              threshold_kn=kn, suspect_only=bool(suspect_on),
              mode=(mode if mode in ("chain", "spike", "any") else "chain"),
              sort=sort or "ts_desc", page_size=_PAGE_SIZE)
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
        html.Div(id="vtdb-qc",
                 style={"maxHeight": "560px", "overflow": "auto",
                        "border": f"1px solid {LINE}",
                        "borderRadius": "8px"}),
        dcc.Store(id="vtdb-page", data=1),
        dcc.Store(id="vtdb-pending", data=None),
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
    State("vtdb-page", "data"),
    State("vtdb-pending", "data"),
)
def _qc(_r, vessel, d_from, d_to, source, suspect, kn, sort, mode,
        _pp, _pn, _d, _dc, _dx, page, pending):
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

    new_pending = pending
    if isinstance(trig, dict) and clicked:
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
                "vtdb-kn", "vtdb-sort", "vtdb-mode", "vtdb-refresh"):
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
        table, counter, page = _build_qc(vessel, d_from, d_to, source,
                                         bool(suspect), kn, sort, mode, page,
                                         can_edit, new_pending)
    except ais_db.AisDbError as exc:
        return (_error_card(exc), "", None, page, None, stamp, [], [])
    except Exception as exc:  # never kill the page
        return (_error_card(f"Unexpected error: {exc}"), "", None, page,
                None, stamp, [], [])

    return (table, counter, _banner(banner, ok), page, new_pending, stamp,
            v_opts, s_opts)
