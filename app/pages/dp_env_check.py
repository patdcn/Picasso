"""
DP Environment Planner — station-keeping capability at USER-CHOSEN current,
wind and Hs (the free-input companion to the DP Capability & Ops Check page).

Envelopes are rescaled from the Thrustmaster Appendix C force decomposition
(wind ~ V^2, current ~ Vc^2, wave drift ~ Hs^2 at the study spectral shape),
with the capability criterion that the weighted environmental wrench magnitude
stays within the study-limit wrench at that incidence. Exact at the study
basis; an engineering estimate away from it — the page says so, loudly.

The power panel shows ESTIMATED thruster demand at the user's actual
condition (Appendix E loads scaled by the propeller law), plus the DP
consumer registry per bus, rolled up per DG against the PMS 80/85% limits.

Numeric data lives only on the /data volume (engines/dp_env_rescale.py).
"""
import dash
import datetime
from dash import html, dcc, Input, Output, State, callback, ALL, ctx, no_update
import plotly.graph_objects as go

from app.engines import dp_capability as dp
from app.engines import dp_env_rescale as rs
from app import dp_consumers as dcon
from app import reports
from app import units
from app import wind_sea
from app import dpdocs

dash.register_page(__name__, path="/dp/env-planner", name="DP Environment Planner",
                   category="DP Station Keeping", order=2)

MUTED = "#64748b"
ACCENT = "#0f766e"
INK = "#0f172a"
GRID = "#e2e8f0"

STATUS_STYLE = {
    "GO":       {"bg": "#dcfce7", "fg": "#166534", "label": "GO — inside rescaled envelope"},
    "MARGINAL": {"bg": "#fef9c3", "fg": "#854d0e", "label": "MARGINAL — \u2265 80% of rescaled envelope"},
    "NO-GO":    {"bg": "#fee2e2", "fg": "#991b1b", "label": "NO-GO — exceeds rescaled envelope"},
}
BAND_COLOR = {"ok": "#16a34a", "warn": "#d97706", "limit": "#dc2626", "offline": "#94a3b8"}
AXIS_LABEL = {"surge": "surge", "sway": "sway", "yaw": "yaw", None: "\u2014"}

_CARD = {"background": "#ffffff", "border": f"1px solid {GRID}", "borderRadius": "10px",
         "padding": "14px 16px", "marginBottom": "14px"}
_LBL = {"fontSize": "12px", "color": MUTED, "marginBottom": "2px", "display": "block"}
_LBL_ENV = {**_LBL, "minHeight": "28px"}
_NUM = {"width": "100%", "boxSizing": "border-box"}


def _num_input(cid, value, mi=None, ma=None, step="any"):
    return dcc.Input(id=cid, type="number", value=value, min=mi, max=ma, step=step,
                     debounce=True, style=_NUM)


def _controls():
    mode_opts = [{"label": m["label"], "value": k} for k, m in dp.modes().items()]
    return html.Div([
        html.Label("Operating mode (FMEA Table 9-4)", style=_LBL),
        dcc.RadioItems(id="dpe-mode", options=mode_opts, value="2split",
                       labelStyle={"display": "block", "margin": "2px 0"},
                       style={"marginBottom": "10px", "fontSize": "14px"}),
        html.Label("Analysis case", style=_LBL),
        dcc.Dropdown(id="dpe-case", clearable=False,
                     style={"marginBottom": "10px", "fontSize": "13.5px"}),
        html.Div([
            html.Div([html.Label("Vessel heading [\u00b0T]", style=_LBL),
                      _num_input("dpe-heading", 0, 0, 360)], style={"flex": 1}),
            html.Div([html.Label("Wind from [\u00b0T]", style=_LBL),
                      _num_input("dpe-winddir", 70, 0, 360)], style={"flex": 1}),
        ], style={"display": "flex", "gap": "10px", "marginBottom": "8px"}),
        html.Div([
            html.Div([html.Label("Wind speed (1-min @ 10 m)", style=_LBL_ENV),
                      _num_input("dpe-wind", 10.0, 0)], style={"flex": 1}),
            html.Div([html.Label("Current — free input", style=_LBL_ENV),
                      _num_input("dpe-current", 1.0, 0, step=0.05)], style={"flex": 1}),
            html.Div([html.Label("Hs [m] — free input", style=_LBL_ENV),
                      _num_input("dpe-hs", 2.5, 0, step=0.1)], style={"flex": 1}),
        ], style={"display": "flex", "gap": "10px", "marginBottom": "4px",
                  "alignItems": "flex-end"}),
        html.Div([
            html.Span("Units:", style={"fontSize": "12px", "color": MUTED,
                                       "marginRight": "8px"}),
            html.Span("wind", style={"fontSize": "12px", "color": MUTED}),
            dcc.RadioItems(id="dpe-wu", options=units.WIND_UNITS, value="ms",
                           inline=True, labelStyle={"marginRight": "8px"},
                           style={"fontSize": "12px", "display": "inline-block",
                                  "margin": "0 14px 0 6px"}),
            html.Span("current", style={"fontSize": "12px", "color": MUTED}),
            dcc.RadioItems(id="dpe-cu", options=units.CUR_UNITS, value="ms",
                           inline=True, labelStyle={"marginRight": "8px"},
                           style={"fontSize": "12px", "display": "inline-block",
                                  "marginLeft": "6px"}),
            dcc.Store(id="dpe-wu-prev", data="ms"),
            dcc.Store(id="dpe-cu-prev", data="ms"),
        ], style={"marginBottom": "6px"}),
        html.Div("Current and Hs are free here: the envelope is rescaled from the "
                 "study's force decomposition. Exact at the study basis; an "
                 "estimate away from it (flagged in the verdict).",
                 style={"fontSize": "11px", "color": MUTED, "marginBottom": "8px"}),
        html.Label("DP power consumers — planning kW (admin-editable registry)",
                   style=_LBL),
        dcc.Checklist(
            id="dpe-consumers",
            options=[{"label": f' {r["name"]}\u00a0\u00b7\u00a0{r["kw"]:,.0f}\u00a0kW',
                      "value": r["id"]} for r in dcon.rows()],
            value=[r["id"] for r in dcon.rows() if r["default_on"]],
            labelStyle={"display": "block", "margin": "2px 0"},
            style={"fontSize": "13px", "marginBottom": "4px"}),
        html.Div(id="dpe-consumer-note",
                 style={"fontSize": "11px", "color": MUTED, "marginBottom": "8px"}),
        html.Label("Auxiliary (non-thruster) load per bus [kW] — prefilled from the "
                   "selection above, editable for ad-hoc tweaks",
                   style=_LBL),
        html.Div([
            html.Div([html.Label("Bus 1", style=_LBL), _num_input("dpe-aux1", 0, 0)], style={"flex": 1}),
            html.Div([html.Label("Bus 2", style=_LBL), _num_input("dpe-aux2", 0, 0)], style={"flex": 1}),
            html.Div([html.Label("Bus 3", style=_LBL), _num_input("dpe-aux3", 0, 0)], style={"flex": 1}),
        ], style={"display": "flex", "gap": "10px", "marginBottom": "8px"}),
        dcc.Checklist(id="dpe-overlays",
                      options=[{"label": " Study-basis envelope (published App. D)",
                                "value": "study"}],
                      value=["study"], style={"fontSize": "13px", "marginBottom": "8px"}),
        html.Label("Project / client reference (appears on the printed sheet)",
                   style=_LBL),
        dcc.Input(id="dpe-ref", type="text", debounce=True, placeholder="e.g. tender ref, field, client",
                  style={"width": "100%", "boxSizing": "border-box", "marginBottom": "8px"}),
        html.Label("Plot frame", style=_LBL),
        dcc.RadioItems(
            id="dpe-frame",
            options=[{"label": " Vessel-relative (bow up, as per study)", "value": "rel"},
                     {"label": " True bearings (North up, envelope rotated to heading)",
                      "value": "true"}],
            value="rel", labelStyle={"display": "block", "margin": "2px 0"},
            style={"fontSize": "13px"}),
    ], style=_CARD, className="no-print")


def _notice_missing():
    missing = []
    if not rs.available():
        missing.append(html.Li([html.Code("tools/dp/dp_env_rescale.json"),
                                " — Appendix C/D/E force decomposition data"]))
    if not dp.available():
        missing.append(html.Li([html.Code("tools/dp/dp_capability.json"),
                                " — electrical metadata (bus map, DG rating, PMS)"]))
    return html.Div([
        html.H2("DP Environment Planner", style={"color": INK}),
        html.Div([
            html.B("Data not installed. "),
            "This tool needs the following on the data volume (upload via "
            "Admin \u2192 Data volume files; Thrustmaster data is proprietary and "
            "is never stored in the public repository):",
            html.Ul(missing),
        ], style={**_CARD, "background": "#fef9c3"}),
    ], style={"maxWidth": "900px"})


def layout():
    if not (rs.available() and dp.available()):
        return _notice_missing()
    return html.Div([
        reports.print_header(),
        html.Div([
            html.Button([html.Span("\u2913\u2002"), "Print workability sheet"],
                        id="dpe-print-btn", n_clicks=0,
                        style={"border": f"1px solid {GRID}", "background": "#fff",
                               "borderRadius": "8px", "padding": "7px 14px",
                               "cursor": "pointer", "fontSize": "13px"}),
            html.Div(id="dpe-print-sink", style={"display": "none"}),
        ], className="no-print", style={"display": "flex", "justifyContent": "flex-end",
                                        "marginBottom": "6px"}),
        html.H2("DP Environment Planner", style={"color": INK, "marginBottom": "2px"}),
        html.Div("Station-keeping capability rescaled to your current, wind and Hs "
                 "(App. C force decomposition), with estimated power demand at your "
                 "condition including the selected consumers.",
                 style={"color": MUTED, "fontSize": "13px", "marginBottom": "12px"}),
        html.Div([
            html.Div([_controls(), html.Div(id="dpe-status")],
                     style={"flex": "0 0 420px"}),
            html.Div([
                html.Div(dcc.Graph(id="dpe-polar", config={"displaylogo": False}),
                         style=_CARD),
                html.Div(id="dpe-basis", style={**_CARD, "fontSize": "13px"}),
                _windsea_panel(),
            ], style={"flex": 1, "minWidth": "420px"}),
        ], style={"display": "flex", "gap": "14px", "flexWrap": "wrap"}),
        html.Div(id="dpe-print-summary", className="print-only"),
        html.Div(id="dpe-power"),
        _method_block(),
        reports.print_footer(),
    ], style={"maxWidth": "1200px"})




_WS_WINDS = (5, 10, 15, 20, 25)          # m/s rows
_WS_FETCH = (20, 50, 100, 200, 400)      # km columns


def _windsea_panel():
    """JONSWAP wind-sea reference: clickable wind x fetch matrix. A cell click
    copies that wind (in the selected unit), the fetch, and the fetch-limited
    Hs into the inputs — a defensible default environment when the client has
    provided no metocean, and the printed sheet then substantiates it."""
    th = {"fontSize": "11.5px", "color": MUTED, "padding": "4px 6px",
          "textAlign": "center", "fontWeight": 600}
    head = html.Tr([html.Th("wind \\ fetch", style=th)] +
                   [html.Th(f"{x} km", style=th) for x in _WS_FETCH])
    rows = [head]
    for w in _WS_WINDS:
        cells = [html.Td(f"{w} m/s", style={**th, "textAlign": "right"})]
        for x in _WS_FETCH:
            hs = wind_sea.hs_fetch_m(w, x)
            tp = wind_sea.tp_fetch_s(w, x)
            cells.append(html.Td(html.Button(
                f"{hs:.1f} m",
                id={"type": "dpe-ws-cell", "w": w, "x": x}, n_clicks=0,
                title=f"Click to use: wind {w} m/s, Hs {hs:.1f} m, "
                      f"fetch {x} km (Tp \u2248 {tp:.1f} s)",
                style={"width": "100%", "border": f"1px solid {GRID}",
                       "background": "#f8fafc", "borderRadius": "6px",
                       "padding": "4px 2px", "cursor": "pointer",
                       "fontSize": "12.5px"}),
                style={"padding": "2px 3px"}))
        rows.append(html.Tr(cells))
    return html.Div([
        html.B("JONSWAP wind-sea reference — fetch-limited Hs",
               style={"fontSize": "13px"}),
        html.Div("Click a cell to copy wind, Hs and fetch into the inputs — a "
                 "substantiated default environment when no metocean data is "
                 "provided.",
                 style={"fontSize": "12px", "color": MUTED, "margin": "4px 0 8px"}),
        html.Table(rows, style={"width": "100%", "borderCollapse": "collapse"}),
        dcc.Store(id="dpe-ws-sel", data=None),
        html.Div(id="dpe-ws-note",
                 style={"fontSize": "12px", "color": ACCENT, "fontWeight": 600,
                        "marginTop": "6px"}),
        html.Div([
            html.Div("Hs = 0.0016 \u00b7 \u221a(g\u00b7X) \u00b7 U / g   "
                     "(fetch-limited), capped at the fully developed sea "
                     "Hs = 0.0246 \u00b7 U\u00b2;  "
                     "Tp = 0.286 \u00b7 (g\u00b7X/U\u00b2)^\u2153 \u00b7 U / g.",
                     style={"fontFamily": "ui-monospace,monospace",
                            "fontSize": "11px", "marginBottom": "4px"}),
            html.Div("U = 1-min wind at 10 m [m/s], X = open-water fetch upwind "
                     "[m], g = 9.81 m/s\u00b2. JONSWAP fetch-limited growth "
                     "relations (Hasselmann et al., 1973), deep water — shallow "
                     "Gulf water limits Hs further, so these err conservative. "
                     "Fetch is directional: take the open-water distance along "
                     "the wind, not the distance to the nearest coast.",
                     style={"fontSize": "11px", "color": MUTED}),
        ], style={"marginTop": "8px"}),
    ], style=_CARD)


_WS_CELL_BASE = {"width": "100%", "border": "1px solid " + GRID,
                 "background": "#f8fafc", "borderRadius": "6px",
                 "padding": "4px 2px", "cursor": "pointer", "fontSize": "12.5px"}
_WS_CELL_SEL = {**_WS_CELL_BASE, "background": ACCENT, "color": "#ffffff",
                "border": "1px solid " + ACCENT, "fontWeight": 700}


def _ws_styles(sel):
    return [(_WS_CELL_SEL if (sel and w == sel.get("w") and x == sel.get("x"))
             else _WS_CELL_BASE)
            for w in _WS_WINDS for x in _WS_FETCH]


def _ws_note(sel):
    if not sel:
        return None
    return (f"Environment from JONSWAP reference: wind {sel['w']} m/s, "
            f"Hs {sel['hs']} m — calculated with {sel['x']} km fetch.")


@callback(Output({"type": "dpe-ws-cell", "w": ALL, "x": ALL}, "style"),
          Output("dpe-ws-sel", "data"),
          Output("dpe-ws-note", "children"),
          Output("dpe-wind", "value", allow_duplicate=True),
          Output("dpe-hs", "value"),
          Input({"type": "dpe-ws-cell", "w": ALL, "x": ALL}, "n_clicks"),
          Input("dpe-wind", "value"), Input("dpe-hs", "value"),
          State("dpe-ws-sel", "data"), State("dpe-wu", "value"),
          prevent_initial_call=True)
def _ws_select(clicks, wind, hs, sel, wu):
    """Cell click: adopt that (wind, Hs, fetch), highlight the cell, note it.
    Manual edit of wind or Hs afterwards: clear highlight and note. The
    programmatic write-back from a click re-enters here matching the
    selection, so it does not self-clear; unit switches are compared in m/s
    with rounding tolerance for the same reason."""
    trig = ctx.triggered_id
    if isinstance(trig, dict) and trig.get("type") == "dpe-ws-cell":
        if not any(clicks or []):
            return _ws_styles(sel), no_update, _ws_note(sel), no_update, no_update
        new = {"w": trig["w"], "x": trig["x"],
               "hs": round(wind_sea.hs_fetch_m(trig["w"], trig["x"]), 1)}
        return (_ws_styles(new), new, _ws_note(new),
                round(units.from_ms(new["w"], wu or "ms"), 2), new["hs"])
    # wind/hs edited: keep the selection only while values still match it
    if sel:
        try:
            wind_ms = units.to_ms(float(wind), wu or "ms")
            match = (abs(wind_ms - sel["w"]) < 0.05
                     and abs(float(hs) - sel["hs"]) < 0.05)
        except (TypeError, ValueError):
            match = False
        if not match:
            return _ws_styles(None), None, None, no_update, no_update
    return _ws_styles(sel), no_update, _ws_note(sel), no_update, no_update


def _method_block():
    prov = html.Ul([html.Li(dpdocs.linkify(p), style={"marginBottom": "3px"})
                    for p in rs.provenance()],
                   style={"fontSize": "12px", "color": MUTED, "paddingLeft": "18px"})
    return html.Div([
        html.B("Method & use limits", style={"fontSize": "13px"}),
        html.Div([
            "Wind force scales with V\u00b2 (coefficient calibrated at the study's "
            "limiting wind), current with Vc\u00b2, wave drift with Hs\u00b2 at the "
            "study spectral shape (Tp not rescaled). Capability criterion: the "
            "weighted environmental wrench magnitude (surge, sway, yaw/55 m) stays "
            "within the study-limit wrench at that incidence. This reproduces the "
            "published envelopes exactly at the study basis; away from it the result "
            "is an engineering estimate whose uncertainty grows with the deviation. "
            "Thruster power below the limit follows the propeller law "
            "(App. E \u00d7 s^1.5). Power limitation, thrust degradation and "
            "footprint effects are not modelled. This page supports planning only — "
            "the ASOG and the DPO's judgement remain leading.",
        ], style={"fontSize": "12px", "color": MUTED, "margin": "6px 0"}),
        prov,
    ], style=_CARD)


# ------------------------------------------------------------------ callbacks

@callback(Output("dpe-case", "options"), Output("dpe-case", "value"),
          Input("dpe-mode", "value"))
def _cases(mode):
    if not rs.available():
        return [], None
    cs = rs.cases(mode)
    opts = [{"label": rs.WORST_LABEL, "value": rs.WORST}]
    opts += [{"label": c, "value": c} for c in cs]
    return opts, rs.WORST


@callback(Output("dpe-aux1", "value"), Output("dpe-aux2", "value"),
          Output("dpe-aux3", "value"), Output("dpe-consumer-note", "children"),
          Input("dpe-consumers", "value"), Input("dpe-mode", "value"))
def _prefill_aux(selected, mode):
    if not (dp.available() and mode):
        return 0, 0, 0, None
    dgs_per_bus = dp.modes()[mode].get("dgs_per_bus", {})
    loads, warns, total = dcon.bus_loads(selected or [], dgs_per_bus)
    note = [html.Span(
        f"Selected {total:,.0f} kW \u2192 Bus 1 {loads['bus1']:,.0f} / "
        f"Bus 2 {loads['bus2']:,.0f} / Bus 3 {loads['bus3']:,.0f} kW. "
        "Assignments per El. Load Balance 2245-880-201 (PS/SB pairs on "
        "Bus 1+3); \u2018split\u2019 shares over the live buses weighted by "
        "running DGs.")]
    for w in warns:
        note.append(html.Div(w, style={"color": "#991b1b"}))
    return (round(loads["bus1"]), round(loads["bus2"]), round(loads["bus3"]),
            note)


def _case_display(case, res=None):
    if case == rs.WORST:
        s = rs.WORST_LABEL
        if res and res.get("case_used"):
            s += f' — governing: {res["case_used"]}'
        return s
    return case


def _print_summary(mode, case, res, wind, winddir, heading, current, hs, aux,
                   ref, ws_sel=None):
    """Study-style summary table for the printed workability sheet."""
    mm = dp.mode_meta(mode)
    b = res["basis"]
    angs, vals = rs.envelope(mode, case, current, hs)
    mn = min(vals[:-1])
    mn_ang = angs[vals.index(mn)]
    aux_total = sum(float(v or 0) for v in aux.values())
    st = STATUS_STYLE[res["status"]]
    rows = [
        ("Vessel", "DSV Picasso"),
        ("Operating mode", dp.modes()[mode]["label"]),
        ("Analysis case", _case_display(case, res)),
        ("Current speed", f"{current:.2f} m/s (collinear)"),
        ("Significant wave height (Hs)", f"{hs:.1f} m"),
        ("Wave spectrum", f'JONSWAP, Tp {b["tp_s"]:.1f} s (study basis, not rescaled)'),
    ]
    if ws_sel:
        rows.append(("Environment basis",
                     f'JONSWAP fetch-limited wind sea \u2014 wind {ws_sel["w"]} m/s, '
                     f'Hs {ws_sel["hs"]} m at {ws_sel["x"]} km fetch (reference '
                     "table; no client metocean provided)"))
    rows += [
        ("Min capability wind speed", f"{mn:.2f} m/s ({mn * rs.MS_TO_KN:.0f} kn)"),
        ("Min capability angle", f"{mn_ang}\u00b0 relative"),
        ("Assessed wind / direction",
         f'{res["wind_ms"]:.1f} m/s from {winddir % 360:.0f}\u00b0T '
         f'(heading {heading % 360:.0f}\u00b0T, incidence {res["incidence_deg"]:.0f}\u00b0)'),
        ("Wind limit at assessed incidence",
         f'{res["limit_ms"]:.1f} m/s \u2014 margin {res["margin_ms"]:+.1f} m/s'),
        ("Verdict", st["label"]),
        ("Selected DP consumers", f"{aux_total:,.0f} kW "
         f'(Bus 1 {float(aux["bus1"] or 0):,.0f} / Bus 2 {float(aux["bus2"] or 0):,.0f} / '
         f'Bus 3 {float(aux["bus3"] or 0):,.0f} kW)'),
        ("Capability basis",
         f'{mm["study_title"]} \u2014 {mm["study_ref"]}; envelopes rescaled from the '
         f'study basis (current {b["current_ms"]:.2f} m/s, Hs {b["hs_m"]:.1f} m)'),
        ("Advisories", " ".join(res["warnings"]) if res["warnings"] else "none"),
        ("Reference", (ref or "\u2014")),
        ("Generated", datetime.date.today().isoformat() + " \u00b7 DSV Picasso Engineering Portal"),
    ]
    trs = [html.Tr([
        html.Td(k, style={"padding": "3px 10px 3px 0", "color": MUTED,
                          "whiteSpace": "nowrap", "verticalAlign": "top"}),
        html.Td(v, style={"padding": "3px 0", "fontWeight": 600}),
    ]) for k, v in rows]
    note = ("Rescaled workability estimate derived from the Thrustmaster capability "
            "studies; exact at the study basis, an engineering estimate away from it. "
            "Estimated capabilities do not act as a guarantee of station-keeping in the "
            "given environmental conditions. Indicative, for commercial planning only; "
            "operational limits are governed by the ASOG and the DPO.")
    return html.Div([
        html.Div("Station-keeping workability summary",
                 style={"fontWeight": 700, "fontSize": "15px", "margin": "8px 0 6px"}),
        html.Table(html.Tbody(trs), style={"fontSize": "12.5px",
                                           "borderCollapse": "collapse"}),
        html.Div(note, style={"fontSize": "11px", "color": MUTED, "marginTop": "8px",
                              "maxWidth": "760px"}),
    ])


dash.clientside_callback(
    "function(n){ if(n){ setTimeout(function(){ window.print(); }, 60); } "
    "return window.dash_clientside.no_update; }",
    Output("dpe-print-sink", "children"), Input("dpe-print-btn", "n_clicks"),
    prevent_initial_call=True,
)


@callback(Output("dpe-wind", "value"), Output("dpe-wu-prev", "data"),
          Input("dpe-wu", "value"), State("dpe-wind", "value"),
          State("dpe-wu-prev", "data"), prevent_initial_call=True)
def _wind_unit_switch(unit, value, prev):
    return units.convert(value, prev or "ms", unit), unit


@callback(Output("dpe-current", "value"), Output("dpe-cu-prev", "data"),
          Input("dpe-cu", "value"), State("dpe-current", "value"),
          State("dpe-cu-prev", "data"), prevent_initial_call=True)
def _cur_unit_switch(unit, value, prev):
    return units.convert(value, prev or "ms", unit), unit


def _placeholder_fig(msg):
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False, font=dict(size=14, color=MUTED),
                       xref="paper", yref="paper", x=0.5, y=0.5)
    fig.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      height=520, margin=dict(l=20, r=20, t=20, b=20))
    return fig


@callback(Output("dpe-polar", "figure"), Output("dpe-status", "children"),
          Output("dpe-basis", "children"), Output("dpe-power", "children"),
          Output("dpe-print-summary", "children"),
          Input("dpe-mode", "value"), Input("dpe-case", "value"),
          Input("dpe-heading", "value"), Input("dpe-winddir", "value"),
          Input("dpe-wind", "value"), Input("dpe-current", "value"),
          Input("dpe-hs", "value"),
          Input("dpe-aux1", "value"), Input("dpe-aux2", "value"), Input("dpe-aux3", "value"),
          Input("dpe-overlays", "value"), Input("dpe-frame", "value"),
          Input("dpe-ref", "value"),
          Input("dpe-wu", "value"), Input("dpe-cu", "value"),
          Input("dpe-ws-sel", "data"))
def _update(mode, case, heading, winddir, wind, current, hs, aux1, aux2, aux3,
            overlays, frame, ref, wu, cu, ws_sel):
    if not (rs.available() and dp.available()):
        return (_placeholder_fig("Rescale/capability data not readable from the "
                                 "data volume."), None, None, None, None)
    if not (mode and case):
        return (_placeholder_fig("Select an operating mode and analysis case."),
                None, None, None, None)
    heading = float(heading or 0.0)
    winddir = float(winddir or 0.0)
    wind = units.to_ms(float(wind or 0.0), wu or "ms")
    current = max(units.to_ms(float(current or 0.0), cu or "ms"), 0.0)
    hs = max(float(hs or 0.0), 0.0)
    overlays = overlays or []

    res = rs.assess(mode, case, heading, wind, winddir, current, hs)
    fetch_km = (ws_sel or {}).get("x", 200)
    adv = wind_sea.advisory(wind, hs, fetch_km)
    if adv:
        res["warnings"] = list(res["warnings"]) + [adv]
    inc = res["incidence_deg"]

    fig = _polar_figure(mode, case, inc, wind, heading, winddir, frame,
                        overlays, current, hs)
    status = _status_card(res, current, hs)
    basis = _basis_card(mode, res, current, hs)
    aux = {"bus1": aux1 or 0, "bus2": aux2 or 0, "bus3": aux3 or 0}
    power = _power_block(mode, case, inc, wind, current, hs, aux)
    summary = _print_summary(mode, case, res, wind, winddir, heading,
                             current, hs, aux, ref, ws_sel)
    return fig, status, basis, power, summary


def _polar_figure(mode, case, inc, wind, heading, winddir, frame, overlays,
                  current, hs):
    north_up = (frame == "true")
    off = heading % 360.0 if north_up else 0.0
    env_theta = winddir % 360.0 if north_up else inc

    fig = go.Figure()
    rmax = 0.0
    hover_ang = "brg" if north_up else "rel"
    if "study" in overlays:
        a, v = rs.study_envelope(mode, case)
        rmax = max(rmax, max(v))
        fig.add_trace(go.Scatterpolar(
            r=v, theta=[x + off for x in a], mode="lines",
            name="Study basis (published)",
            line=dict(color="#94a3b8", width=1.5, dash="dash"),
            hovertemplate="%{theta}\u00b0 " + hover_ang + ": %{r:.1f} m/s<extra>Study basis</extra>"))
    a, v = rs.envelope(mode, case, current, hs)
    rmax = max(rmax, max(v))
    fig.add_trace(go.Scatterpolar(
        r=v, theta=[x + off for x in a], mode="lines",
        name=f"Rescaled (Vc {current:.2f} m/s \u00b7 Hs {hs:.1f} m)",
        fill="toself", fillcolor="rgba(15,118,110,0.10)",
        line=dict(color=ACCENT, width=2.5),
        hovertemplate="%{theta}\u00b0 " + hover_ang + ": %{r:.1f} m/s<extra>Rescaled</extra>"))
    rmax = max(rmax, wind) * 1.06
    if north_up:
        fig.add_trace(go.Scatterpolar(
            r=[0, rmax * 0.985], theta=[off, off], mode="lines",
            name=f"Bow ({heading % 360:.0f}\u00b0T)",
            line=dict(color=INK, width=1.2, dash="dot"),
            hovertemplate=f"Vessel heading {heading % 360:.0f}\u00b0T<extra>Bow</extra>"))
    fig.add_trace(go.Scatterpolar(
        r=[0, wind], theta=[env_theta, env_theta], mode="lines+markers",
        name="Environment", line=dict(color="#dc2626", width=3),
        marker=dict(size=[0, 11], symbol="circle", color="#dc2626"),
        hovertemplate=(f"{wind:.1f} m/s @ "
                       + (f"{winddir % 360:.0f}\u00b0T" if north_up else f"{inc:.0f}\u00b0 rel")
                       + "<extra>Environment</extra>")))
    fig.update_layout(
        polar=dict(
            angularaxis=dict(rotation=90, direction="clockwise", dtick=30,
                             gridcolor=GRID, tickfont=dict(size=11)),
            radialaxis=dict(range=[0, rmax], gridcolor=GRID, angle=90, tickangle=90,
                            title=dict(text="wind [m/s]", font=dict(size=11, color=MUTED))),
            bgcolor="#ffffff"),
        legend=dict(orientation="h", yanchor="bottom", y=-0.14, x=0, font=dict(size=11)),
        margin=dict(l=40, r=40, t=25, b=40), height=520,
        paper_bgcolor="rgba(0,0,0,0)", font=dict(color=INK))
    fig.add_annotation(
        text=("Angles are true bearings (000\u00b0 = North)" if north_up
              else "Angles are relative to the bow (000\u00b0 = ahead)"),
        showarrow=False, xref="paper", yref="paper", x=1.0, y=1.04,
        xanchor="right", font=dict(size=11, color=MUTED))
    return fig


def _status_card(res, current, hs):
    st = STATUS_STYLE[res["status"]]
    lines = [
        ("Incidence angle", f'{res["incidence_deg"]:.0f}\u00b0'),
        ("Rescaled wind limit at incidence",
         f'{res["limit_ms"]:.1f} m/s  ({res["limit_kn"]:.0f} kn)'),
        ("Actual wind", f'{res["wind_ms"]:.1f} m/s'),
        ("Margin", f'{res["margin_ms"]:+.1f} m/s'),
        ("Envelope utilisation", f'{min(res["utilisation"], 9.99)*100:.0f}%'),
        ("Governing wrench axis", AXIS_LABEL.get(res["binding_axis"], "\u2014")),
    ]
    if res.get("case_used") and res["case_used"] != res.get("case_requested",
                                                            res["case_used"]):
        lines.insert(1, ("Governing failure case", res["case_used"]))
    return html.Div([
        html.Div(st["label"], style={"background": st["bg"], "color": st["fg"],
                                     "fontWeight": 700, "padding": "8px 12px",
                                     "borderRadius": "8px", "marginBottom": "10px",
                                     "textAlign": "center"}),
        *[html.Div([html.Span(k + ": ", style={"color": MUTED}),
                    html.Span(v, style={"fontWeight": 600})],
                   style={"fontSize": "13px", "marginBottom": "3px"}) for k, v in lines],
        *[html.Div(w, style={"fontSize": "12px", "color": "#92400e", "marginTop": "4px"})
          for w in res["warnings"]],
    ], style=_CARD)


def _basis_card(mode, res, current, hs):
    mm = dp.mode_meta(mode)
    b = res["basis"]
    return html.Div([
        html.B(["Rescaled from — ",
                dpdocs.mode_link(mode, mm["study_title"])],
               style={"fontSize": "13px"}),
        html.Div([dpdocs.mode_link(mode, mm["study_ref"], style={"color": MUTED}),
                  html.Span(f' \u00b7 {mm["study_note"]}', style={"color": MUTED})]),
        html.Div([
            f'Study basis: current {b["current_ms"]:.2f} m/s \u00b7 Hs {b["hs_m"]:.1f} m \u00b7 '
            f'Tp {b["tp_s"]:.1f} s (JONSWAP), collinear with wind. {mm["thrust_note"]}. '
            f'Your condition: current {current:.2f} m/s \u00b7 Hs {hs:.1f} m (collinear assumed).'
        ], style={"marginTop": "4px"}),
        html.Div(mm["wcfdi"], style={"marginTop": "4px", "color": MUTED}),
    ])


def _power_block(mode, case, inc, wind, current, hs, aux):
    thr, s = rs.thruster_loads_est(mode, case, inc, wind, current, hs)
    p = rs.power_panel_est(mode, thr, aux)
    warn, lim = p["thresholds"]
    dg_kw = p["dg_nominal_kw"]

    thr_cells = [html.Div([
        html.Div(name, style={"fontSize": "12px", "color": MUTED}),
        html.Div(f"{kw:,.0f} kW", style={"fontWeight": 700, "fontSize": "15px"}),
    ], style={"flex": 1, "textAlign": "center"}) for name, kw in thr.items()]

    bus_rows = []
    for b in p["buses"]:
        if b["band"] == "offline":
            body = html.Div("DG3 standby — RAT not in use (2-split)",
                            style={"color": MUTED, "fontSize": "12px"})
        else:
            frac = min(b["per_dg_frac"], 1.15)
            bar = html.Div(style={"width": f"{frac/1.15*100:.1f}%", "height": "14px",
                                  "background": BAND_COLOR[b["band"]], "borderRadius": "7px"})
            track = html.Div(bar, style={
                "position": "relative", "background": "#f1f5f9", "borderRadius": "7px",
                "height": "14px", "marginTop": "4px",
                "backgroundImage":
                    f"linear-gradient(90deg, transparent {warn/1.15*100:.1f}%, {GRID} {warn/1.15*100:.1f}%, "
                    f"{GRID} calc({warn/1.15*100:.1f}% + 2px), transparent calc({warn/1.15*100:.1f}% + 2px), "
                    f"transparent {lim/1.15*100:.1f}%, {GRID} {lim/1.15*100:.1f}%, "
                    f"{GRID} calc({lim/1.15*100:.1f}% + 2px), transparent calc({lim/1.15*100:.1f}% + 2px))"})
            body = html.Div([
                html.Div(f'{b["thruster_kw"]:,.0f} kW thrusters (est.) + {b["aux_kw"]:,.0f} kW consumers '
                         f'= {b["total_kw"]:,.0f} kW on {b["n_dg"]} DG '
                         f'\u2192 {b["per_dg_kw"]:,.0f} kW/DG ({b["per_dg_frac"]*100:.0f}% of {dg_kw:,.0f} kW)',
                         style={"fontSize": "13px"}),
                track,
            ])
        bus_rows.append(html.Div([
            html.Div(f'{b["bus"].upper()} — {"/".join(b["dgs"])} \u2192 {"+".join(b["thrusters"])}',
                     style={"fontWeight": 600, "fontSize": "13px"}),
            body,
        ], style={"marginBottom": "10px"}))

    return html.Div([
        html.B("Estimated power demand at your condition (App. E \u00d7 propeller law)",
               style={"fontSize": "14px"}),
        html.Div(f"Thrust utilisation vs study limit: s = {s*100:.0f}%. Per-thruster "
                 f"estimate = Appendix E load \u00d7 s^1.5 (exact at s = 100%; clamped at 125%). "
                 f"At the capability limit demand rises to the full Appendix E values. "
                 f"Threshold marks: PMS warning at {warn*100:.0f}% and thrust limitation at "
                 f"{lim*100:.0f}% of available bus power.",
                 style={"fontSize": "12px", "color": MUTED, "margin": "4px 0 10px"}),
        html.Div(thr_cells, style={"display": "flex", "gap": "8px", "marginBottom": "12px",
                                   "borderBottom": f"1px solid {GRID}", "paddingBottom": "10px"}),
        html.Div(bus_rows),
    ], style=_CARD)
