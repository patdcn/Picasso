"""
Vessel Tracker - Database.

Live view of what the AIS collector has stored: headline numbers, a
per-vessel overview (including who has NOT been heard yet - terrestrial
AIS coverage gaps), and the most recent stored track points. Refreshes
every 60 s; manual refresh button included.

All content is built inside one callback wrapped in try/except: if the AIS
database is unreachable (separate Dokploy project) the page shows an
explanatory card instead of failing, in line with the portal's _safe()
philosophy.
"""
import glob
import os
from datetime import datetime, timezone

import dash
from dash import html, dcc, Input, Output, State, callback, ctx, no_update

from app import auth
from app.engines import ais_db

BACKUP_DIR = os.environ.get("AIS_BACKUP_DIR", "/data/backups")


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

dash.register_page(__name__, path="/vessel-tracker/database", name="Database",
                   category="Vessel Tracker", order=3)

INK = "#1f2937"
MUTED = "#6b7280"
TEAL = "#0f766e"
LINE = "#d1d5db"
HEAD_BG = "#f8fafc"
DIM = "#aeb4bd"

_CELL = {"padding": "6px 10px", "borderBottom": f"1px solid {LINE}",
         "fontSize": "0.85rem", "whiteSpace": "nowrap"}
_TH = {**_CELL, "textAlign": "left", "background": HEAD_BG, "color": MUTED,
       "fontWeight": "600", "position": "sticky", "top": "0"}


def _fmt_ts(ts):
    if ts is None:
        return "—"
    return ts.strftime("%d-%m %H:%M")


def _age(ts):
    """Human age of a timestamp vs now (UTC)."""
    if ts is None:
        return "—"
    s = (datetime.now(timezone.utc) - ts).total_seconds()
    if s < 90:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)} min ago"
    if s < 172800:
        return f"{s / 3600:.1f} h ago"
    return f"{int(s // 86400)} d ago"


def _card(label, value, sub=""):
    return html.Div(
        [
            html.Div(label, style={"color": MUTED, "fontSize": "0.78rem"}),
            html.Div(value, style={"color": INK, "fontSize": "1.5rem",
                                   "fontWeight": "700", "lineHeight": "1.2"}),
            html.Div(sub, style={"color": MUTED, "fontSize": "0.75rem"}),
        ],
        style={"border": f"1px solid {LINE}", "borderRadius": "10px",
               "padding": "12px 16px", "minWidth": "150px", "background": "white"},
    )


def _table(headers, rows, row_styles=None):
    head = html.Tr([html.Th(h, style=_TH) for h in headers])
    body = []
    for i, r in enumerate(rows):
        style = (row_styles[i] if row_styles else None) or {}
        body.append(html.Tr([html.Td(c, style={**_CELL, **style}) for c in r]))
    return html.Table([html.Thead(head), html.Tbody(body)],
                      style={"borderCollapse": "collapse", "width": "100%"})


def _error_card(msg):
    return html.Div(
        [
            html.Div("AIS database not available", style={"fontWeight": "600",
                                                          "color": "#b91c1c"}),
            html.Div(str(msg), style={"color": MUTED, "fontSize": "0.85rem",
                                      "marginTop": "6px", "maxWidth": "720px"}),
        ],
        style={"border": "1px solid #fecaca", "background": "#fef2f2",
               "borderRadius": "10px", "padding": "14px 18px"},
    )


layout = html.Div(
    [
        html.H3("Database"),
        html.P("Live contents of the AIS track database (separate ais-db project). "
               "Auto-refreshes every 60 seconds.",
               style={"color": MUTED, "maxWidth": "720px"}),
        html.Div(
            [
                html.Button("Refresh", id="vtdb-refresh", n_clicks=0,
                            style={"padding": "6px 14px", "borderRadius": "8px",
                                   "border": f"1px solid {LINE}", "background": "white",
                                   "cursor": "pointer"}),
                html.Span(id="vtdb-stamp", style={"color": MUTED,
                                                  "fontSize": "0.8rem",
                                                  "marginLeft": "12px"}),
            ],
            style={"margin": "6px 0 14px"},
        ),
        dcc.Interval(id="vtdb-tick", interval=60_000, n_intervals=0),
        html.Div(id="vtdb-content"),
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
    Output("vtdb-content", "children"),
    Output("vtdb-stamp", "children"),
    Input("vtdb-tick", "n_intervals"),
    Input("vtdb-refresh", "n_clicks"),
)
def _render(_tick, _clicks):
    stamp = "updated " + datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    try:
        s = ais_db.summary()
        vessels = ais_db.per_vessel()
        recent = ais_db.recent_positions(50)
    except ais_db.AisDbError as exc:
        return _error_card(exc), stamp
    except Exception as exc:  # never kill the page
        return _error_card(f"Unexpected error: {exc}"), stamp

    heard = s["vessels_heard"] or 0
    active = s["fleet_active"] or 0
    cards = html.Div(
        [
            _card("Vessels heard", f"{heard} / {active}",
                  "of active fleet (terrestrial AIS)"),
            _card("Position records", f"{s['position_rows'] or 0:,}",
                  "downsampled to 30 min"),
            _card("Voyage records", f"{s['voyage_rows'] or 0:,}",
                  "destination / ETA changes"),
            _card("Last message", _age(s["last_message"]),
                  _fmt_ts(s["last_message"]) + " UTC"),
        ],
        style={"display": "flex", "gap": "12px", "flexWrap": "wrap",
               "marginBottom": "20px"},
    )

    # --- per-vessel overview -------------------------------------------------
    v_rows, v_styles = [], []
    for (name, mmsi, region, n_points, first_seen, last_seen,
         nav_status, sog, destination, eta) in vessels:
        heard_this = n_points is not None
        v_rows.append([
            name,
            str(mmsi or "—"),
            region or "—",
            f"{n_points:,}" if heard_this else "not heard yet",
            _fmt_ts(first_seen),
            _age(last_seen) if heard_this else "—",
            ais_db.nav_status_label(nav_status) if heard_this else "—",
            f"{sog:.1f} kn" if sog is not None else "—",
            destination or "—",
            eta or "—",
        ])
        v_styles.append(None if heard_this else {"color": DIM})

    # --- recent stored points ------------------------------------------------
    r_rows = [
        [_fmt_ts(ts), vessel, f"{lat:.4f}", f"{lon:.4f}",
         f"{sog:.1f}" if sog is not None else "—",
         ais_db.nav_status_label(nav), source]
        for (ts, vessel, lat, lon, sog, nav, source) in recent
    ]

    content = html.Div(
        [
            cards,
            html.H4("Per vessel", style={"margin": "10px 0 6px"}),
            html.Div(
                _table(["Vessel", "MMSI", "Region", "Points", "First seen",
                        "Last seen", "Status", "SOG", "Destination", "ETA"],
                       v_rows, v_styles),
                style={"maxHeight": "420px", "overflow": "auto",
                       "border": f"1px solid {LINE}", "borderRadius": "8px"},
            ),
            html.H4("Recent stored positions", style={"margin": "18px 0 6px"}),
            html.Div(
                _table(["Time (UTC)", "Vessel", "Lat", "Lon", "SOG", "Status",
                        "Source"], r_rows),
                style={"maxHeight": "360px", "overflow": "auto",
                       "border": f"1px solid {LINE}", "borderRadius": "8px"},
            ),
        ]
    )
    return content, stamp
