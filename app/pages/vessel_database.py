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
from datetime import datetime, timezone

import dash
from dash import html, dcc, Input, Output, callback

from app.engines import ais_db

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
    ]
)


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
