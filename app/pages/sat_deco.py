"""
SAT Diving — saturation decompression profile planner.

Implements the standard USN Diving Manual (Rev 7) Ch.13 saturation decompression
schedule (storage depth -> surface) using the rates in Table 13-9 and the rules
in section 13-23 (rest stops, terminal 4 fsw hold). Produces a tabulated
depth/time profile and a depth-vs-time chart, with a ft/m display toggle and a
start date/time that defaults to "now" (vessel local time, read from the browser).

Upward-excursion initiation is prepped (mode selector present, disabled) and will
be wired in a later session. INDICATIVE PLANNING ONLY — see the disclaimer block.
"""
import io
from datetime import datetime, date as _date

import dash
from dash import html, dcc, Input, Output, State, callback, clientside_callback, no_update
import plotly.graph_objects as go

from app.engines import sat_deco as eng

dash.register_page(__name__, path="/diving/sat-deco", name="SAT Decompression",
                   category="SAT Diving", order=0)

MUTED = "#64748b"
ACCENT = "#0f766e"
INK = "#0f172a"
GRID = "#e2e8f0"
AMBER = "#b45309"
AMBER_BG = "rgba(186,117,23,0.13)"


# --------------------------------------------------------------------------- #
# Small UI helpers
# --------------------------------------------------------------------------- #
def _label(txt):
    return html.Label(txt, style={"fontSize": "0.75rem", "fontWeight": 600,
                                  "color": MUTED, "display": "block",
                                  "marginBottom": "4px"})


def _hour_input(id_, value):
    return dcc.Input(id=id_, type="number", value=value, min=0, max=24, step=1,
                     debounce=True, style={"width": "70px"})


def _card(label, value, sub=None, accent=False):
    return html.Div([
        html.Div(label, style={"fontSize": "0.72rem", "color": MUTED,
                               "textTransform": "uppercase", "letterSpacing": "0.04em"}),
        html.Div(value, style={"fontSize": "1.4rem", "fontWeight": 700,
                               "color": ACCENT if accent else INK, "lineHeight": "1.2",
                               "marginTop": "2px"}),
        html.Div(sub or "", style={"fontSize": "0.74rem", "color": MUTED}),
    ], style={"background": "#f8fafc", "border": f"1px solid {GRID}",
              "borderRadius": "10px", "padding": "10px 14px", "minWidth": "140px",
              "flex": "1 1 140px"})


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
def layout():
    today = _date.today().isoformat()
    return html.Div([
        html.H3("SAT Decompression planner", style={"marginBottom": "2px"}),
        html.P("Standard saturation decompression from storage depth to surface, "
               "per the U.S. Navy Diving Manual (Rev 7) Ch.13, Table 13-9. "
               "Indicative planning only.",
               style={"color": MUTED, "marginTop": 0, "maxWidth": "780px"}),

        dcc.Interval(id="sd-boot", interval=200, max_intervals=1),
        dcc.Store(id="sd-profile"),     # serialisable rows for CSV
        dcc.Store(id="sd-unit-prev", data="fsw"),

        # ---- input panel ----
        html.Div([
            html.Div([
                _label("Mode"),
                dcc.RadioItems(
                    id="sd-mode",
                    options=[
                        {"label": " Standard decompression", "value": "standard"},
                        {"label": " Upward-excursion start (coming soon)",
                         "value": "excursion", "disabled": True},
                    ],
                    value="standard",
                    style={"fontSize": "0.85rem"},
                    labelStyle={"display": "block", "marginBottom": "3px"},
                ),
            ], style={"flex": "1 1 220px", "minWidth": "200px"}),

            html.Div([
                _label("Storage depth"),
                html.Div([
                    dcc.Input(id="sd-depth", type="number", value=300, step="any",
                              debounce=True, style={"width": "110px"}),
                    html.Span("fsw", id="sd-depth-unit",
                              style={"marginLeft": "6px", "color": MUTED,
                                     "fontSize": "0.85rem"}),
                ], style={"display": "flex", "alignItems": "center"}),
                _label("Units"),
                dcc.RadioItems(
                    id="sd-unit",
                    options=[{"label": " ft (fsw)", "value": "fsw"},
                             {"label": " m (msw)", "value": "msw"}],
                    value="fsw", inline=True,
                    style={"fontSize": "0.85rem"},
                    labelStyle={"marginRight": "12px"},
                ),
            ], style={"flex": "1 1 200px", "minWidth": "190px"}),

            html.Div([
                _label("Start date / time (vessel local)"),
                html.Div([
                    dcc.DatePickerSingle(id="sd-date", date=today,
                                         display_format="DD MMM YYYY"),
                    dcc.Input(id="sd-time", type="text", value="12:00",
                              debounce=True, placeholder="HH:MM",
                              style={"width": "78px", "marginLeft": "8px"}),
                ], style={"display": "flex", "alignItems": "center"}),
                html.Div(dcc.Checklist(
                    id="sd-terminal",
                    options=[{"label": " 4 fsw / 80-min terminal stop", "value": "on"}],
                    value=["on"], style={"fontSize": "0.82rem"}),
                    id="sd-terminal-row", style={"marginTop": "10px"}),
            ], style={"flex": "1 1 240px", "minWidth": "230px"}),

            html.Div([
                _label("Decompress to"),
                dcc.RadioItems(
                    id="sd-decompto",
                    options=[{"label": " Surface", "value": "surface"},
                             {"label": " New (shallower) storage depth",
                              "value": "newdepth"}],
                    value="surface",
                    style={"fontSize": "0.85rem"},
                    labelStyle={"display": "block", "marginBottom": "3px"}),
                html.Div([
                    _label("New storage depth"),
                    html.Div([
                        dcc.Input(id="sd-target", type="number", value=150,
                                  step="any", debounce=True,
                                  style={"width": "110px"}),
                        html.Span("fsw", id="sd-target-unit",
                                  style={"marginLeft": "6px", "color": MUTED,
                                         "fontSize": "0.85rem"}),
                    ], style={"display": "flex", "alignItems": "center"}),
                ], id="sd-target-row", style={"display": "none", "marginTop": "6px"}),
            ], style={"flex": "1 1 220px", "minWidth": "200px"}),
        ], style={"display": "flex", "gap": "22px", "flexWrap": "wrap",
                  "background": "#fff", "border": f"1px solid {GRID}",
                  "borderRadius": "12px", "padding": "16px"}),

        # ---- advanced rest schedule ----
        html.Details([
            html.Summary("Rest schedule (advanced)",
                         style={"cursor": "pointer", "fontSize": "0.85rem",
                                "fontWeight": 600, "color": ACCENT,
                                "margin": "12px 0 6px"}),
            html.Div([
                html.Div([_label("Rest 1 start"), _hour_input("sd-r1s", 0)]),
                html.Div([_label("Rest 1 end"), _hour_input("sd-r1e", 6)]),
                html.Div([_label("Rest 2 start"), _hour_input("sd-r2s", 14)]),
                html.Div([_label("Rest 2 end"), _hour_input("sd-r2e", 16)]),
            ], style={"display": "flex", "gap": "16px", "flexWrap": "wrap",
                      "alignItems": "flex-end"}),
            html.Div(id="sd-rest-note", style={"fontSize": "0.78rem",
                                               "marginTop": "8px"}),
            html.Div("Whole-clock-hour windows; depth is held during a rest. "
                     "The manual requires a total of 8 h rest per 24 h, in at least "
                     "two periods (\u00a713-23.4).",
                     style={"fontSize": "0.74rem", "color": MUTED, "marginTop": "4px"}),
        ], style={"background": "#fff", "border": f"1px solid {GRID}",
                  "borderRadius": "12px", "padding": "4px 16px 14px"}),

        # ---- summary cards ----
        html.Div(id="sd-cards", style={"display": "flex", "gap": "12px",
                                       "flexWrap": "wrap", "margin": "16px 0"}),

        # ---- chart + table ----
        html.Div([
            html.Div([
                dcc.Graph(id="sd-graph", config={"displayModeBar": False},
                          style={"height": "430px"}),
            ], style={"flex": "1 1 460px", "minWidth": "340px"}),
            html.Div([
                html.Div([
                    html.Span("Decompression profile", style={"fontWeight": 700}),
                    html.Button("Download CSV", id="sd-csv-btn", n_clicks=0,
                                style={"marginLeft": "auto", "padding": "6px 12px",
                                       "borderRadius": "8px", "border": "none",
                                       "background": ACCENT, "color": "#fff",
                                       "fontWeight": 600, "cursor": "pointer",
                                       "fontSize": "0.8rem"}),
                    dcc.Download(id="sd-csv"),
                ], style={"display": "flex", "alignItems": "center",
                          "marginBottom": "8px"}),
                html.Div(id="sd-table", style={"maxHeight": "400px",
                                               "overflowY": "auto"}),
            ], style={"flex": "1 1 380px", "minWidth": "320px"}),
        ], style={"display": "flex", "gap": "24px", "flexWrap": "wrap"}),

        # ---- rules + disclaimer ----
        _rules_block(),
    ], style={"maxWidth": "1180px"})


# --------------------------------------------------------------------------- #
# Rules + disclaimer (static)
# --------------------------------------------------------------------------- #
def _rules_block():
    def li(t):
        return html.Li(t, style={"marginBottom": "5px"})
    band_rows = [
        html.Tr([html.Td("1,600 \u2013 200 fsw"), html.Td("6 ft/hr"), html.Td("1 ft / 10 min")]),
        html.Tr([html.Td("200 \u2013 100 fsw"), html.Td("5 ft/hr"), html.Td("1 ft / 12 min")]),
        html.Tr([html.Td("100 \u2013 50 fsw"), html.Td("4 ft/hr"), html.Td("1 ft / 15 min")]),
        html.Tr([html.Td("50 \u2013 0 fsw"), html.Td("3 ft/hr"), html.Td("1 ft / 20 min")]),
    ]
    cell = {"padding": "4px 14px 4px 0", "fontSize": "0.82rem"}
    for tr in band_rows:
        for td in tr.children:
            td.style = cell
    return html.Div([
        html.H4("Rules implemented", style={"marginBottom": "6px"}),
        html.Div([
            html.Table([html.Thead(html.Tr([
                html.Th("Depth band", style={**cell, "fontWeight": 700}),
                html.Th("Rate (Table 13-9)", style={**cell, "fontWeight": 700}),
                html.Th("As increments", style={**cell, "fontWeight": 700})]))]
                + [html.Tbody(band_rows)]),
        ], style={"marginBottom": "10px"}),
        html.Ul([
            li("Travel runs upward at the band rate above; the chamber moves in "
               "1-foot steps, never faster than 1 fsw/min (\u00a713-23.5). The band "
               "boundary belongs to the slower, shallower band."),
            li("Rest stops: travel halts for the scheduled rest windows, holding "
               "depth. The manual requires 8 h rest per 24 h in at least two "
               "periods (\u00a713-23.4); the default windows reproduce the manual's "
               "example daily routine (0000\u20130600 and 1400\u20131600)."),
            li("Terminal sequence: the last stop may be taken at 4 fsw for 80 "
               "minutes, followed by direct ascent to the surface at 1 fsw/min "
               "(\u00a713-23.5). This sequence runs to completion without an "
               "intervening rest stop."),
            li("Decompression to a new, shallower storage depth uses these same "
               "Table 13-9 rates and rest stops, with no terminal 4 fsw sequence "
               "(\u00a713-21). Downward excursions are then permitted immediately "
               "at the new depth; upward excursions require \u2265 48 h of "
               "stabilisation there."),
            li("Depths are computed in fsw (the table's native unit); the metre "
               "view converts at 1 m = 3.281 ft for display only."),
            li("Prepared but not yet active: upward-excursion initiation at "
               "2 fsw/min with a 2-hour post-excursion hold for storage depths "
               "\u2264 200 fsw (\u00a713-23.1\u20133)."),
        ], style={"color": INK, "fontSize": "0.85rem", "paddingLeft": "18px",
                  "lineHeight": "1.5", "maxWidth": "820px"}),
        html.Div([
            html.Span("Disclaimer  ", style={"fontWeight": 700, "color": AMBER}),
            html.Span("This tool is for indicative planning only. It is not an "
                      "operational decompression schedule and must not be used to "
                      "control a dive. Saturation decompression shall be conducted "
                      "under the responsible Diving Supervisor / Diving Medical "
                      "Officer using the controlling tables and unit procedures. "
                      "Always validate against the current U.S. Navy Diving Manual."),
        ], style={"marginTop": "12px", "padding": "10px 14px",
                  "background": AMBER_BG, "border": f"1px solid {AMBER}",
                  "borderRadius": "10px", "fontSize": "0.82rem", "color": "#7c2d12",
                  "maxWidth": "860px"}),
    ], style={"marginTop": "28px", "paddingTop": "14px",
              "borderTop": f"1px solid {GRID}"})


# --------------------------------------------------------------------------- #
# Default start date/time = browser-local "now" (vessel local time)
# --------------------------------------------------------------------------- #
clientside_callback(
    """
    function(n){
        var d = new Date();
        var p = function(x){ return ('' + x).padStart(2, '0'); };
        var date = d.getFullYear() + '-' + p(d.getMonth()+1) + '-' + p(d.getDate());
        var time = p(d.getHours()) + ':' + p(d.getMinutes());
        return [date, time];
    }
    """,
    Output("sd-date", "date"),
    Output("sd-time", "value"),
    Input("sd-boot", "n_intervals"),
    prevent_initial_call=True,
)


# --------------------------------------------------------------------------- #
# Unit toggle: convert the displayed depth value and its bounds.
# --------------------------------------------------------------------------- #
@callback(
    Output("sd-depth", "value"),
    Output("sd-depth", "step"),
    Output("sd-depth-unit", "children"),
    Output("sd-target", "value"),
    Output("sd-target-unit", "children"),
    Output("sd-unit-prev", "data"),
    Input("sd-unit", "value"),
    State("sd-depth", "value"),
    State("sd-target", "value"),
    State("sd-unit-prev", "data"),
    prevent_initial_call=True,
)
def _convert_units(unit, depth, target, prev):
    if unit == prev:
        return (no_update, no_update, no_update, no_update, no_update, unit)

    def conv(v, default):
        if v is None:
            return default
        return (round(eng.fsw_to_msw(v), 1) if unit == "msw"
                else round(eng.msw_to_fsw(v)))

    suffix = "msw" if unit == "msw" else "fsw"
    return (conv(depth, 300), "any", suffix, conv(target, 150), suffix, unit)


# --------------------------------------------------------------------------- #
# Show the new-storage-depth field (and hide the terminal stop) when the
# destination is a shallower storage depth rather than the surface.
# --------------------------------------------------------------------------- #
@callback(
    Output("sd-target-row", "style"),
    Output("sd-terminal-row", "style"),
    Input("sd-decompto", "value"),
)
def _toggle_target(decompto):
    if decompto == "newdepth":
        return {"display": "block", "marginTop": "6px"}, {"display": "none"}
    return {"display": "none"}, {"marginTop": "10px"}


# --------------------------------------------------------------------------- #
# Main compute: profile -> cards, chart, table, CSV store, rest-note.
# --------------------------------------------------------------------------- #
@callback(
    Output("sd-cards", "children"),
    Output("sd-graph", "figure"),
    Output("sd-table", "children"),
    Output("sd-profile", "data"),
    Output("sd-rest-note", "children"),
    Input("sd-mode", "value"),
    Input("sd-unit", "value"),
    Input("sd-depth", "value"),
    Input("sd-date", "date"),
    Input("sd-time", "value"),
    Input("sd-terminal", "value"),
    Input("sd-decompto", "value"),
    Input("sd-target", "value"),
    Input("sd-r1s", "value"), Input("sd-r1e", "value"),
    Input("sd-r2s", "value"), Input("sd-r2e", "value"),
)
def _compute(mode, unit, depth, date_str, time_str, terminal, decompto, target,
             r1s, r1e, r2s, r2e):
    # --- parse start datetime ---
    start = _parse_dt(date_str, time_str)
    if start is None:
        return _msg("Enter a valid start time as HH:MM.")

    # --- depth -> fsw, clamp ---
    try:
        depth = float(depth)
    except (TypeError, ValueError):
        return _msg("Enter a storage depth.")
    depth_fsw = eng.msw_to_fsw(depth) if unit == "msw" else depth
    depth_fsw = max(eng.MIN_FSW, min(eng.MAX_FSW, depth_fsw))

    # --- destination: surface or a new shallower storage depth ---
    to_surface = decompto != "newdepth"
    target_fsw = 0.0
    if not to_surface:
        try:
            target_fsw = float(target)
        except (TypeError, ValueError):
            return _msg("Enter a new storage depth.")
        target_fsw = eng.msw_to_fsw(target_fsw) if unit == "msw" else target_fsw
        if target_fsw >= depth_fsw - 1e-6:
            return _msg("New storage depth must be shallower than the current "
                        "storage depth.")
        target_fsw = max(0.0, target_fsw)

    # --- rest windows ---
    windows = _windows(r1s, r1e, r2s, r2e)
    rest_h = _rest_hours_per_24(windows)

    # --- run engine ---
    terminal_on = bool(terminal) and "on" in terminal
    try:
        verts = eng.simulate(depth_fsw, start, windows, target_fsw, terminal_on,
                             mode=mode)
    except NotImplementedError:
        return _msg("Upward-excursion mode isn't built yet \u2014 use Standard.")
    su = eng.summary(verts)

    unit_lbl = "fsw" if unit == "fsw" else "msw"
    dfmt = "%.0f" if unit == "fsw" else "%.1f"

    # --- cards ---
    end_lbl = "Surfacing" if to_surface else "Arrival at new depth"
    end_depth_txt = ("surface" if to_surface
                     else f"{dfmt % eng.depth_in(su['end_depth_fsw'], unit)} {unit_lbl}")
    cards = [
        _card("Total decompression", f"{su['total_h']:.1f} h",
              f"{su['total_days']:.2f} days", accent=True),
        _card(end_lbl, f"{su['end_dt']:%H:%M}",
              f"{su['end_dt']:%a %d %b %Y}"),
        _card("Storage depth", dfmt % eng.depth_in(depth_fsw, unit),
              f"{unit_lbl} \u2192 {end_depth_txt}"),
        _card("Rest stops", str(su["rest_stops"]),
              f"{rest_h:.0f} h / 24 h"),
    ]

    fig = _figure(verts, unit, unit_lbl, dfmt)
    rows = eng.table_rows(verts, unit)
    table = _table(rows, unit_lbl, dfmt)

    # --- serialisable CSV payload ---
    payload = {
        "unit": unit_lbl,
        "rows": [[round(e, 2), c.strftime("%Y-%m-%d %H:%M"),
                  round(d, 1), ev] for (e, c, d, ev) in rows],
    }

    # --- rest-hours note (+ new-storage 48 h reminder) ---
    if abs(rest_h - 8.0) < 1e-6:
        note = [html.Span(f"Total rest: {rest_h:.0f} h / 24 h \u2014 matches the manual.",
                          style={"color": "#15803d"})]
    else:
        note = [html.Span(f"Total rest: {rest_h:.0f} h / 24 h \u2014 the manual "
                          f"specifies 8 h / 24 h.", style={"color": AMBER,
                                                           "fontWeight": 600})]
    if not to_surface:
        note.append(html.Div(
            "On reaching the new storage depth, downward excursions are permitted "
            "immediately; upward excursions require \u2265 48 h at the new depth "
            "(\u00a713-21).", style={"color": MUTED, "marginTop": "4px"}))

    return cards, fig, table, payload, note


# --------------------------------------------------------------------------- #
# Figure / table / helpers
# --------------------------------------------------------------------------- #
def _figure(verts, unit, unit_lbl, dfmt):
    xs = [v["elapsed_h"] for v in verts]
    ys = [eng.depth_in(v["depth_fsw"], unit) for v in verts]
    hov = [f"+{v['elapsed_h']:.1f} h<br>{v['clock']:%a %H:%M}<br>"
           f"{dfmt % eng.depth_in(v['depth_fsw'], unit)} {unit_lbl}<br>{v['event']}"
           for v in verts]

    fig = go.Figure()

    # rest-stop shading (pair 'Rest stop begins' -> next vertex)
    for i, v in enumerate(verts[:-1]):
        if v["event"] == "Rest stop begins":
            fig.add_vrect(x0=v["elapsed_h"], x1=verts[i + 1]["elapsed_h"],
                          fillcolor=AMBER_BG, line_width=0, layer="below")

    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="lines+markers",
        line=dict(color=ACCENT, width=2),
        marker=dict(size=5, color=ACCENT),
        text=hov, hovertemplate="%{text}<extra></extra>",
        showlegend=False,
    ))
    fig.update_layout(
        margin=dict(l=8, r=8, t=10, b=8),
        plot_bgcolor="#fff", paper_bgcolor="#fff",
        xaxis=dict(title="Elapsed time (hours)", gridcolor=GRID, zeroline=False),
        yaxis=dict(title=f"Chamber depth ({unit_lbl})", autorange="reversed",
                   gridcolor=GRID, zeroline=False),
        font=dict(color=INK, size=12),
    )
    return fig


def _table(rows, unit_lbl, dfmt):
    head = html.Thead(html.Tr([
        html.Th("Elapsed", style=_TH), html.Th("Clock", style=_TH),
        html.Th(f"Depth ({unit_lbl})", style=_TH), html.Th("Event", style=_TH)]))
    body = []
    for (e, c, d, ev) in rows:
        resting = ev in ("Rest stop begins",)
        body.append(html.Tr([
            html.Td(f"{e:.2f} h", style=_TD),
            html.Td(f"{c:%a %H:%M}", style=_TD),
            html.Td(dfmt % d, style={**_TD, "fontWeight": 600}),
            html.Td(ev, style={**_TD, "color": AMBER if resting else INK}),
        ], style={"background": AMBER_BG if resting else "transparent"}))
    return html.Table([head, html.Tbody(body)],
                      style={"width": "100%", "borderCollapse": "collapse",
                             "fontSize": "0.8rem"})


_TH = {"textAlign": "left", "padding": "6px 10px", "borderBottom": f"2px solid {GRID}",
       "position": "sticky", "top": 0, "background": "#fff", "fontSize": "0.74rem",
       "color": MUTED, "textTransform": "uppercase", "letterSpacing": "0.03em"}
_TD = {"padding": "5px 10px", "borderBottom": f"1px solid {GRID}"}


def _parse_dt(date_str, time_str):
    if not date_str or not time_str:
        return None
    try:
        d = datetime.fromisoformat(str(date_str)[:10]).date()
        parts = str(time_str).strip().split(":")
        hh, mm = int(parts[0]), int(parts[1])
        if not (0 <= hh < 24 and 0 <= mm < 60):
            return None
        return datetime(d.year, d.month, d.day, hh, mm)
    except (ValueError, IndexError):
        return None


def _windows(r1s, r1e, r2s, r2e):
    out = []
    for a, b in ((r1s, r1e), (r2s, r2e)):
        try:
            a, b = float(a) % 24, float(b) % 24
        except (TypeError, ValueError):
            continue
        if abs(a - b) > 1e-9:
            out.append((a, b))
    return out or eng.DEFAULT_REST_WINDOWS


def _rest_hours_per_24(windows):
    total = 0.0
    for a, b in windows:
        total += (b - a) if a <= b else (24 - a + b)
    return total


def _msg(text):
    fig = go.Figure()
    fig.update_layout(margin=dict(l=8, r=8, t=10, b=8),
                      plot_bgcolor="#fff", paper_bgcolor="#fff",
                      xaxis=dict(visible=False), yaxis=dict(visible=False),
                      annotations=[dict(text=text, showarrow=False,
                                        font=dict(color=MUTED, size=13))])
    note = html.Div(text, style={"color": MUTED, "fontSize": "0.85rem"})
    return [], fig, note, None, ""


# --------------------------------------------------------------------------- #
# CSV download
# --------------------------------------------------------------------------- #
@callback(
    Output("sd-csv", "data"),
    Input("sd-csv-btn", "n_clicks"),
    State("sd-profile", "data"),
    State("sd-depth", "value"),
    prevent_initial_call=True,
)
def _csv(_n, payload, depth):
    if not payload:
        return no_update
    unit = payload["unit"]
    buf = io.StringIO()
    buf.write("# SAT decompression profile (indicative planning only)\n")
    buf.write(f"elapsed_h,clock,depth_{unit},event\n")
    for e, c, d, ev in payload["rows"]:
        buf.write(f"{e},{c},{d},{ev}\n")
    return dict(content=buf.getvalue(), filename="sat_deco_profile.csv")
