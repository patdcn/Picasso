"""
Air MG Diving - Dive Planning.

Lay out a working day of subsequent dives as a Gantt. The selected DCD / US Navy
schedule (bottom time, in-water runtime and any chamber-deco time) comes from the
table engine on the /data volume; the team, shift, standby and tidal inputs drive
the rotation. Standard values live in the parameters DB; the timing assumptions
are admin-set and locked for accounts without the "edit parameters" grant.

Indicative, for commercial planning only - not for operational decompression.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, no_update

from app import auth, params, reports
from app.engines import profiles
from app.engines import dive_planning as dpe

dash.register_page(__name__, path="/air-diving/dive-planning", name="Dive Planning",
                   category="Air MG Diving", order=4)

MODULE = "/air-diving/dive-planning"
INK, MUTED, TEAL, LINE = "#1f2937", "#6b7280", "#0f766e", "#d1d5db"

PDF_BTN = {"padding": "8px 14px", "borderRadius": "8px", "border": "none", "background": TEAL,
           "color": "#fff", "fontWeight": 600, "cursor": "pointer", "fontSize": "0.85rem"}
NUM = {"width": "100%", "padding": "7px 9px", "borderRadius": "8px", "border": f"1px solid {LINE}",
       "boxSizing": "border-box", "fontFamily": "ui-monospace,monospace"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _table_opts():
    return [{"label": o["label"], "value": o["value"]} for o in profiles.selectable_tables()]


def _dlabel(value, d):
    return f"{d} m" if value.split("|")[0] == "dcd" else f"{round(d * 0.3048)} m"


def _depth_m(value, d):
    return float(d) if value.split("|")[0] == "dcd" else float(d) * 0.3048


def _bt_of(value, depth, ri):
    for r in profiles.rows(value, depth):
        if r["value"] == ri:
            try:
                return float(str(r["label"]).split()[0])
            except (ValueError, IndexError):
                return None
    return None


def _field(label, comp, hint=None):
    return html.Div([
        html.Label(label, style={"fontSize": "0.78rem", "fontWeight": 600, "color": INK}),
        comp,
        html.Div(hint, style={"fontSize": "0.68rem", "color": MUTED, "marginTop": "2px"}) if hint else None,
    ], style={"marginBottom": "9px"})


def _radio(id_, value, options):
    return dcc.RadioItems(id=id_, value=value, options=options, inputStyle={"marginRight": "4px"},
                          labelStyle={"display": "inline-block", "marginRight": "14px",
                                      "fontSize": "0.85rem", "cursor": "pointer"},
                          style={"marginTop": "3px"})


def _assumptions_panel():
    try:
        locked = not auth.may_edit_params(auth.current_user(), MODULE)
    except Exception:
        locked = True
    note = html.Div(
        "Timing assumptions are set by an administrator and locked for your account.",
        style={"fontSize": "0.72rem", "color": "#b45309", "background": "#fffbeb",
               "border": "1px solid #fde68a", "borderRadius": "6px", "padding": "6px 8px",
               "marginBottom": "10px"}) if locked else None

    def n(id_, label, key, step, unit):
        return _field(f"{label}  [{unit}]",
                      dcc.Input(id=id_, type="number", value=params.get_float(key), step=step,
                                min=0, debounce=True, disabled=locked, style=NUM))

    body = [
        html.Div("Timing assumptions", style={"fontWeight": 700, "fontSize": "0.9rem", "marginBottom": "8px"}),
        note,
        n("dp-descent-rate", "Descent to worksite", "dp_descent_rate", 1, "m/min"),
        n("dp-arrive", "Arrive at worksite", "dp_arrive_min", 0.5, "min"),
        n("dp-return", "Return from worksite", "dp_return_min", 0.5, "min"),
        n("dp-undress", "Undress", "dp_undress_min", 0.5, "min"),
        n("dp-turnaround", "Turn-around (next diver)", "dp_turnaround_min", 1, "min"),
    ]
    if not locked:
        body += [html.Button("Save as defaults", id="dp-assump-save", n_clicks=0,
                             style={**PDF_BTN, "marginTop": "4px"}),
                 html.Div(id="dp-assump-status", style={"fontSize": "0.78rem", "marginTop": "6px",
                                                        "minHeight": "1em"})]
    else:
        body += [html.Div(id="dp-assump-status", style={"display": "none"})]
    return html.Div(body, style={"border": f"1px solid #e5e7eb", "borderRadius": "10px",
                                 "padding": "14px", "background": "#fafafa", "marginTop": "12px"})


def _gas_panel():
    try:
        locked = not auth.may_edit_params(auth.current_user(), MODULE)
    except Exception:
        locked = True
    note = html.Div(
        "Breathing rates are set by an administrator and locked for your account.",
        style={"fontSize": "0.72rem", "color": "#b45309", "background": "#fffbeb",
               "border": "1px solid #fde68a", "borderRadius": "6px", "padding": "6px 8px",
               "marginBottom": "10px"}) if locked else None

    def n(id_, label, key):
        return _field(f"{label}  [L/min]",
                      dcc.Input(id=id_, type="number", value=params.get_float(key), step=1,
                                min=0, debounce=True, disabled=locked, style=NUM))

    body = [
        html.Div("Breathing rates", style={"fontWeight": 700, "fontSize": "0.9rem", "marginBottom": "4px"}),
        html.Div("Atmospheric (surface) consumption \u2014 multiplied by the pressure at depth "
                 "to give real gas use.", style={"fontSize": "0.68rem", "color": MUTED, "marginBottom": "8px"}),
        note,
        n("dp-rmv-work", "Working diver", "dp_rmv_working"),
        n("dp-rmv-deco", "Deco diver", "dp_rmv_deco"),
    ]
    if not locked:
        body += [html.Button("Save as defaults", id="dp-gas-save", n_clicks=0,
                             style={**PDF_BTN, "marginTop": "4px"}),
                 html.Div(id="dp-gas-status", style={"fontSize": "0.78rem", "marginTop": "6px", "minHeight": "1em"})]
    else:
        body += [html.Div(id="dp-gas-status", style={"display": "none"})]
    return html.Div(body, style={"border": "1px solid #e5e7eb", "borderRadius": "10px",
                                 "padding": "14px", "background": "#fafafa", "marginTop": "12px"})


def _scenario_panel():
    start_h = int(params.get_float("dp_start_hour"))
    return html.Div([
        html.Div("Scenario", style={"fontWeight": 700, "fontSize": "0.9rem", "marginBottom": "8px"}),
        _field("Dive table (metric)",
               dcc.Dropdown(id="dp-table", options=_table_opts(), placeholder="select table",
                            clearable=True, style={"fontSize": "0.82rem"})),
        _field("Depth",
               dcc.Dropdown(id="dp-depth", placeholder="depth", clearable=True,
                            style={"fontSize": "0.82rem"})),
        _field("Bottom time",
               dcc.Dropdown(id="dp-row", placeholder="bottom time", clearable=True,
                            style={"fontSize": "0.82rem"}),
               hint="picked from the selected table's schedule"),
        dcc.Checklist(id="dp-dvis5", options=[{"label": " DVIS5 / IMCA exposure limits", "value": "on"}],
                      value=["on"], inputStyle={"marginRight": "6px"},
                      labelStyle={"fontSize": "0.8rem", "fontWeight": 600, "color": INK},
                      style={"margin": "2px 0 12px"}),
        html.Div([
            html.Div(_field("Working day", _radio("dp-shift", 12, [{"label": " 12 h", "value": 12},
                                                                   {"label": " 24 h", "value": 24}])),
                     style={"flex": "1 1 120px"}),
            html.Div(_field("Start time",
                            dcc.Input(id="dp-start", type="time", value=f"{start_h:02d}:00", style=NUM)),
                     style={"flex": "1 1 100px"}),
        ], style={"display": "flex", "gap": "10px"}),
        html.Div([
            html.Div(_field("Divers per shift",
                            dcc.Input(id="dp-team", type="number", value=int(params.get_float("dp_divers_per_shift")),
                                      min=1, step=1, debounce=True, style=NUM)), style={"flex": "1 1 120px"}),
            html.Div(_field("Divers / dive", _radio("dp-iw", 2, [{"label": " 1", "value": 1},
                                                                 {"label": " 2", "value": 2}])),
                     style={"flex": "1 1 100px"}),
        ], style={"display": "flex", "gap": "10px"}),
        _field("Repeat dives per diver",
               dcc.Input(id="dp-repeats", type="number", value=int(params.get_float("dp_repeats_per_diver")),
                         min=0, step=1, debounce=True, style=NUM),
               hint="0 = one dive each · 1 = up to two"),
        _field("Standby diver",
               _radio("dp-standby", "wet", [{"label": " Dry (no dive)", "value": "dry"},
                                            {"label": " Wet (may work)", "value": "wet"}]),
               hint="dry = one diver per shift held out · wet = joins rotation"),
        html.Hr(style={"border": "none", "borderTop": "1px solid #eee", "margin": "10px 0"}),
        dcc.Checklist(id="dp-tidal", options=[{"label": " Tidal current", "value": "on"}], value=[],
                      inputStyle={"marginRight": "6px"},
                      labelStyle={"fontSize": "0.82rem", "fontWeight": 600, "color": INK}),
        html.Div([
            html.Div(_field("Slack windows / day",
                            dcc.Input(id="dp-windows", type="number",
                                      value=int(params.get_float("dp_tidal_windows")), min=1, step=1,
                                      debounce=True, style=NUM)), style={"flex": "1 1 120px"}),
            html.Div(_field("Work window / tide",
                            dcc.Input(id="dp-window-min", type="number",
                                      value=params.get_float("dp_tidal_window_min"), min=1, step=1,
                                      debounce=True, style=NUM)), style={"flex": "1 1 120px"}),
        ], id="dp-tidal-fields", style={"display": "flex", "gap": "10px", "marginTop": "6px"}),
    ], style={"border": f"1px solid {LINE}", "borderRadius": "10px", "padding": "14px", "background": "#fff"})


def layout():
    return html.Div([
        reports.print_header(),
        html.Div([
            html.Button([html.Span("\u2913\u2002"), "Export to PDF"], id="dp-print-btn", n_clicks=0, style=PDF_BTN),
            html.Div(id="dp-print-sink", style={"display": "none"}),
        ], className="no-print", style={"display": "flex", "justifyContent": "flex-end"}),

        html.H3("Dive Planning"),
        html.P("Lay out a working day of subsequent dives. Pick a table, depth and bottom time; "
               "set the team, shift and tidal conditions; the Gantt below fills in on the fly. A 24 h "
               "day runs a day and a night shift, each with its own team and standby. Indicative, for "
               "commercial planning only - not for operational decompression.",
               style={"color": MUTED, "maxWidth": "76ch", "lineHeight": 1.5}),

        html.Div([
            html.Div([_scenario_panel(), _assumptions_panel(), _gas_panel()],
                     className="assump-panel no-print",
                     style={"flex": "0 0 300px", "alignSelf": "flex-start", "position": "sticky",
                            "top": "72px", "maxHeight": "calc(100vh - 96px)", "overflowY": "auto"}),
            html.Div([
                html.Div(id="dp-timing"),
                html.Div(id="dp-gantt"),
                html.Div(id="dp-totals"),
                html.Div(id="dp-gasuse"),
            ], className="diving-main", style={"flex": "1 1 auto", "minWidth": "0"}),
        ], style={"display": "flex", "gap": "18px", "marginTop": "8px", "alignItems": "flex-start"}),
        reports.print_footer(),
    ])


# --------------------------------------------------------------------------- #
# selection cascade (table -> depth -> bottom time), DVIS5-aware
# --------------------------------------------------------------------------- #
@callback(Output("dp-depth", "options"), Output("dp-depth", "value"),
          Input("dp-table", "value"), Input("dp-dvis5", "value"), prevent_initial_call=True)
def _depths(value, dvis5):
    if not value:
        return [], None
    apply_limit = bool(dvis5)
    opts = []
    for d in profiles.depths(value):
        o = {"label": _dlabel(value, d), "value": d}
        if apply_limit and profiles.dvis5_limit(value, d) is None:
            o["disabled"] = True
            o["label"] = _dlabel(value, d) + "  \u2014 SAT"
        opts.append(o)
    return opts, None


@callback(Output("dp-row", "options"), Output("dp-row", "value"),
          Input("dp-depth", "value"), Input("dp-dvis5", "value"),
          State("dp-table", "value"), prevent_initial_call=True)
def _rows(depth, dvis5, value):
    if not value or depth is None:
        return [], None
    return profiles.rows(value, depth, apply_limit=bool(dvis5)), None


@callback(Output("dp-tidal-fields", "style"), Input("dp-tidal", "value"))
def _toggle_tidal(v):
    base = {"display": "flex", "gap": "10px", "marginTop": "6px"}
    return base if v else {**base, "display": "none"}


# --------------------------------------------------------------------------- #
# main compute -> Gantt + readouts (populates on the fly)
# --------------------------------------------------------------------------- #
def _hint(msg):
    return html.Div(msg, style={"color": MUTED, "fontStyle": "italic", "fontSize": "0.88rem",
                                "padding": "24px 4px"})


def _card(title, value):
    return html.Div([
        html.Div(title, style={"fontSize": "0.7rem", "textTransform": "uppercase",
                               "letterSpacing": "0.03em", "color": MUTED}),
        html.Div(value, style={"fontSize": "1.25rem", "fontWeight": 700,
                               "fontVariantNumeric": "tabular-nums"}),
    ], style={"background": "#fff", "border": "1px solid #e5e7eb", "borderRadius": "10px",
              "padding": "10px 14px", "flex": "1 1 140px"})


@callback(
    Output("dp-timing", "children"), Output("dp-gantt", "children"),
    Output("dp-totals", "children"), Output("dp-gasuse", "children"),
    Input("dp-row", "value"), Input("dp-shift", "value"), Input("dp-start", "value"),
    Input("dp-team", "value"), Input("dp-iw", "value"), Input("dp-repeats", "value"),
    Input("dp-standby", "value"), Input("dp-tidal", "value"), Input("dp-windows", "value"),
    Input("dp-window-min", "value"), Input("dp-descent-rate", "value"), Input("dp-arrive", "value"),
    Input("dp-return", "value"), Input("dp-undress", "value"), Input("dp-turnaround", "value"),
    Input("dp-rmv-work", "value"), Input("dp-rmv-deco", "value"),
    State("dp-table", "value"), State("dp-depth", "value"),
)
def _compute(ri, shift_h, start, team, iw, repeats, standby, tidal, windows, window_min,
             desc_rate, arrive, ret, undress, turn, rmv_work, rmv_deco, value, depth):
    if not value or depth is None or ri is None:
        return "", _hint("Choose a table, depth and bottom time to lay out the day."), "", ""

    legs, unit = profiles.legs_for(value, depth, ri)
    if not legs:
        return "", _hint("No schedule for that selection."), "", ""

    bt = _bt_of(value, depth, ri)
    if bt is None:
        return "", _hint("Couldn't read the bottom time for that row."), "", ""

    water = [l for l in legs if l.get("phase") == "water"]
    surface = [l for l in legs if l.get("phase") == "surface"]
    runtime = profiles.run_minutes(water, unit)
    chamber = profiles.run_minutes(surface, unit)

    try:
        desc_rate = float(desc_rate) or 10.0
    except (TypeError, ValueError):
        desc_rate = 10.0
    descent_min = _depth_m(value, depth) / desc_rate

    def f(x, d):
        try:
            return float(x)
        except (TypeError, ValueError):
            return d

    try:
        hh, mm = str(start or "06:00").split(":")
        start_min = int(hh) * 60 + int(mm)
    except Exception:
        start_min = 360

    cfg = dict(start_min=start_min, shift_hours=int(shift_h or 12), tidal_enabled=bool(tidal),
               windows_per_day=int(windows or 4), window_min=f(window_min, 90.0),
               divers_per_shift=max(1, int(team or 8)), divers_in_water=int(iw or 2),
               repeats=max(0, int(repeats or 0)), standby_type=standby or "wet",
               bt=bt, runtime=runtime, chamber=chamber, descent_min=descent_min,
               arrive=f(arrive, 3), ret=f(ret, 3), undress=f(undress, 3), turnaround=f(turn, 15))

    plan = dpe.plan_day(cfg)
    D = plan["derived"]

    if plan["flags"]["neg_work"]:
        return "", _hint("Bottom time is too short for this depth - descent, arrive and return "
                         "leave no working time. Pick a longer bottom time."), "", ""
    if plan["flags"]["team_too_small"]:
        return "", _hint("Not enough working divers to crew a dive with this standby / divers-per-dive."), "", ""

    def r1(x):
        return f"{x:.1f}"

    chip = lambda lbl, v, col=INK: html.Span([lbl + " ", html.B(v)], style={"color": col, "marginRight": "16px"})
    timing = html.Div([
        html.Div("Per-dive timing (full dive)", style={"fontSize": "0.72rem", "textTransform": "uppercase",
                                                       "letterSpacing": "0.03em", "color": MUTED, "marginBottom": "4px"}),
        html.Div([
            chip("Descent", r1(D["descent"]) + " min"), chip("Arrive", r1(D["arrive"]) + " min"),
            chip("Work", r1(D["work"]) + " min", TEAL), chip("Return", r1(D["return"]) + " min"),
            chip("Ascent+stops", r1(D["ascent"]) + " min", "#d98a2b"), chip("Undress", r1(D["undress"]) + " min"),
            chip("Chamber", r1(D["chamber"]) + " min", "#2f9e6b"), chip("Turn-around", r1(D["turnaround"]) + " min"),
            html.Span(["│ Runtime ", html.B(r1(D["runtime"]) + " min"), " · next splash +",
                       html.B(r1(D["cycle"] - D["runtime"]) + " min")], style={"color": MUTED}),
        ], style={"fontSize": "0.85rem", "fontVariantNumeric": "tabular-nums"}),
    ], style={"background": "#fff", "border": "1px solid #e5e7eb", "borderRadius": "10px",
              "padding": "10px 14px", "marginBottom": "10px"})

    gantt = html.Div([
        dcc.Graph(figure=dpe.build_gantt_figure(plan, cfg), config={"displayModeBar": False},
                  style={"height": f"{max(240, 42 * (len(plan['dives']) + 1) + 90)}px"}),
        html.Div("Turn-around is the gap before the next splash. Chamber deco can overlap later dives "
                 "and does not delay them.", style={"fontSize": "0.72rem", "color": MUTED, "marginTop": "2px"}),
    ], style={"background": "#fff", "border": "1px solid #e5e7eb", "borderRadius": "10px",
              "padding": "12px", "marginBottom": "10px"})

    t = plan["totals"]
    totals = html.Div([
        _card("Onboard divers", str(plan["onboard"])),
        _card("Dives / day", str(t["n_dives"])),
        _card("Productive work", r1(t["work"]) + " min"),
        _card("Chamber time / day", r1(t["chamber"]) + " min"),
    ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap"})

    # ---- Dive Gas Use ----------------------------------------------------- #
    rmv_w = f(rmv_work, 40.0)
    rmv_d = f(rmv_deco, 30.0)
    gu = dpe.gas_use_day(legs, unit, t["n_dives"], rmv_w, rmv_d)
    period = "24 h" if int(shift_h or 12) == 24 else "12 h"

    def _gas_rows(rows):
        out = []
        for r in rows:
            out.append(html.Div([
                html.Span(r["label"], style={"flex": "0 0 78px", "fontWeight": 600}),
                html.Span(f"{r['litres']:,.0f} L", style={"flex": "1 1 auto", "textAlign": "right",
                                                          "fontVariantNumeric": "tabular-nums"}),
                html.Span(f"{r['quads']:.2f} quads", style={"flex": "0 0 96px", "textAlign": "right",
                                                            "color": MUTED, "fontVariantNumeric": "tabular-nums"}),
            ], style={"display": "flex", "gap": "8px", "fontSize": "0.85rem", "padding": "2px 0"}))
        return out or [html.Div("\u2014", style={"color": MUTED, "fontSize": "0.85rem"})]

    def _mix_block(title, subtitle, rows):
        return html.Div([
            html.Div(title, style={"fontWeight": 700, "fontSize": "0.85rem"}),
            html.Div(subtitle, style={"fontSize": "0.7rem", "color": MUTED, "marginBottom": "4px"}),
            *_gas_rows(rows),
        ], style={"flex": "1 1 220px", "minWidth": "200px"})

    cat = profiles.table_category(value)
    deco_sub = "surface deco: air + O\u2082" if cat == "surdo2" else "in-water: air / O\u2082 / nitrox"
    gasuse = html.Div([
        html.Div([
            html.Span("Dive gas use", style={"fontSize": "0.72rem", "textTransform": "uppercase",
                                             "letterSpacing": "0.03em", "color": MUTED}),
            html.Span(f"  per {period} \u00b7 {t['n_dives']} dives \u00b7 {rmv_w:.0f}/{rmv_d:.0f} L/min "
                      f"work/deco \u00b7 quad = 16\u00d7200 bar\u00d747 L = {dpe.QUAD_L:,} L",
                      style={"fontSize": "0.72rem", "color": MUTED}),
        ], style={"marginBottom": "8px"}),
        html.Div([
            _mix_block("Breathing mix", "bottom gas", gu["bottom"]),
            _mix_block("Deco mix", deco_sub, gu["deco"]),
        ], style={"display": "flex", "gap": "18px", "flexWrap": "wrap"}),
        html.Div([html.Span("Total ", style={"color": MUTED}),
                  html.B(f"{gu['quads_total']:.2f} quads"),
                  html.Span(f" / {period}", style={"color": MUTED})],
                 style={"marginTop": "8px", "paddingTop": "6px", "borderTop": "1px solid #f1f5f9",
                        "fontSize": "0.9rem", "fontVariantNumeric": "tabular-nums"}),
    ], style={"background": "#fff", "border": "1px solid #e5e7eb", "borderRadius": "10px",
              "padding": "10px 14px", "marginTop": "10px"})

    return timing, gantt, totals, gasuse


# --------------------------------------------------------------------------- #
# save timing assumptions (admin / edit-granted only; guarded internally)
# --------------------------------------------------------------------------- #
@callback(
    Output("dp-assump-status", "children"),
    Input("dp-assump-save", "n_clicks"),
    State("dp-descent-rate", "value"), State("dp-arrive", "value"), State("dp-return", "value"),
    State("dp-undress", "value"), State("dp-turnaround", "value"),
    prevent_initial_call=True,
)
def _save_assumptions(_n, desc, arrive, ret, undress, turn):
    if not auth.may_edit_params(auth.current_user(), MODULE):
        return html.Span("Not permitted.", style={"color": "#b91c1c"})
    mapping = {"dp_descent_rate": desc, "dp_arrive_min": arrive, "dp_return_min": ret,
               "dp_undress_min": undress, "dp_turnaround_min": turn}
    n, msg = params.set_many(mapping)
    return html.Span(msg, style={"color": TEAL if n else "#b91c1c"})


@callback(
    Output("dp-gas-status", "children"),
    Input("dp-gas-save", "n_clicks"),
    State("dp-rmv-work", "value"), State("dp-rmv-deco", "value"),
    prevent_initial_call=True,
)
def _save_gas(_n, rmv_work, rmv_deco):
    if not auth.may_edit_params(auth.current_user(), MODULE):
        return html.Span("Not permitted.", style={"color": "#b91c1c"})
    n, msg = params.set_many({"dp_rmv_working": rmv_work, "dp_rmv_deco": rmv_deco})
    return html.Span(msg, style={"color": TEAL if n else "#b91c1c"})


dash.clientside_callback(
    "function(n){ if(n){ setTimeout(function(){ window.print(); }, 60); } "
    "return window.dash_clientside.no_update; }",
    Output("dp-print-sink", "children"), Input("dp-print-btn", "n_clicks"),
    prevent_initial_call=True,
)
