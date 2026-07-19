"""
Fuel Consumption — standalone estimator, own nav section.

Expected DG fuel from the electrical load, via the admin-editable SFOC curve
(Admin -> Fuel consumption; MAN L27/38 basis). Two ways to set the load:

- DP estimate: intact-condition thruster demand at a chosen environment
  (JONSWAP quick-pick table or free values, same rescale engine as the DP
  Environment Planner) plus the DP consumer registry. Always the INTACT case
  — fuel is an expectation; failure cases are contingencies.
- Manual load: total electrical load and the number of engines online —
  independent of the DP data, for harbour/transit-style what-ifs or when the
  load is simply known.

Validated against Jul-Oct 2025 fuel monitoring (on-DP median 15.8 m3/day
reproduced at representative weather with hotel + SAT running).
"""
import dash
from dash import html, dcc, Input, Output, State, callback, ALL, ctx, no_update

from app.engines import dp_capability as dp
from app.engines import dp_env_rescale as rs
from app import dp_consumers as dcon
from app import dp_fuel, units, wind_sea

dash.register_page(__name__, path="/fuel", name="Fuel consumption",
                   category="Fuel Consumption", order=1)

MUTED = "#64748b"
ACCENT = "#0f766e"
INK = "#0f172a"
GRID = "#e2e8f0"
_CARD = {"background": "#ffffff", "border": f"1px solid {GRID}", "borderRadius": "10px",
         "padding": "14px 16px", "marginBottom": "14px"}
_LBL = {"fontSize": "12px", "color": MUTED, "marginBottom": "2px", "display": "block"}
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


def layout():
    dp_ok = rs.available() and dp.available()
    mode_opts = ([{"label": f' {m["label"]}', "value": k}
                  for k, m in dp.modes().items()] if dp_ok else [])
    return html.Div([
        html.H2("Fuel consumption", style={"color": INK, "marginBottom": "2px"}),
        html.Div("Expected DG fuel from the electrical load via the SFOC curve "
                 "(Admin \u2192 Fuel consumption). Intact condition — an "
                 "expectation, not a failure contingency.",
                 style={"color": MUTED, "fontSize": "13px", "marginBottom": "12px"}),
        html.Div([
            html.Div([
                html.Div([
                    html.Label("Load basis", style=_LBL),
                    dcc.RadioItems(
                        id="fp-basis",
                        options=[{"label": " DP estimate (intact) — environment + consumers",
                                  "value": "dp", "disabled": not dp_ok},
                                 {"label": " Manual load — total kW + engines online",
                                  "value": "manual"},
                                 {"label": " Transit — speed, distance & engines online",
                                  "value": "transit"}],
                        value="dp" if dp_ok else "manual",
                        labelStyle={"display": "block", "margin": "2px 0"},
                        style={"fontSize": "14px", "marginBottom": "10px"}),
                    # ---------------- DP-estimate inputs ----------------
                    html.Div([
                        html.Label("Operating mode", style=_LBL),
                        dcc.RadioItems(id="fp-mode", options=mode_opts,
                                       value="2split" if dp_ok else None,
                                       labelStyle={"display": "block", "margin": "2px 0"},
                                       style={"marginBottom": "8px", "fontSize": "14px"}),
                        html.Div([
                            html.Div([html.Label("Vessel heading [\u00b0T]", style=_LBL),
                                      _num("fp-heading", 0, 0, 360)], style={"flex": 1}),
                            html.Div([html.Label("Wind from [\u00b0T]", style=_LBL),
                                      _num("fp-winddir", 70, 0, 360)], style={"flex": 1}),
                        ], style={"display": "flex", "gap": "10px", "marginBottom": "8px"}),
                        html.Div([
                            html.Div([html.Label("Wind speed (1-min @ 10 m)", style=_LBL_ENV),
                                      _num("fp-wind", 8.0, 0)], style={"flex": 1}),
                            html.Div([html.Label("Current", style=_LBL_ENV),
                                      _num("fp-current", 0.8, 0, step=0.05)], style={"flex": 1}),
                            html.Div([html.Label("Hs [m]", style=_LBL_ENV),
                                      _num("fp-hs", 1.5, 0, step=0.1)], style={"flex": 1}),
                        ], style={"display": "flex", "gap": "10px", "marginBottom": "4px",
                                  "alignItems": "flex-end"}),
                        html.Div([
                            html.Span("Units:", style={"fontSize": "12px", "color": MUTED,
                                                       "marginRight": "8px"}),
                            html.Span("wind", style={"fontSize": "12px", "color": MUTED}),
                            dcc.RadioItems(id="fp-wu", options=units.WIND_UNITS, value="ms",
                                           inline=True, labelStyle={"marginRight": "8px"},
                                           style={"fontSize": "12px", "display": "inline-block",
                                                  "margin": "0 14px 0 6px"}),
                            html.Span("current", style={"fontSize": "12px", "color": MUTED}),
                            dcc.RadioItems(id="fp-cu", options=units.CUR_UNITS, value="ms",
                                           inline=True, labelStyle={"marginRight": "8px"},
                                           style={"fontSize": "12px", "display": "inline-block",
                                                  "marginLeft": "6px"}),
                        ], style={"marginBottom": "8px"}),
                        html.Label("DP power consumers", style=_LBL),
                        dcc.Checklist(
                            id="fp-consumers",
                            options=[{"label": f' {r["name"]}\u00a0\u00b7\u00a0{r["kw"]:,.0f}\u00a0kW',
                                      "value": r["id"]} for r in dcon.rows()],
                            value=[r["id"] for r in dcon.rows() if r["default_on"]],
                            labelStyle={"display": "block", "margin": "2px 0"},
                            style={"fontSize": "13px", "marginBottom": "8px"}),
                    ], id="fp-dp-section"),
                    # ---------------- manual inputs ----------------
                    html.Div([
                        html.Div([
                            html.Div([html.Label("Total electrical load [kW]", style=_LBL),
                                      _num("fp-total", 3000, 0, step=50)], style={"flex": 1.4}),
                            html.Div([html.Label("Engines online", style=_LBL),
                                      dcc.Dropdown(id="fp-ndg",
                                                   options=[{"label": f"{n} DG", "value": n}
                                                            for n in (1, 2, 3, 4, 5)],
                                                   value=4, clearable=False,
                                                   style={"fontSize": "14px"})],
                                     style={"flex": 1}),
                        ], style={"display": "flex", "gap": "10px", "marginBottom": "8px"}),
                        html.Div("Load split evenly over the engines online. "
                                 "4 DG = 2-split, 5 DG = 3-split; fewer for "
                                 "harbour / closed-bus configurations.",
                                 style={"fontSize": "11px", "color": MUTED}),
                    ], id="fp-manual-section", style={"display": "none"}),
                    # ---------------- transit inputs ----------------
                    html.Div([
                        html.Div([
                            html.Div([html.Label("Speed [kn]", style=_LBL),
                                      _num("fp-tr-speed", 8.0, 0, 14, 0.5)],
                                     style={"flex": 1}),
                            html.Div([html.Label("Engines online", style=_LBL),
                                      dcc.Dropdown(id="fp-tr-ndg",
                                                   options=[{"label": f"{n} DG", "value": n}
                                                            for n in (2, 3, 4, 5)],
                                                   value=2, clearable=False,
                                                   style={"fontSize": "14px"})],
                                     style={"flex": 1}),
                        ], style={"display": "flex", "gap": "10px", "marginBottom": "8px"}),
                        html.Div([
                            html.Div([html.Label("Sea margin [%]", style=_LBL),
                                      _num("fp-tr-margin", 15, 0, 50, 5)],
                                     style={"flex": 1}),
                            html.Div([html.Label("Distance [nm] (optional)", style=_LBL),
                                      _num("fp-tr-dist", None, 0)],
                                     style={"flex": 1}),
                        ], style={"display": "flex", "gap": "10px", "marginBottom": "8px"}),
                        html.Div("Propulsion scales with speed cubed from the "
                                 "service point in Admin → Fuel consumption "
                                 "(load-balance transit column), plus the "
                                 "transit auxiliary load. Sea margin covers "
                                 "wind/waves/fouling on the propulsion share; "
                                 "0% reproduces the calm-water Oct 2025 "
                                 "transit actuals at ≈ 8 kn.",
                                 style={"fontSize": "11px", "color": MUTED}),
                    ], id="fp-transit-section", style={"display": "none"}),
                ], style=_CARD),
                html.Div(id="fp-result"),
            ], style={"flex": "0 0 440px"}),
            html.Div([
                html.Div([
                    html.B("JONSWAP wind-sea reference — fetch-limited Hs",
                           style={"fontSize": "13px"}),
                    html.Div("Click a cell to use that wind + Hs (DP-estimate basis).",
                             style={"fontSize": "12px", "color": MUTED,
                                    "margin": "4px 0 8px"}),
                    _ws_table(),
                    dcc.Store(id="fp-ws-sel", data=None),
                    html.Div(id="fp-ws-note",
                             style={"fontSize": "12px", "color": ACCENT,
                                    "fontWeight": 600, "marginTop": "6px"}),
                ], style=_CARD, id="fp-ws-card"),
                html.Div([
                    html.B("Method", style={"fontSize": "13px"}),
                    html.Div("SFOC piecewise-linear through the Admin anchors "
                             "(electrical basis, MAN L27/38 project guide; flat "
                             "below 25% with a low-load warning). DP-estimate "
                             "basis: intact-condition Appendix E thruster loads "
                             "scaled by the propeller law at the entered "
                             "environment, plus the selected consumers, per the "
                             "as-built bus feeding (2245-880-201). DP electrical "
                             "load only — no boilers. Transit basis: propulsion "
                             "\u221d speed\u00b3 from the load-balance service "
                             "point (2\u00d72,163 kW @ service speed, Admin \u2192 "
                             "Fuel consumption), plus transit auxiliaries and a "
                             "sea-margin factor on the propulsion share. "
                             "Validated against Jul\u2013Oct 2025 fuel "
                             "monitoring: on-DP median 15.8 m\u00b3/day "
                             "reproduced at representative weather with "
                             "hotel + SAT running; transit days (11.4\u201312.0 "
                             "m\u00b3/day) reproduced at \u2248 8 kn calm water; "
                             "port days (\u2248 5 m\u00b3/day) match the "
                             "auxiliary-only base.",
                             style={"fontSize": "12px", "color": MUTED,
                                    "marginTop": "4px"}),
                ], style=_CARD),
            ], style={"flex": 1, "minWidth": "380px"}),
        ], style={"display": "flex", "gap": "14px", "flexWrap": "wrap"}),
    ], style={"maxWidth": "1100px"})


@callback(Output("fp-dp-section", "style"), Output("fp-manual-section", "style"),
          Output("fp-transit-section", "style"), Output("fp-ws-card", "style"),
          Input("fp-basis", "value"))
def _toggle(basis):
    show = lambda on: ({} if on else {"display": "none"})
    ws_style = {**_CARD} if basis == "dp" else {**_CARD, "display": "none"}
    return (show(basis == "dp"), show(basis == "manual"),
            show(basis == "transit"), ws_style)


@callback(Output({"type": "fp-ws-cell", "w": ALL, "x": ALL}, "style"),
          Output("fp-ws-sel", "data"), Output("fp-ws-note", "children"),
          Output("fp-wind", "value"), Output("fp-hs", "value"),
          Input({"type": "fp-ws-cell", "w": ALL, "x": ALL}, "n_clicks"),
          Input("fp-wind", "value"), Input("fp-hs", "value"),
          State("fp-ws-sel", "data"), State("fp-wu", "value"),
          prevent_initial_call=True)
def _ws_select(clicks, wind, hs, sel, wu):
    def styles(s):
        return [(_CELL_SEL if (s and w == s.get("w") and x == s.get("x")) else _CELL)
                for w in _WS_WINDS for x in _WS_FETCH]

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


def _result_card(fuel, context_lines):
    rows = [html.Div(
        f'{b["bus"].upper()} — {b["n_dg"]}\u00d7DG @ {b["per_dg_frac"]*100:.0f}% '
        f'({b["per_dg_kw"]:,.0f} kW/DG) \u2192 SFOC {b["sfoc"]:.0f} g/kWh \u2192 '
        f'{b["kg_h"]:,.0f} kg/h',
        style={"fontSize": "13px", "marginBottom": "3px"}) for b in fuel["buses"]]
    return html.Div([
        html.B("Expected fuel consumption", style={"fontSize": "14px"}),
        *[html.Div(t, style={"fontSize": "12px", "color": MUTED,
                             "margin": "4px 0"}) for t in context_lines],
        *rows,
        html.Div(f'Total: {fuel["total_kg_h"]:,.0f} kg/h \u2248 '
                 f'{fuel["t_day"]:.1f} t/day \u2248 {fuel["m3_day"]:.1f} m\u00b3/day',
                 style={"fontWeight": 700, "fontSize": "15px", "margin": "6px 0 4px"}),
        *[html.Div(w, style={"fontSize": "12px", "color": "#92400e"})
          for w in fuel["warnings"]],
    ], style=_CARD)


@callback(Output("fp-result", "children"),
          Input("fp-basis", "value"), Input("fp-mode", "value"),
          Input("fp-heading", "value"), Input("fp-winddir", "value"),
          Input("fp-wind", "value"), Input("fp-current", "value"),
          Input("fp-hs", "value"), Input("fp-wu", "value"), Input("fp-cu", "value"),
          Input("fp-consumers", "value"),
          Input("fp-total", "value"), Input("fp-ndg", "value"),
          Input("fp-tr-speed", "value"), Input("fp-tr-ndg", "value"),
          Input("fp-tr-margin", "value"), Input("fp-tr-dist", "value"))
def _update(basis, mode, heading, winddir, wind, current, hs, wu, cu,
            consumers, total_kw, ndg, tr_speed, tr_ndg, tr_margin, tr_dist):
    if basis == "transit":
        est = dp_fuel.transit_estimate(tr_speed, int(tr_ndg or 2),
                                       tr_margin, tr_dist)
        tr = est["transit"]
        ctx_lines = [
            f'Transit at {tr["speed_kn"]:.1f} kn: propulsion '
            f'{tr["prop_kw"]:,.0f} kW (cube law incl. {tr["sea_margin_pct"]:.0f}% '
            f'sea margin) + auxiliaries {tr["aux_kw"]:,.0f} kW = '
            f'{tr["total_kw"]:,.0f} kW over {int(tr_ndg or 2)} DG.']
        extra = []
        if tr.get("m3_per_100nm"):
            extra.append(html.Div(
                f'Economy: ≈ {tr["m3_per_100nm"]:.1f} m³ per 100 nm',
                style={"fontSize": "13px", "marginTop": "4px"}))
        if tr.get("voyage_m3") is not None:
            extra.append(html.Div(
                f'Voyage {tr["distance_nm"]:,.0f} nm: {tr["hours"]:.1f} h '
                f'→ {tr["voyage_m3"]:.1f} m³ ({tr["voyage_t"]:.1f} t)',
                style={"fontWeight": 700, "fontSize": "14px", "marginTop": "2px"}))
        # eco-speed sweep
        hdr = html.Tr([html.Th(t, style={"fontSize": "11px", "color": MUTED,
                                         "padding": "2px 8px"})
                       for t in ("kn", "m³/day", "m³/100 nm")])
        rows = [hdr]
        for v in (6, 7, 8, 9, 10, 11, 12):
            e = dp_fuel.transit_estimate(v, int(tr_ndg or 2), tr_margin)
            rows.append(html.Tr([html.Td(f"{v}", style={"padding": "1px 8px",
                                                        "fontSize": "12px"}),
                                 html.Td(f'{e["m3_day"]:.1f}',
                                         style={"padding": "1px 8px",
                                                "fontSize": "12px"}),
                                 html.Td(f'{e["transit"]["m3_per_100nm"]:.1f}',
                                         style={"padding": "1px 8px",
                                                "fontSize": "12px"})]))
        extra.append(html.Div([
            html.Div("Speed sweep (same engines & margin):",
                     style={"fontSize": "11px", "color": MUTED,
                            "margin": "8px 0 2px"}),
            html.Table(rows)]))
        card = _result_card(est, ctx_lines)
        card.children.extend(extra)
        return card
    if basis == "manual" or not (rs.available() and dp.available()):
        fuel = dp_fuel.estimate_uniform(float(total_kw or 0.0), int(ndg or 1))
        return _result_card(fuel, [
            f"Manual basis: {float(total_kw or 0):,.0f} kW over {int(ndg or 1)} DG."])
    if not mode:
        return None
    wind_ms = units.to_ms(float(wind or 0.0), wu or "ms")
    cur_ms = max(units.to_ms(float(current or 0.0), cu or "ms"), 0.0)
    hs_m = max(float(hs or 0.0), 0.0)
    inc = (float(winddir or 0.0) - float(heading or 0.0)) % 360.0
    fuel_case = ("All Thrusters Active"
                 if "All Thrusters Active" in rs.cases(mode) else rs.cases(mode)[0])
    thr, s = rs.thruster_loads_est(mode, fuel_case, inc, wind_ms, cur_ms, hs_m)
    dgs = dp.modes()[mode].get("dgs_per_bus", {})
    loads, warns, tot = dcon.bus_loads(consumers or [], dgs)
    panel = rs.power_panel_est(mode, thr, loads)
    fuel = dp_fuel.estimate(panel)
    fuel["warnings"] = list(fuel["warnings"]) + warns
    return _result_card(fuel, [
        f"Intact condition at wind {wind_ms:.1f} m/s / current {cur_ms:.2f} m/s / "
        f"Hs {hs_m:.1f} m, incidence {inc:.0f}\u00b0 "
        f"(thrust utilisation s = {s*100:.0f}%); consumers {tot:,.0f} kW."])
