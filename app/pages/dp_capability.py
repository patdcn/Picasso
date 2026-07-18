"""
DP Capability & Ops Check — DSV Picasso station-keeping envelopes.

Interactive polar capability plot (digitised Thrustmaster Appendix D data) with
an operations check: enter vessel heading, forecast wind, current and Hs and
get the limiting wind at that incidence, the margin, and a GO / MARGINAL /
NO-GO / OUTSIDE-BASIS verdict. The power panel shows the exact Appendix E
per-thruster demand at the capability limit, rolled up per 690 V bus and per
DG with the vessel's own PMS 80 % / 85 % power-limit thresholds.

The numeric data lives only on the /data volume (see engines/dp_capability.py).
"""
import dash
import datetime
from dash import html, dcc, Input, Output, State, callback
import plotly.graph_objects as go

from app.engines import dp_capability as dp
from app import dp_consumers as dcon
from app import reports
from app import units

dash.register_page(__name__, path="/dp/capability", name="DP Capability & Ops Check",
                   category="DP Station Keeping", order=1)

MUTED = "#64748b"
ACCENT = "#0f766e"
INK = "#0f172a"
GRID = "#e2e8f0"

STATUS_STYLE = {
    "GO":            {"bg": "#dcfce7", "fg": "#166534", "label": "GO — inside envelope"},
    "MARGINAL":      {"bg": "#fef9c3", "fg": "#854d0e", "label": "MARGINAL — \u2265 80% of envelope"},
    "NO-GO":         {"bg": "#fee2e2", "fg": "#991b1b", "label": "NO-GO — exceeds envelope"},
    "OUTSIDE BASIS": {"bg": "#fee2e2", "fg": "#991b1b", "label": "OUTSIDE ANALYSIS BASIS"},
}
BAND_COLOR = {"ok": "#16a34a", "warn": "#d97706", "limit": "#dc2626", "offline": "#94a3b8"}

_CARD = {"background": "#ffffff", "border": f"1px solid {GRID}", "borderRadius": "10px",
         "padding": "14px 16px", "marginBottom": "14px"}
_LBL = {"fontSize": "12px", "color": MUTED, "marginBottom": "2px", "display": "block"}
# env-input row: equal-height labels so the three boxes bottom-align even
# when one label wraps to two lines
_LBL_ENV = {**_LBL, "minHeight": "28px"}
_NUM = {"width": "100%", "boxSizing": "border-box"}


def _num_input(cid, value, mi=None, ma=None, step="any"):
    return dcc.Input(id=cid, type="number", value=value, min=mi, max=ma, step=step,
                     debounce=True, style=_NUM)


def _controls():
    mode_opts = [{"label": m["label"], "value": k} for k, m in dp.modes().items()]
    return html.Div([
        html.Label("Operating mode (FMEA Table 9-4)", style=_LBL),
        dcc.RadioItems(id="dpc-mode", options=mode_opts, value="2split",
                       labelStyle={"display": "block", "margin": "2px 0"},
                       style={"marginBottom": "10px", "fontSize": "14px"}),
        html.Label("Analysis case", style=_LBL),
        dcc.Dropdown(id="dpc-case", clearable=False,
                     style={"marginBottom": "10px", "fontSize": "13.5px"}),
        html.Div([
            html.Div([html.Label("Vessel heading [°T]", style=_LBL),
                      _num_input("dpc-heading", 0, 0, 360)], style={"flex": 1}),
            html.Div([html.Label("Wind from [°T]", style=_LBL),
                      _num_input("dpc-winddir", 70, 0, 360)], style={"flex": 1}),
        ], style={"display": "flex", "gap": "10px", "marginBottom": "8px"}),
        html.Div([
            html.Div([html.Label("Wind speed (1-min @ 10 m)", style=_LBL_ENV),
                      _num_input("dpc-wind", 10.0, 0)], style={"flex": 1}),
            html.Div([html.Label("Current — study basis", style=_LBL_ENV),
                      dcc.Dropdown(id="dpc-current", clearable=False,
                                   searchable=False)], style={"flex": 1}),
            html.Div([html.Label("Hs [m] — study basis", style=_LBL_ENV),
                      dcc.Dropdown(id="dpc-hs", clearable=False,
                                   searchable=False)], style={"flex": 1}),
        ], style={"display": "flex", "gap": "10px", "marginBottom": "4px",
                  "alignItems": "flex-end"}),
        html.Div("Current and Hs are selectable only at the values the capability "
                 "studies were run at (no tidal/current sweep exists in the analyses).",
                 style={"fontSize": "11px", "color": MUTED, "marginBottom": "8px"}),
        html.Label("DP power consumers — planning kW (admin-editable registry)",
                   style=_LBL),
        dcc.Checklist(
            id="dpc-consumers",
            options=[{"label": f' {r["name"]}\u00a0\u00b7\u00a0{r["kw"]:,.0f}\u00a0kW',
                      "value": r["id"]} for r in dcon.rows()],
            value=[r["id"] for r in dcon.rows() if r["default_on"]],
            labelStyle={"display": "block", "margin": "2px 0"},
            style={"fontSize": "13px", "marginBottom": "4px"}),
        html.Div(id="dpc-consumer-note",
                 style={"fontSize": "11px", "color": MUTED, "marginBottom": "8px"}),
        html.Label("Auxiliary (non-thruster) load per bus [kW] — prefilled from the "
                   "selection above, editable for ad-hoc tweaks",
                   style=_LBL),
        html.Div([
            html.Div([html.Label("Bus 1", style=_LBL), _num_input("dpc-aux1", 0, 0)], style={"flex": 1}),
            html.Div([html.Label("Bus 2", style=_LBL), _num_input("dpc-aux2", 0, 0)], style={"flex": 1}),
            html.Div([html.Label("Bus 3", style=_LBL), _num_input("dpc-aux3", 0, 0)], style={"flex": 1}),
        ], style={"display": "flex", "gap": "10px", "marginBottom": "8px"}),
        dcc.Checklist(id="dpc-overlays",
                      options=[{"label": " Intact envelope (All Thrusters Active)", "value": "intact"}],
                      value=["intact"], style={"fontSize": "13px", "marginBottom": "8px"}),
        html.Label("Plot frame", style=_LBL),
        dcc.RadioItems(
            id="dpc-frame",
            options=[{"label": " Vessel-relative (bow up, as per study)", "value": "rel"},
                     {"label": " True bearings (North up, envelope rotated to heading)",
                      "value": "true"}],
            value="rel", labelStyle={"display": "block", "margin": "2px 0"},
            style={"fontSize": "13px"}),
    ], style=_CARD, className="no-print")


def _notice_missing():
    return html.Div([
        html.H2("DP Capability & Ops Check", style={"color": INK}),
        html.Div([
            html.B("Data not installed. "),
            "This tool reads the digitised capability data from the data volume at ",
            html.Code("tools/dp/dp_capability.json"),
            ". Upload it via Admin \u2192 Data volume files (the Thrustmaster data is "
            "proprietary and is never stored in the public repository).",
        ], style={**_CARD, "background": "#fef9c3"}),
    ], style={"maxWidth": "900px"})


def layout():
    if not dp.available():
        return _notice_missing()
    return html.Div([
        reports.print_header(),
        html.Div([
            html.Button([html.Span("\u2913\u2002"), "Print capability sheet"],
                        id="dpc-print-btn", n_clicks=0,
                        style={"border": f"1px solid {GRID}", "background": "#fff",
                               "borderRadius": "8px", "padding": "7px 14px",
                               "cursor": "pointer", "fontSize": "13px"}),
            html.Div(id="dpc-print-sink", style={"display": "none"}),
        ], className="no-print", style={"display": "flex", "justifyContent": "flex-end",
                                        "marginBottom": "6px"}),
        html.H2("DP Capability & Ops Check", style={"color": INK, "marginBottom": "2px"}),
        html.Div("Station-keeping envelopes (Thrustmaster App. D) with operations check "
                 "and power demand at the capability limit (App. E).",
                 style={"color": MUTED, "fontSize": "13px", "marginBottom": "12px"}),
        html.Div([
            html.Div([_controls(), html.Div(id="dpc-status")],
                     style={"flex": "0 0 420px"}),
            html.Div([
                html.Div(dcc.Graph(id="dpc-polar", config={"displaylogo": False}),
                         style=_CARD),
                html.Div(id="dpc-basis", style={**_CARD, "fontSize": "13px"}),
            ], style={"flex": 1, "minWidth": "420px"}),
        ], style={"display": "flex", "gap": "14px", "flexWrap": "wrap"}),
        html.Div(id="dpc-print-summary", className="print-only"),
        html.Div(id="dpc-power"),
        _reference_block(),
        reports.print_footer(),
    ], style={"maxWidth": "1200px"})


def _reference_block():
    rows = []
    for r in dp.fmea_load_balance():
        rows.append(html.Tr([
            html.Td(r["mode"]),
            html.Td(f'{r["bus1_kw"]:.0f} kW · {r["bus1_pct"]}%'),
            html.Td(f'{r["bus2_kw"]:.0f} kW · {r["bus2_pct"]}%'),
            html.Td(f'{r["bus3_kw"]:.0f} kW · {r["bus3_pct"] if r["bus3_pct"] is not None else "—"}'
                    + ("%" if r["bus3_pct"] is not None else "")),
        ]))
    table = html.Table(
        [html.Thead(html.Tr([html.Th(h) for h in
                             ["FMEA design load balance (Table 10-2)", "Bus 1", "Bus 2", "Bus 3"]]))] +
        [html.Tbody(rows)],
        style={"width": "100%", "fontSize": "12px", "borderCollapse": "collapse"},
        className="dpc-table")
    prov = html.Ul([html.Li(p, style={"marginBottom": "3px"}) for p in dp.provenance()],
                   style={"fontSize": "12px", "color": MUTED, "paddingLeft": "18px"})
    disclaimer = html.Div([
        html.B("Use limits. "), "Envelopes are theoretical capability at the study's fixed "
        "environment (collinear wind/wave/current) and do not guarantee station keeping; "
        "power limitation was ignored in the analyses, so near the envelope edge the PMS "
        "power-limit function (80 % warn / 85 % thrust limitation) may govern before the "
        "theoretical limit is reached. This page supports planning only — the ASOG and the "
        "DPO's judgement remain leading. Validate with footprints in the operational area.",
    ], style={"fontSize": "12px", "color": MUTED, "marginTop": "8px"})
    return html.Div([
        html.Div(table, style=_CARD),
        html.Div([html.B("Document basis", style={"fontSize": "13px"}), prov, disclaimer],
                 style=_CARD),
    ])


# ------------------------------------------------------------------ callbacks

@callback(Output("dpc-case", "options"), Output("dpc-case", "value"),
          Input("dpc-mode", "value"))
def _cases(mode):
    if not dp.available():
        return [], None
    cs = dp.cases(mode)
    opts = [{"label": dp.WORST_LABEL, "value": dp.WORST}]
    opts += [{"label": c, "value": c} for c in cs]
    return opts, dp.WORST


@callback(Output("dpc-current", "options"), Output("dpc-current", "value"),
          Output("dpc-hs", "options"), Output("dpc-hs", "value"),
          Input("dpc-mode", "value"), Input("dpc-case", "value"),
          Input("dpc-cu", "value"))
def _env_choices(mode, case, cu):
    """Restrict current and Hs to the exact values the studies were run at.

    Free numeric entry is deliberately not offered: the envelopes are only a
    valid bound at the study's fixed environment, and no current/Hs sweep
    exists to interpolate from. Rescaling to arbitrary environments is the
    separate (Stage 2 / 'Option 4') App. C engine, not this page.
    """
    if not (dp.available() and mode and case):
        return [], None, [], None
    opts = dp.env_options(mode, case)
    curs = sorted({round(float(o["current_ms"]), 3) for o in opts})
    hss = sorted({round(float(o["hs_m"]), 2) for o in opts})
    if (cu or "ms") == "kn":
        cur_opts = [{"label": f"{c * units.KN_PER_MS:.2f} kn", "value": c}
                    for c in curs]
    else:
        cur_opts = [{"label": f"{c:.2f} m/s", "value": c} for c in curs]
    hs_opts = [{"label": f"{h:.1f} m", "value": h} for h in hss]
    return cur_opts, curs[0], hs_opts, hss[0]


@callback(Output("dpc-aux1", "value"), Output("dpc-aux2", "value"),
          Output("dpc-aux3", "value"), Output("dpc-consumer-note", "children"),
          Input("dpc-consumers", "value"), Input("dpc-mode", "value"))
def _prefill_aux(selected, mode):
    """Prefill (not lock) the per-bus aux fields from the consumer selection.

    Runs on page load too, so the default-on consumers seed the fields. The
    fields stay directly editable; any manual tweak holds until the selection
    or mode changes, which recomputes the prefill.
    """
    if not (dp.available() and mode):
        return 0, 0, 0, None
    dgs_per_bus = dp.modes()[mode].get("dgs_per_bus", {})
    loads, warns, total = dcon.bus_loads(selected or [], dgs_per_bus)
    note = [html.Span(
        f"Selected {total:,.0f} kW \u2192 Bus 1 {loads['bus1']:,.0f} / "
        f"Bus 2 {loads['bus2']:,.0f} / Bus 3 {loads['bus3']:,.0f} kW. "
        "\u2018Split\u2019 consumers are shared over the live buses weighted by "
        "running DGs, pending the 440 V single-line bus mapping.")]
    for w in warns:
        note.append(html.Div(w, style={"color": "#991b1b"}))
    return (round(loads["bus1"]), round(loads["bus2"]), round(loads["bus3"]),
            note)


@callback(Output("dpc-wind", "value"), Output("dpc-wu-prev", "data"),
          Input("dpc-wu", "value"), State("dpc-wind", "value"),
          State("dpc-wu-prev", "data"), prevent_initial_call=True)
def _wind_unit_switch(unit, value, prev):
    return units.convert(value, prev or "ms", unit), unit


def _placeholder_fig(msg):
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False, font=dict(size=14, color=MUTED),
                       xref="paper", yref="paper", x=0.5, y=0.5)
    fig.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      height=520, margin=dict(l=20, r=20, t=20, b=20))
    return fig


@callback(Output("dpc-polar", "figure"), Output("dpc-status", "children"),
          Output("dpc-basis", "children"), Output("dpc-power", "children"),
          Output("dpc-print-summary", "children"),
          Input("dpc-mode", "value"), Input("dpc-case", "value"),
          Input("dpc-heading", "value"), Input("dpc-winddir", "value"),
          Input("dpc-wind", "value"), Input("dpc-current", "value"),
          Input("dpc-hs", "value"),
          Input("dpc-aux1", "value"), Input("dpc-aux2", "value"), Input("dpc-aux3", "value"),
          Input("dpc-overlays", "value"), Input("dpc-frame", "value"),
          Input("dpc-wu", "value"))
def _update(mode, case, heading, winddir, wind, current, hs, aux1, aux2, aux3,
            overlays, frame, wu):
    if not dp.available():
        return (_placeholder_fig("Capability data not readable from the data volume "
                                 "(tools/dp/dp_capability.json)."), None, None, None, None)
    if not (mode and case):
        return (_placeholder_fig("Select an operating mode and analysis case."),
                None, None, None, None)
    heading = float(heading or 0.0)
    winddir = float(winddir or 0.0)
    wind = units.to_ms(float(wind or 0.0), wu or "ms")
    current = float(current or 0.0)
    hs = float(hs or 0.0)
    overlays = overlays or []

    res = dp.assess(mode, case, heading, wind, winddir, current, hs)
    inc = res["incidence_deg"]

    fig = _polar_figure(mode, case, inc, wind, heading, winddir, frame, overlays)
    status = _status_card(mode, case, res)
    basis = _basis_card(mode, case, res)
    aux = {"bus1": aux1 or 0, "bus2": aux2 or 0, "bus3": aux3 or 0}
    power = _power_block(mode, case, inc, aux)
    summary = _print_summary(mode, case, res, wind, winddir, heading,
                             current, hs, aux)
    return fig, status, basis, power, summary


def _polar_figure(mode, case, inc, wind, heading, winddir, frame, overlays):
    """Polar capability plot in one of two frames.

    'rel'  — vessel-relative, bow at top (Thrustmaster App. D convention).
             Envelope drawn as tabulated; environment vector at the incidence.
    'true' — North up. Everything vessel-fixed (envelopes, bow marker) rotates
             by +heading; the environment vector is earth-fixed at its true
             bearing. Identical geometry, different reference frame — the
             assessment itself is frame-independent.
    """
    north_up = (frame == "true")
    off = heading % 360.0 if north_up else 0.0     # rotation of vessel-fixed items
    env_theta = winddir % 360.0 if north_up else inc

    fig = go.Figure()
    rmax = 0.0
    hover_ang = "brg" if north_up else "rel"
    if "intact" in overlays and case != "All Thrusters Active":
        a, v = dp.envelope(mode, "All Thrusters Active")
        rmax = max(rmax, max(v))
        fig.add_trace(go.Scatterpolar(
            r=v, theta=[x + off for x in a], mode="lines", name="All Thrusters Active",
            line=dict(color="#94a3b8", width=1.5, dash="dash"),
            hovertemplate="%{theta}° " + hover_ang + ": %{r:.1f} m/s<extra>Intact</extra>"))
    a, v = dp.envelope(mode, case)
    rmax = max(rmax, max(v))
    fig.add_trace(go.Scatterpolar(
        r=v, theta=[x + off for x in a], mode="lines",
        name=(dp.WORST_LABEL if case == dp.WORST else case), fill="toself",
        fillcolor="rgba(15,118,110,0.10)", line=dict(color=ACCENT, width=2.5),
        hovertemplate="%{theta}° " + hover_ang + ": %{r:.1f} m/s<extra>"
                      + (dp.WORST_LABEL if case == dp.WORST else case) + "</extra>"))
    rmax = max(rmax, wind) * 1.06
    if north_up:
        # bow indicator: vessel-fixed reference so the rotated petal is readable
        fig.add_trace(go.Scatterpolar(
            r=[0, rmax * 0.985], theta=[off, off], mode="lines",
            name=f"Bow ({heading % 360:.0f}°T)",
            line=dict(color=INK, width=1.2, dash="dot"),
            hovertemplate=f"Vessel heading {heading % 360:.0f}°T<extra>Bow</extra>"))
    # environment vector: from centre to the actual wind speed
    fig.add_trace(go.Scatterpolar(
        r=[0, wind], theta=[env_theta, env_theta], mode="lines+markers",
        name="Environment", line=dict(color="#dc2626", width=3),
        marker=dict(size=[0, 11], symbol="circle", color="#dc2626"),
        hovertemplate=(f"{wind:.1f} m/s @ "
                       + (f"{winddir % 360:.0f}°T" if north_up else f"{inc:.0f}° rel")
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
        text=("Angles are true bearings (000° = North)" if north_up
              else "Angles are relative to the bow (000° = ahead)"),
        showarrow=False, xref="paper", yref="paper", x=1.0, y=1.04,
        xanchor="right", font=dict(size=11, color=MUTED))
    return fig


def _print_summary(mode, case, res, wind, winddir, heading, current, hs, aux):
    """Study-style summary table for the printed capability sheet."""
    mm = dp.mode_meta(mode)
    angs, vals = dp.envelope(mode, case)
    mn = min(vals[:-1]); mn_ang = angs[vals.index(mn)]
    aux_total = sum(float(v or 0) for v in aux.values())
    st = STATUS_STYLE[res["status"]]
    rows = [
        ("Vessel", "DSV Picasso"),
        ("Operating mode", dp.modes()[mode]["label"]),
        ("Analysis case",
         (dp.WORST_LABEL + (f' \u2014 governing: {res["case_used"]}'
                            if res.get("case_used") else "")) if case == dp.WORST
         else case),
        ("Current speed", f"{float(current):.2f} m/s (collinear, study value)"),
        ("Significant wave height (Hs)", f"{float(hs):.1f} m (study value)"),
        ("Wave spectrum", f'JONSWAP, Tp {res["basis"]["tp_s"]:.1f} s'),
        ("Min capability wind speed", f"{mn:.2f} m/s ({mn * dp.MS_TO_KN:.0f} kn)"),
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
         f'{mm["study_title"]} \u2014 {mm["study_ref"]} \u00b7 {mm["study_note"]} '
         "(published Appendix D envelope, no rescaling)"),
        ("Generated", datetime.date.today().isoformat()
         + " \u00b7 DSV Picasso Engineering Portal"),
    ]
    trs = [html.Tr([
        html.Td(k, style={"padding": "3px 10px 3px 0", "color": MUTED,
                          "whiteSpace": "nowrap", "verticalAlign": "top"}),
        html.Td(v, style={"padding": "3px 0", "fontWeight": 600}),
    ]) for k, v in rows]
    note = ("Figures from the Thrustmaster capability studies at their analysed "
            "environment. Estimated capabilities do not act as a guarantee of "
            "station-keeping in the given environmental conditions. Indicative, for "
            "planning only; operational limits are governed by the ASOG and the DPO.")
    return html.Div([
        html.Div("DP capability summary",
                 style={"fontWeight": 700, "fontSize": "15px", "margin": "8px 0 6px"}),
        html.Table(html.Tbody(trs), style={"fontSize": "12.5px",
                                           "borderCollapse": "collapse"}),
        html.Div(note, style={"fontSize": "11px", "color": MUTED, "marginTop": "8px",
                              "maxWidth": "760px"}),
    ])


dash.clientside_callback(
    "function(n){ if(n){ setTimeout(function(){ window.print(); }, 60); } "
    "return window.dash_clientside.no_update; }",
    Output("dpc-print-sink", "children"), Input("dpc-print-btn", "n_clicks"),
    prevent_initial_call=True,
)


def _status_card(mode, case, res):
    st = STATUS_STYLE[res["status"]]
    governing = (res.get("case_used")
                 if res.get("case_requested") == dp.WORST else None)
    lines = [
        ("Incidence angle", f'{res["incidence_deg"]:.0f}°'),
        ("Limiting wind at incidence", f'{res["limit_ms"]:.1f} m/s  ({res["limit_kn"]:.0f} kn)'),
        ("Actual wind", f'{res["wind_ms"]:.1f} m/s'),
        ("Margin", f'{res["margin_ms"]:+.1f} m/s'),
        ("Envelope utilisation", f'{res["utilisation"]*100:.0f}%'),
    ]
    if governing:
        lines.insert(0, ("Governing failure case", governing))
    warn = []
    if not res["current_ok"]:
        warn.append(f'Current exceeds analysis basis ({res["basis"]["current_ms"]:.2f} m/s).')
    if not res["hs_ok"]:
        warn.append(f'Hs exceeds analysis basis ({res["basis"]["hs_m"]:.1f} m).')
    return html.Div([
        html.Div(st["label"], style={"background": st["bg"], "color": st["fg"],
                                     "fontWeight": 700, "padding": "8px 12px",
                                     "borderRadius": "8px", "marginBottom": "10px",
                                     "textAlign": "center"}),
        *[html.Div([html.Span(k + ": ", style={"color": MUTED}),
                    html.Span(v, style={"fontWeight": 600})],
                   style={"fontSize": "13px", "marginBottom": "3px"}) for k, v in lines],
        *[html.Div(w, style={"fontSize": "12px", "color": "#991b1b", "marginTop": "4px"})
          for w in warn],
    ], style=_CARD)


def _basis_card(mode, case, res):
    mm = dp.mode_meta(mode)
    b = res["basis"]
    return html.Div([
        html.B("Analysis basis — " + mm["study_title"], style={"fontSize": "13px"}),
        html.Div(f'{mm["study_ref"]} · {mm["study_note"]}', style={"color": MUTED}),
        html.Div([
            f'Fixed environment: current {b["current_ms"]:.2f} m/s · Hs {b["hs_m"]:.1f} m · '
            f'Tp {b["tp_s"]:.1f} s (JONSWAP), collinear with wind. {mm["thrust_note"]}.'
        ], style={"marginTop": "4px"}),
        html.Div(mm["wcfdi"], style={"marginTop": "4px", "color": MUTED}),
    ])


def _power_block(mode, case, inc, aux):
    p = dp.power_panel(mode, case, inc, aux)
    warn, lim = p["thresholds"]
    dg_kw = p["dg_nominal_kw"]

    thr_cells = [html.Div([
        html.Div(name, style={"fontSize": "12px", "color": MUTED}),
        html.Div(f"{kw:,.0f} kW", style={"fontWeight": 700, "fontSize": "15px"}),
    ], style={"flex": 1, "textAlign": "center"}) for name, kw in p["thrusters"].items()]

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
                html.Div(f'{b["thruster_kw"]:,.0f} kW thrusters + {b["aux_kw"]:,.0f} kW aux '
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
        html.B("Power demand at capability limit (Appendix E, exact study values)",
               style={"fontSize": "14px"}),
        html.Div("Marginal station keeping in the limiting wind at the selected incidence. "
                 f"Actual demand below the limit is lower. Threshold marks: PMS warning at "
                 f"{warn*100:.0f}% and thrust limitation at {lim*100:.0f}% of available bus power.",
                 style={"fontSize": "12px", "color": MUTED, "margin": "4px 0 10px"}),
        html.Div(thr_cells, style={"display": "flex", "gap": "8px", "marginBottom": "12px",
                                   "borderBottom": f"1px solid {GRID}", "paddingBottom": "10px"}),
        html.Div(bus_rows),
    ], style=_CARD)
