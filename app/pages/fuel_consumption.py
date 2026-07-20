"""
Fuel Consumption — four operating states, each its own section with its own
consumer selection, all printed together on one tender sheet.

- DP operations: intact-condition thruster demand at the chosen environment
  (JONSWAP quick-pick table or free values), 2-/3-split mode, DP consumer
  registry with as-built bus feeding. Always the INTACT case — fuel is an
  expectation, failure cases are contingencies.
- Transit: propulsion ∝ speed³ from the admin service point (load-balance
  transit column) with a sea-margin factor, plus the consumers selected for
  the passage (e.g. with or without divers in SAT).
- Anchorage / In port: auxiliary-only states from the selected consumers;
  the number of DGs is selected automatically from the load (1 DG until the
  PMS 85% criterion requires a second).

Validated against Jul-Oct 2025 fuel monitoring: on-DP median 15.8 m3/day at
representative weather with hotel + SAT; transit days 11.4-12.0 m3/day at
~8 kn calm; port days ~5.0 m3/day against the hotel-only base.
"""
import math

import dash
from dash import html, dcc, Input, Output, State, callback, ALL, ctx, no_update

from app.engines import dp_capability as dp
from app.engines import dp_env_rescale as rs
from app import dp_consumers as dcon
from app import dp_fuel, units, wind_sea, reports

dash.register_page(__name__, path="/fuel", name="Fuel consumption",
                   category="Fuel Consumption", order=1)

MUTED = "#64748b"
ACCENT = "#0f766e"
INK = "#0f172a"
GRID = "#e2e8f0"
BLUE = "#1d4ed8"
DG_KW = 2851.0
PMS_LIMIT = 0.85
_CARD = {"background": "#ffffff", "border": f"1px solid {GRID}",
         "borderRadius": "10px", "padding": "14px 16px", "marginBottom": "14px"}
_LBL = {"fontSize": "12px", "color": MUTED, "marginBottom": "2px",
        "display": "block"}
_LBL_ENV = {**_LBL, "minHeight": "28px"}
_NUM = {"width": "100%", "boxSizing": "border-box"}

_WS_WINDS = (4, 6, 8, 10, 12, 15, 20, 25)
_WS_FETCH = (20, 50, 100, 200, 400)
_CELL = {"width": "100%", "border": f"1px solid {GRID}", "background": "#f8fafc",
         "borderRadius": "6px", "padding": "4px 2px", "cursor": "pointer",
         "fontSize": "12.5px"}
_CELL_SEL = {**_CELL, "background": ACCENT, "color": "#fff",
             "border": f"1px solid {ACCENT}", "fontWeight": 700}


def _num(cid, value, mi=None, ma=None, step="any"):
    return dcc.Input(id=cid, type="number", value=value, min=mi, max=ma,
                     step=step, debounce=True, style=_NUM)


def _consumers(cid, default_names=("Hotel",)):
    rows = dcon.rows()
    return dcc.Checklist(
        id=cid,
        options=[{"label": f' {r["name"]}\u00a0\u00b7\u00a0{r["kw"]:,.0f}\u00a0kW',
                  "value": r["id"]} for r in rows],
        value=[r["id"] for r in rows
               if any(r["name"].startswith(n) for n in default_names)],
        labelStyle={"display": "block", "margin": "2px 0"},
        style={"fontSize": "13px", "marginBottom": "6px"})


def _consumer_total(selected):
    sel = set(selected or [])
    return sum(r["kw"] for r in dcon.rows() if r["id"] in sel)


def _auto_ndg(total_kw):
    """Smallest DG count keeping per-DG load within the PMS 85% criterion."""
    return max(1, math.ceil(max(float(total_kw), 0.0) / (DG_KW * PMS_LIMIT)))


def _ws_table():
    th = {"fontSize": "11.5px", "color": MUTED, "padding": "4px 6px",
          "textAlign": "center", "fontWeight": 600}
    rows = [html.Tr([html.Th("wind \\ fetch", style=th)] +
                    [html.Th(f"{x} km", style=th) for x in _WS_FETCH])]
    for w in _WS_WINDS:
        cells = [html.Td(f"{w} m/s", style={**th, "textAlign": "right"})]
        for x in _WS_FETCH:
            hs = wind_sea.hs_fetch_m(w, x)
            cells.append(html.Td(html.Button(
                f"{hs:.1f} m", id={"type": "fp-ws-cell", "w": w, "x": x},
                n_clicks=0, style=_CELL,
                title=f"wind {w} m/s, Hs {hs:.1f} m, fetch {x} km"),
                style={"padding": "2px 3px"}))
        rows.append(html.Tr(cells))
    return html.Table(rows, style={"width": "100%", "borderCollapse": "collapse"})


def _section_title(txt):
    return html.B(txt, style={"fontSize": "14px", "display": "block",
                              "marginBottom": "6px"})


def layout():
    dp_ok = rs.available() and dp.available()
    mode_opts = ([{"label": f' {m["label"]}', "value": k}
                  for k, m in dp.modes().items()] if dp_ok else [])
    return html.Div([
        reports.print_header(),
        html.Div([
            html.Button([html.Span("\u2913\u2002"), "Print fuel sheet"],
                        id="fp-print-btn", n_clicks=0,
                        style={"border": f"1px solid {GRID}", "background": "#fff",
                               "borderRadius": "8px", "padding": "7px 14px",
                               "cursor": "pointer", "fontSize": "13px"}),
            html.Div(id="fp-print-sink", style={"display": "none"}),
        ], className="no-print", style={"display": "flex",
                                        "justifyContent": "flex-end",
                                        "marginBottom": "6px"}),
        html.H2("Fuel consumption", style={"color": INK, "marginBottom": "2px"}),
        html.Div("Expected DG fuel per operating state via the SFOC curve "
                 "(Admin \u2192 Fuel consumption). Each section selects its own "
                 "consumers; the printed sheet combines all four states.",
                 style={"color": MUTED, "fontSize": "13px",
                        "marginBottom": "10px"}),
        html.Div([
            html.Label("Project / voyage reference (appears in the printed "
                       "sheet title)", style=_LBL),
            dcc.Input(id="fp-ref", type="text", debounce=True,
                      placeholder="e.g. tender ref, voyage, client",
                      style={"width": "100%", "boxSizing": "border-box"}),
        ], style={**_CARD, "maxWidth": "560px"}, className="no-print"),

        html.Div([
            # ---------------- DP section ----------------
            html.Div([
                html.Div([
                    _section_title("DP operations"),
                    html.Label("Operating mode", style=_LBL),
                    dcc.RadioItems(id="fp-mode", options=mode_opts,
                                   value="2split" if dp_ok else None,
                                   labelStyle={"display": "block",
                                               "margin": "2px 0"},
                                   style={"marginBottom": "8px",
                                          "fontSize": "14px"}),
                    html.Div([
                        html.Div([html.Label("Vessel heading [\u00b0T]",
                                             style=_LBL),
                                  _num("fp-heading", 0, 0, 360)],
                                 style={"flex": 1}),
                        html.Div([html.Label("Wind from [\u00b0T]", style=_LBL),
                                  _num("fp-winddir", 70, 0, 360)],
                                 style={"flex": 1}),
                    ], style={"display": "flex", "gap": "10px",
                              "marginBottom": "8px"}),
                    html.Div([
                        html.Div([html.Label("Wind speed (1-min @ 10 m)",
                                             style=_LBL_ENV),
                                  _num("fp-wind", 8.0, 0)], style={"flex": 1}),
                        html.Div([html.Label("Current", style=_LBL_ENV),
                                  _num("fp-current", 0.8, 0, step=0.05)],
                                 style={"flex": 1}),
                        html.Div([html.Label("Hs [m]", style=_LBL_ENV),
                                  _num("fp-hs", 1.5, 0, step=0.1)],
                                 style={"flex": 1}),
                    ], style={"display": "flex", "gap": "10px",
                              "marginBottom": "4px",
                              "alignItems": "flex-end"}),
                    html.Div([
                        html.Span("Units:", style={"fontSize": "12px",
                                                   "color": MUTED,
                                                   "marginRight": "8px"}),
                        html.Span("wind", style={"fontSize": "12px",
                                                 "color": MUTED}),
                        dcc.RadioItems(id="fp-wu", options=units.WIND_UNITS,
                                       value="ms", inline=True,
                                       labelStyle={"marginRight": "8px"},
                                       style={"fontSize": "12px",
                                              "display": "inline-block",
                                              "margin": "0 14px 0 6px"}),
                        html.Span("current", style={"fontSize": "12px",
                                                    "color": MUTED}),
                        dcc.RadioItems(id="fp-cu", options=units.CUR_UNITS,
                                       value="ms", inline=True,
                                       labelStyle={"marginRight": "8px"},
                                       style={"fontSize": "12px",
                                              "display": "inline-block",
                                              "marginLeft": "6px"}),
                    ], style={"marginBottom": "8px"}),
                    html.Label("DP power consumers", style=_LBL),
                    dcc.Checklist(
                        id="fp-consumers",
                        options=[{"label": f' {r["name"]}\u00a0\u00b7\u00a0'
                                           f'{r["kw"]:,.0f}\u00a0kW',
                                  "value": r["id"]} for r in dcon.rows()],
                        value=[r["id"] for r in dcon.rows() if r["default_on"]],
                        labelStyle={"display": "block", "margin": "2px 0"},
                        style={"fontSize": "13px", "marginBottom": "6px"}),
                    html.Div(id="fp-dp-out"),
                ], style=_CARD),
            ], style={"flex": "0 0 440px"}),
            html.Div([
                html.Div([
                    html.B("JONSWAP wind-sea reference — fetch-limited Hs",
                           style={"fontSize": "13px"}),
                    html.Div("Click a cell to use that wind + Hs in the DP "
                             "section.",
                             style={"fontSize": "12px", "color": MUTED,
                                    "margin": "4px 0 8px"}),
                    _ws_table(),
                    dcc.Store(id="fp-ws-sel", data=None),
                    dcc.Store(id="fp-wu-prev", data="ms"),
                    dcc.Store(id="fp-cu-prev", data="ms"),
                    html.Div(id="fp-ws-note",
                             style={"fontSize": "12px", "color": ACCENT,
                                    "fontWeight": 600, "marginTop": "6px"}),
                ], style=_CARD, id="fp-ws-card", className="no-print"),
                html.Div([
                    html.B("Method", style={"fontSize": "13px"}),
                    html.Div("SFOC piecewise-linear through the Admin anchors "
                             "(electrical basis, MAN L27/38 project guide; "
                             "flat below 25% with a low-load warning). DP: "
                             "intact-condition Appendix E thruster loads "
                             "scaled by the propeller law, plus consumers per "
                             "the as-built bus feeding (2245-880-201). "
                             "Transit: propulsion \u221d speed\u00b3 from the "
                             "load-balance service point plus a sea margin, "
                             "plus the selected consumers. Anchorage / port: "
                             "selected consumers only, DG count automatic "
                             "against the PMS 85% criterion. Validated "
                             "against Jul\u2013Oct 2025 fuel monitoring "
                             "(on-DP median 15.8 m\u00b3/day; transit "
                             "11.4\u201312.0 m\u00b3/day at \u2248 8 kn; port "
                             "\u2248 5.0 m\u00b3/day).",
                             style={"fontSize": "12px", "color": MUTED,
                                    "marginTop": "4px"}),
                ], style=_CARD, className="no-print"),
            ], style={"flex": 1, "minWidth": "380px"}),
        ], style={"display": "flex", "gap": "14px", "flexWrap": "wrap"}),

        # ---------------- Transit section ----------------
        html.Div([
            _section_title("Transit"),
            html.Div([
                html.Div([html.Label("Speed [kn]", style=_LBL),
                          _num("fp-tr-speed", 10.0, 0, 14, 0.5)],
                         style={"flex": 1}),
                html.Div([html.Label("Engines online", style=_LBL),
                          dcc.Dropdown(id="fp-tr-ndg",
                                       options=[{"label": f"{n} DG", "value": n}
                                                for n in (2, 3, 4, 5)],
                                       value=2, clearable=False,
                                       style={"fontSize": "14px"})],
                         style={"flex": 1}),
                html.Div([html.Label("Sea margin [%]", style=_LBL),
                          _num("fp-tr-margin", 15, 0, 50, 5)],
                         style={"flex": 1}),
                html.Div([html.Label("Distance [nm] (optional)", style=_LBL),
                          _num("fp-tr-dist", None, 0)], style={"flex": 1}),
            ], style={"display": "flex", "gap": "10px", "marginBottom": "8px",
                      "flexWrap": "wrap"}),
            html.Label("Consumers during transit (e.g. SAT manned or not)",
                       style=_LBL),
            _consumers("fp-tr-consumers"),
            html.Div(id="fp-tr-out"),
        ], style=_CARD),

        # ------------- Anchorage + Port sections -------------
        html.Div([
            html.Div([
                _section_title("At anchorage"),
                html.Label("Consumers at anchorage", style=_LBL),
                _consumers("fp-anc-consumers"),
                html.Div(id="fp-anc-out"),
            ], style={**_CARD, "flex": 1, "minWidth": "340px"}),
            html.Div([
                _section_title("In port"),
                html.Label("Consumers in port", style=_LBL),
                _consumers("fp-port-consumers"),
                html.Div(id="fp-port-out"),
            ], style={**_CARD, "flex": 1, "minWidth": "340px"}),
        ], style={"display": "flex", "gap": "14px", "flexWrap": "wrap"}),

        html.Div(id="fp-print-summary", className="print-only"),
        reports.print_footer(),
    ], style={"maxWidth": "1100px"})


# ---------------------------------------------------------- JONSWAP selection
@callback(Output({"type": "fp-ws-cell", "w": ALL, "x": ALL}, "style"),
          Output("fp-ws-sel", "data"), Output("fp-ws-note", "children"),
          Output("fp-wind", "value"), Output("fp-hs", "value"),
          Input({"type": "fp-ws-cell", "w": ALL, "x": ALL}, "n_clicks"),
          Input("fp-wind", "value"), Input("fp-hs", "value"),
          State("fp-ws-sel", "data"), State("fp-wu", "value"),
          prevent_initial_call=True)
def _ws_select(clicks, wind, hs, sel, wu):
    def styles(s):
        return [(_CELL_SEL if (s and w == s.get("w") and x == s.get("x"))
                 else _CELL) for w in _WS_WINDS for x in _WS_FETCH]

    def note(s):
        if not s:
            return None
        return (f"Environment from JONSWAP reference: wind {s['w']} m/s, "
                f"Hs {s['hs']} m — {s['x']} km fetch.")

    trig = ctx.triggered_id
    if isinstance(trig, dict) and trig.get("type") == "fp-ws-cell":
        if not any(clicks or []):
            return styles(sel), no_update, note(sel), no_update, no_update
        new = {"w": trig["w"], "x": trig["x"],
               "hs": round(wind_sea.hs_fetch_m(trig["w"], trig["x"]), 1)}
        return (styles(new), new, note(new),
                round(units.from_ms(new["w"], wu or "ms"), 2), new["hs"])
    if sel:
        try:
            match = (abs(units.to_ms(float(wind), wu or "ms") - sel["w"]) < 0.05
                     and abs(float(hs) - sel["hs"]) < 0.05)
        except (TypeError, ValueError):
            match = False
        if not match:
            return styles(None), None, None, no_update, no_update
    return styles(sel), no_update, note(sel), no_update, no_update


# Convert the displayed wind/current value when the unit selector changes —
# same behaviour as the DP pages (dpc-wu / dpe-wu). Without this the number
# keeps its magnitude and is silently reinterpreted in the new unit.
@callback(Output("fp-wind", "value", allow_duplicate=True),
          Output("fp-wu-prev", "data"),
          Input("fp-wu", "value"), State("fp-wind", "value"),
          State("fp-wu-prev", "data"), prevent_initial_call=True)
def _wind_unit_switch(unit, value, prev):
    return units.convert(value, prev or "ms", unit), unit


@callback(Output("fp-current", "value"), Output("fp-cu-prev", "data"),
          Input("fp-cu", "value"), State("fp-current", "value"),
          State("fp-cu-prev", "data"), prevent_initial_call=True)
def _cur_unit_switch(unit, value, prev):
    return units.convert(value, prev or "ms", unit), unit


# ---------------------------------------------------------- state estimators
def _dp_state(mode, heading, winddir, wind, current, hs, wu, cu, consumers):
    """(est, ctx_line, short_label) for DP intact, or (None, reason, None)."""
    if not (mode and rs.available() and dp.available()):
        return None, "select an operating mode to compute", None
    wind_ms = units.to_ms(float(wind or 0.0), wu or "ms")
    cur_ms = max(units.to_ms(float(current or 0.0), cu or "ms"), 0.0)
    hs_m = max(float(hs or 0.0), 0.0)
    inc = (float(winddir or 0.0) - float(heading or 0.0)) % 360.0
    fuel_case = ("All Thrusters Active"
                 if "All Thrusters Active" in rs.cases(mode)
                 else rs.cases(mode)[0])
    thr, s = rs.thruster_loads_est(mode, fuel_case, inc, wind_ms, cur_ms, hs_m)
    dgs = dp.modes()[mode].get("dgs_per_bus", {})
    loads, warns, tot = dcon.bus_loads(consumers or [], dgs)
    est = dp_fuel.estimate(rs.power_panel_est(mode, thr, loads))
    est["warnings"] = list(est["warnings"]) + warns
    ctx_line = (f"Intact, wind {wind_ms:.1f} m/s / current {cur_ms:.2f} m/s / "
                f"Hs {hs_m:.1f} m, incidence {inc:.0f}\u00b0 (s = "
                f"{s * 100:.0f}%); consumers {tot:,.0f} kW.")
    lab = (f"intact \u2014 {wind_ms:.1f} m/s / {cur_ms:.2f} m/s / Hs "
           f"{hs_m:.1f} m; consumers {tot:,.0f} kW "
           f"({dp.modes()[mode]['label']})")
    return est, ctx_line, lab


def _transit_state(speed, ndg, margin, dist, consumers):
    aux = _consumer_total(consumers)
    est = dp_fuel.transit_estimate(speed, int(ndg or 2), margin, dist, aux)
    tr = est["transit"]
    lab = (f'{tr["speed_kn"]:.1f} kn, {int(ndg or 2)} DG, '
           f'{tr["sea_margin_pct"]:.0f}% sea margin; consumers {aux:,.0f} kW '
           f'\u2014 {tr["total_kw"]:,.0f} kW total')
    return est, lab


def _static_state(consumers):
    total = _consumer_total(consumers)
    n = _auto_ndg(total)
    est = dp_fuel.estimate_uniform(total, n)
    lab = f"consumers {total:,.0f} kW on {n} DG (auto)"
    return est, lab, n


# ---------------------------------------------------------- result rendering
def _plant_lines(est):
    out = []
    for b in est["buses"]:
        name = "PLANT" if b["bus"] == "plant" else b["bus"].upper()
        out.append(html.Div(
            f'{name} \u2014 {b["n_dg"]}\u00d7DG @ {b["per_dg_frac"]*100:.0f}% '
            f'({b["per_dg_kw"]:,.0f} kW/DG) \u2192 SFOC {b["sfoc"]:.0f} g/kWh '
            f'\u2192 {b["kg_h"]:,.0f} kg/h',
            style={"fontSize": "13px", "marginBottom": "3px"}))
    return out


def _totals_line(est):
    return html.Div(
        f'Expected fuel consumption: {est["m3_day"]:.1f} m\u00b3/day '
        f'({est["t_day"]:.1f} t/day \u00b7 {est["total_kg_h"]:,.0f} kg/h)',
        style={"fontWeight": 700, "fontSize": "15px", "color": BLUE,
               "margin": "6px 0 2px"})


def _warn_lines(est):
    return [html.Div(w, style={"fontSize": "12px", "color": "#92400e"})
            for w in est.get("warnings", [])]


def _section_result(est, ctx_line=None, extras=()):
    if est is None:
        return html.Div(ctx_line or "\u2014",
                        style={"fontSize": "12px", "color": MUTED})
    kids = []
    if ctx_line:
        kids.append(html.Div(ctx_line, style={"fontSize": "12px",
                                              "color": MUTED,
                                              "margin": "4px 0"}))
    kids += _plant_lines(est) + [_totals_line(est)] + list(extras)
    kids += _warn_lines(est)
    return html.Div(kids, style={"borderTop": f"1px solid {GRID}",
                                 "paddingTop": "8px", "marginTop": "4px"})


def _transit_extras(est):
    tr = est["transit"]
    out = []
    if tr.get("m3_per_100nm"):
        out.append(html.Div(
            f'Economy: \u2248 {tr["m3_per_100nm"]:.1f} m\u00b3 per 100 nm',
            style={"fontSize": "13px", "marginTop": "2px"}))
    if tr.get("voyage_m3") is not None:
        out.append(html.Div(
            f'Voyage {tr["distance_nm"]:,.0f} nm: {tr["hours"]:.1f} h '
            f'\u2192 {tr["voyage_m3"]:.1f} m\u00b3 ({tr["voyage_t"]:.1f} t)',
            style={"fontWeight": 700, "fontSize": "14px", "marginTop": "2px"}))
    return out


# ---------------------------------------------------------- section callbacks
@callback(Output("fp-dp-out", "children"),
          Input("fp-mode", "value"), Input("fp-heading", "value"),
          Input("fp-winddir", "value"), Input("fp-wind", "value"),
          Input("fp-current", "value"), Input("fp-hs", "value"),
          Input("fp-wu", "value"), Input("fp-cu", "value"),
          Input("fp-consumers", "value"))
def _dp_out(mode, heading, winddir, wind, current, hs, wu, cu, consumers):
    est, ctx_line, _ = _dp_state(mode, heading, winddir, wind, current, hs,
                                 wu, cu, consumers)
    return _section_result(est, ctx_line)


@callback(Output("fp-tr-out", "children"),
          Input("fp-tr-speed", "value"), Input("fp-tr-ndg", "value"),
          Input("fp-tr-margin", "value"), Input("fp-tr-dist", "value"),
          Input("fp-tr-consumers", "value"))
def _tr_out(speed, ndg, margin, dist, consumers):
    est, _ = _transit_state(speed, ndg, margin, dist, consumers)
    tr = est["transit"]
    ctx_line = (f'Propulsion {tr["prop_kw"]:,.0f} kW (cube law incl. '
                f'{tr["sea_margin_pct"]:.0f}% sea margin) + consumers '
                f'{tr["aux_kw"]:,.0f} kW = {tr["total_kw"]:,.0f} kW.')
    return _section_result(est, ctx_line, _transit_extras(est))


@callback(Output("fp-anc-out", "children"),
          Input("fp-anc-consumers", "value"))
def _anc_out(consumers):
    est, lab, _ = _static_state(consumers)
    return _section_result(est, lab.capitalize() + ".")


@callback(Output("fp-port-out", "children"),
          Input("fp-port-consumers", "value"))
def _port_out(consumers):
    est, lab, _ = _static_state(consumers)
    return _section_result(est, lab.capitalize() + ".")


# ---------------------------------------------------------- print sheet
@callback(Output("fp-print-summary", "children"),
          Input("fp-mode", "value"), Input("fp-heading", "value"),
          Input("fp-winddir", "value"), Input("fp-wind", "value"),
          Input("fp-current", "value"), Input("fp-hs", "value"),
          Input("fp-wu", "value"), Input("fp-cu", "value"),
          Input("fp-consumers", "value"),
          Input("fp-tr-speed", "value"), Input("fp-tr-ndg", "value"),
          Input("fp-tr-margin", "value"), Input("fp-tr-dist", "value"),
          Input("fp-tr-consumers", "value"),
          Input("fp-anc-consumers", "value"),
          Input("fp-port-consumers", "value"),
          Input("fp-ref", "value"))
def _sheet(mode, heading, winddir, wind, current, hs, wu, cu, dp_cons,
           tr_speed, tr_ndg, tr_margin, tr_dist, tr_cons, anc_cons, port_cons,
           ref):
    dp_est, _, dp_lab = _dp_state(mode, heading, winddir, wind, current, hs,
                                  wu, cu, dp_cons)
    tr_est, tr_lab = _transit_state(tr_speed, tr_ndg, tr_margin, tr_dist,
                                    tr_cons)
    anc_est, anc_lab, _ = _static_state(anc_cons)
    port_est, port_lab, _ = _static_state(port_cons)

    th = {"textAlign": "left", "padding": "3px 12px 3px 0",
          "borderBottom": "1px solid #94a3b8", "fontSize": "12px"}
    td = {"padding": "3px 12px 3px 0", "borderBottom": "1px solid #e2e8f0",
          "fontSize": "12.5px", "verticalAlign": "top"}
    tdr = {**td, "textAlign": "right"}
    rows = [html.Tr([html.Th("Operating state", style=th),
                     html.Th("Basis", style=th),
                     html.Th("kg/h", style={**th, "textAlign": "right"}),
                     html.Th("t/day", style={**th, "textAlign": "right"}),
                     html.Th("m\u00b3/day (expected)",
                             style={**th, "textAlign": "right",
                                    "color": BLUE})])]

    def row(state, basis_txt, est):
        if est is None:
            rows.append(html.Tr([html.Td(html.B(state), style=td),
                                 html.Td(basis_txt, style=td)] +
                                [html.Td("\u2014", style=tdr)] * 3))
            return
        rows.append(html.Tr([
            html.Td(html.B(state), style=td),
            html.Td(basis_txt, style={**td, "maxWidth": "340px"}),
            html.Td(f'{est["total_kg_h"]:,.0f}', style=tdr),
            html.Td(f'{est["t_day"]:.1f}', style=tdr),
            html.Td(html.B(f'{est["m3_day"]:.1f}'),
                    style={**tdr, "color": BLUE})]))

    row("DP operations", dp_lab or "select an operating mode to include",
        dp_est)
    row("Transit", tr_lab, tr_est)
    row("At anchorage", anc_lab, anc_est)
    row("In port", port_lab, port_est)

    extras = _transit_extras(tr_est)
    warns = []
    for est in ([dp_est] if dp_est else []) + [tr_est, anc_est, port_est]:
        warns += est.get("warnings", [])

    title = "Fuel consumption \u2014 tender summary"
    if ref:
        title += f" \u2014 {ref}"
    return html.Div([
        html.H3(title, style={"marginBottom": "8px"}),
        html.Table(html.Tbody(rows), style={"borderCollapse": "collapse",
                                            "width": "100%"}),
        *extras,
        *[html.Div(w, style={"fontSize": "11px", "color": "#92400e",
                             "marginTop": "4px"}) for w in warns],
        html.Div("Expected values: SFOC per portal parameters (MAN L27/38 "
                 "project guide, electrical basis, excl. +5% guarantee "
                 "tolerance); DP row is the intact condition; anchorage/port "
                 "DG count automatic against the PMS 85% criterion. Validated "
                 "against Jul\u2013Oct 2025 fuel monitoring (on-DP median "
                 "15.8 m\u00b3/day, transit 11.4\u201312.0 m\u00b3/day, port "
                 "\u2248 5.0 m\u00b3/day). Estimate for planning purposes.",
                 style={"fontSize": "11px", "color": MUTED, "marginTop": "8px",
                        "maxWidth": "760px"}),
    ])


dash.clientside_callback(
    "function(n){ if(n){ setTimeout(function(){ window.print(); }, 60); } "
    "return window.dash_clientside.no_update; }",
    Output("fp-print-sink", "children"), Input("fp-print-btn", "n_clicks"),
    prevent_initial_call=True,
)
