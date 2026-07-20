"""
Activity Log (admin only) — review who signed in, for how long, and which tools
they used, with filters, CSV export, and controls to prune or wipe the log.

Admin-only via the before_request guard (any /admin* path). Times are UTC, to
match the rest of the audit trail.
"""
import io
import time
import datetime

import dash
from dash import html, dcc, Input, Output, State, callback, no_update
from dash.exceptions import PreventUpdate

from app import activity
from app.adminui import is_admin, denied

dash.register_page(__name__, path="/admin/activity", name="Activity Log")  # no category

INK = "#1f2937"
MUTED = "#6b7280"
ACCENT = "#0f766e"
GRID = "#e5e7eb"
DANGER = "#b91c1c"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _fmt_ts(s):
    if not s:
        return "—"
    return s.replace("T", " ")[:16]


def _fmt_dur(login_at, end_at):
    try:
        a = datetime.datetime.fromisoformat(login_at)
        b = datetime.datetime.fromisoformat(end_at)
        secs = max(0, (b - a).total_seconds())
    except Exception:
        return "—"
    m = int(secs // 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m"
    return f"{int(secs)}s"


def _dur_secs(login_at, end_at):
    try:
        a = datetime.datetime.fromisoformat(login_at)
        b = datetime.datetime.fromisoformat(end_at)
        return max(0, (b - a).total_seconds())
    except Exception:
        return 0


def _card(children, maxw="1000px"):
    return html.Div(children, style={
        "background": "#fff", "border": f"1px solid {GRID}", "borderRadius": "12px",
        "padding": "18px", "marginBottom": "18px", "maxWidth": maxw})


def _stat(label, value):
    return html.Div([
        html.Div(label, style={"fontSize": "0.72rem", "color": MUTED,
                               "textTransform": "uppercase", "letterSpacing": "0.04em"}),
        html.Div(value, style={"fontSize": "1.4rem", "fontWeight": 700, "color": ACCENT}),
    ], style={"background": "#f8fafc", "border": f"1px solid {GRID}",
              "borderRadius": "10px", "padding": "10px 14px", "flex": "1 1 150px"})


def _table(cols, rows):
    th = {"textAlign": "left", "padding": "7px 12px", "borderBottom": f"2px solid {GRID}",
          "position": "sticky", "top": 0, "background": "#fff", "fontSize": "0.72rem",
          "color": MUTED, "textTransform": "uppercase", "letterSpacing": "0.03em"}
    td = {"padding": "6px 12px", "borderBottom": f"1px solid {GRID}", "fontSize": "0.82rem"}
    head = html.Thead(html.Tr([html.Th(c, style=th) for c in cols]))
    body = html.Tbody([html.Tr([html.Td(v, style=td) for v in r]) for r in rows])
    if not rows:
        body = html.Tbody([html.Tr([html.Td("No activity for these filters.",
                                            colSpan=len(cols),
                                            style={**td, "color": MUTED})])])
    return html.Table([head, body], style={"width": "100%", "borderCollapse": "collapse"})


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
def layout():
    if not is_admin():
        return denied()
    emails = activity.known_emails()
    paths = activity.known_paths()
    return html.Div([
        html.H3("Activity Log"),
        html.P("Sign-ins, session length and tool usage. Session length runs from "
               "login to sign-out, or to the last activity when a tab was just "
               "closed. Times are UTC.",
               style={"color": MUTED, "maxWidth": "720px"}),

        dcc.Store(id="al-store"),
        dcc.Store(id="al-clear-refresh", data=0),
        dcc.Download(id="al-csv"),

        _card([
            html.Div([
                html.Div([
                    html.Label("User", style={"fontSize": "0.75rem", "fontWeight": 600,
                                              "color": MUTED}),
                    dcc.Dropdown(id="al-user", value="",
                                 options=[{"label": "All users", "value": ""}]
                                 + [{"label": e, "value": e} for e in emails],
                                 clearable=False, style={"width": "230px"}),
                ]),
                html.Div([
                    html.Label("Date range (by login)", style={"fontSize": "0.75rem",
                                                               "fontWeight": 600, "color": MUTED}),
                    html.Div(dcc.DatePickerRange(id="al-dates", display_format="DD MMM YYYY",
                                                 first_day_of_week=1)),
                ]),
                html.Div([
                    html.Label("View", style={"fontSize": "0.75rem", "fontWeight": 600,
                                              "color": MUTED}),
                    dcc.RadioItems(id="al-view", value="sessions",
                                   options=[{"label": " Sessions", "value": "sessions"},
                                            {"label": " Page views", "value": "events"}],
                                   labelStyle={"display": "block"},
                                   style={"fontSize": "0.85rem"}),
                ]),
                html.Div([
                    html.Label("Tool (page views)", style={"fontSize": "0.75rem",
                                                           "fontWeight": 600, "color": MUTED}),
                    dcc.Dropdown(id="al-path", value="",
                                 options=[{"label": "All tools", "value": ""}]
                                 + [{"label": (nm or pth), "value": pth} for pth, nm in paths],
                                 clearable=False, style={"width": "230px"}),
                ]),
                html.Div([
                    html.Label("\u00a0", style={"fontSize": "0.75rem", "display": "block"}),
                    html.Button("Refresh", id="al-refresh", n_clicks=0, style={
                        "padding": "8px 16px", "borderRadius": "8px", "border": "none",
                        "background": ACCENT, "color": "#fff", "fontWeight": 600,
                        "cursor": "pointer"}),
                ]),
            ], style={"display": "flex", "gap": "18px", "flexWrap": "wrap",
                      "alignItems": "flex-start"}),
        ]),

        html.Div(id="al-summary", style={"display": "flex", "gap": "12px",
                                         "flexWrap": "wrap", "marginBottom": "14px"}),

        _card([
            html.Div([
                html.Span("Records", style={"fontWeight": 700}),
                html.Button("Download CSV", id="al-csv-btn", n_clicks=0, style={
                    "marginLeft": "auto", "padding": "6px 12px", "borderRadius": "8px",
                    "border": "none", "background": ACCENT, "color": "#fff",
                    "fontWeight": 600, "cursor": "pointer", "fontSize": "0.8rem"}),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "8px"}),
            html.Div(id="al-table", style={"maxHeight": "520px", "overflowY": "auto"}),
        ]),

        _card([
            html.H4("Maintenance", style={"marginTop": 0}),
            html.P("Prune old entries or wipe the log if it grows too large.",
                   style={"color": MUTED, "fontSize": "0.85rem", "marginTop": 0}),
            html.Div([
                html.Div([
                    html.Label("Delete entries before", style={"fontSize": "0.75rem",
                                                               "fontWeight": 600, "color": MUTED,
                                                               "display": "block"}),
                    dcc.DatePickerSingle(id="al-before-date", display_format="DD MMM YYYY",
                                         first_day_of_week=1),
                    dcc.ConfirmDialogProvider(
                        html.Button("Delete before date", style={
                            "marginLeft": "8px", "padding": "8px 14px", "borderRadius": "8px",
                            "border": f"1px solid {DANGER}", "background": "#fff",
                            "color": DANGER, "fontWeight": 600, "cursor": "pointer"}),
                        id="al-clear-before-confirm",
                        message="Delete all activity recorded before the chosen date? "
                                "This cannot be undone."),
                ], style={"display": "flex", "alignItems": "flex-end", "gap": "6px"}),
                dcc.ConfirmDialogProvider(
                    html.Button("Delete ALL activity", style={
                        "padding": "8px 14px", "borderRadius": "8px",
                        "border": f"1px solid {DANGER}", "background": "#fff",
                        "color": DANGER, "fontWeight": 600, "cursor": "pointer"}),
                    id="al-clear-all-confirm",
                    message="Delete the ENTIRE activity log? This cannot be undone."),
            ], style={"display": "flex", "gap": "24px", "flexWrap": "wrap",
                      "alignItems": "flex-end"}),
            html.Div(id="al-status", style={"fontSize": "0.85rem", "marginTop": "12px",
                                            "minHeight": "1.1em"}),
        ], maxw="720px"),
    ], style={"maxWidth": "1040px"})


# --------------------------------------------------------------------------- #
# Render table + summary
# --------------------------------------------------------------------------- #
@callback(
    Output("al-summary", "children"),
    Output("al-table", "children"),
    Output("al-store", "data"),
    Input("al-user", "value"),
    Input("al-dates", "start_date"),
    Input("al-dates", "end_date"),
    Input("al-view", "value"),
    Input("al-path", "value"),
    Input("al-refresh", "n_clicks"),
    Input("al-clear-refresh", "data"),
)
def _render(user, d0, d1, view, path, _n, _clr):
    if not is_admin():
        raise PreventUpdate
    user = user or None
    d0 = d0[:10] if d0 else None
    d1 = d1[:10] if d1 else None

    if view == "events":
        evs = activity.query_events(email=user, path=(path or None), date_from=d0, date_to=d1)
        cols = ["Time (UTC)", "User", "Tool", "Path"]
        rows = [[_fmt_ts(e["ts"]), e["email"], e.get("name") or "—", e["path"]] for e in evs]
        users = len({e["email"] for e in evs})
        summary = [_stat("Page views", str(len(evs))),
                   _stat("Unique users", str(users)),
                   _stat("Tools touched", str(len({e["path"] for e in evs})))]
    else:
        ss = activity.query_sessions(email=user, date_from=d0, date_to=d1)
        cols = ["User", "Login (UTC)", "Ended (UTC)", "Duration", "Page views"]
        rows = []
        total_secs = 0
        for s in ss:
            end = s["logout_at"] or s["last_seen_at"]
            total_secs += _dur_secs(s["login_at"], end)
            ended = _fmt_ts(end) + ("" if s["logout_at"] else "  (last seen)")
            rows.append([s["email"], _fmt_ts(s["login_at"]), ended,
                         _fmt_dur(s["login_at"], end), str(s["views"])])
        th = int(total_secs // 3600)
        tm = int((total_secs % 3600) // 60)
        summary = [_stat("Sessions", str(len(ss))),
                   _stat("Unique users", str(len({s["email"] for s in ss}))),
                   _stat("Total time", f"{th}h {tm:02d}m"),
                   _stat("Page views", str(sum(s["views"] for s in ss)))]

    store = {"cols": cols, "rows": rows, "view": view}
    return summary, _table(cols, rows), store


# --------------------------------------------------------------------------- #
# Clear (prune before date / wipe all)
# --------------------------------------------------------------------------- #
@callback(
    Output("al-status", "children"),
    Output("al-clear-refresh", "data"),
    Input("al-clear-all-confirm", "submit_n_clicks"),
    State("al-clear-refresh", "data"),
    prevent_initial_call=True,
)
def _clear_all(_n, tick):
    if not is_admin():
        raise PreventUpdate
    n = activity.clear()
    return (html.Span(f"Deleted the entire activity log ({n} rows).",
                      style={"color": DANGER, "fontWeight": 600}), (tick or 0) + 1)


@callback(
    Output("al-status", "children", allow_duplicate=True),
    Output("al-clear-refresh", "data", allow_duplicate=True),
    Input("al-clear-before-confirm", "submit_n_clicks"),
    State("al-before-date", "date"),
    State("al-clear-refresh", "data"),
    prevent_initial_call=True,
)
def _clear_before(_n, before, tick):
    if not is_admin():
        raise PreventUpdate
    if not before:
        return html.Span("Pick a date first.", style={"color": DANGER}), no_update
    n = activity.clear(before=before[:10])
    return (html.Span(f"Deleted {n} rows recorded before {before[:10]}.",
                      style={"color": ACCENT, "fontWeight": 600}), (tick or 0) + 1)


# --------------------------------------------------------------------------- #
# CSV export of the current view
# --------------------------------------------------------------------------- #
@callback(
    Output("al-csv", "data"),
    Input("al-csv-btn", "n_clicks"),
    State("al-store", "data"),
    prevent_initial_call=True,
)
def _csv(_n, data):
    if not is_admin():
        raise PreventUpdate
    if not data or not data.get("rows"):
        return no_update
    buf = io.StringIO()
    buf.write(",".join(data["cols"]) + "\n")
    for r in data["rows"]:
        cells = ['"%s"' % str(v).replace('"', '""') for v in r]
        buf.write(",".join(cells) + "\n")
    stamp = time.strftime("%Y%m%d_%H%M")
    return dict(content=buf.getvalue(), filename=f"activity_{data['view']}_{stamp}.csv")
