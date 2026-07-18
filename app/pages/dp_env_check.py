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
from dash import html, dcc, Input, Output, callback
import plotly.graph_objects as go

from app.engines import dp_capability as dp
from app.engines import dp_env_rescale as rs
from app import dp_consumers as dcon

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
            html.Div([html.Label("Wind speed [m/s] (1-min @ 10 m)", style=_LBL_ENV),
                      _num_input("dpe-wind", 10.0, 0)], style={"flex": 1}),
            html.Div([html.Label("Current [m/s] — free input", style=_LBL_ENV),
                      _num_input("dpe-current", 1.0, 0, step=0.05)], style={"flex": 1}),
            html.Div([html.Label("Hs [m] — free input", style=_LBL_ENV),
                      _num_input("dpe-hs", 2.5, 0, step=0.1)], style={"flex": 1}),
        ], style={"display": "flex", "gap": "10px", "marginBottom": "4px",
                  "alignItems": "flex-end"}),
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
        html.Label("Plot frame", style=_LBL),
        dcc.RadioItems(
            id="dpe-frame",
            options=[{"label": " Vessel-relative (bow up, as per study)", "value": "rel"},
                     {"label": " True bearings (North up, envelope rotated to heading)",
                      "value": "true"}],
            value="rel", labelStyle={"display": "block", "margin": "2px 0"},
            style={"fontSize": "13px"}),
    ], style=_CARD)


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
            ], style={"flex": 1, "minWidth": "420px"}),
        ], style={"display": "flex", "gap": "14px", "flexWrap": "wrap"}),
        html.Div(id="dpe-power"),
        _method_block(),
    ], style={"maxWidth": "1200px"})


def _method_block():
    prov = html.Ul([html.Li(p, style={"marginBottom": "3px"}) for p in rs.provenance()],
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
    wcf = rs.wcfdi_cases(mode)
    if wcf:
        default = wcf[-1]                       # side-bus loss: dive planning basis
    elif "Most Critical Thruster Failure" in cs:
        default = "Most Critical Thruster Failure"
    else:
        default = cs[0]
    opts = [{"label": c + (" \u2014 worst case failure"
                          if c in wcf else ""),
             "value": c} for c in cs]
    return opts, default


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
        "\u2018Split\u2019 consumers are shared over the live buses weighted by "
        "running DGs, pending the 440 V single-line bus mapping.")]
    for w in warns:
        note.append(html.Div(w, style={"color": "#991b1b"}))
    return (round(loads["bus1"]), round(loads["bus2"]), round(loads["bus3"]),
            note)


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
          Input("dpe-mode", "value"), Input("dpe-case", "value"),
          Input("dpe-heading", "value"), Input("dpe-winddir", "value"),
          Input("dpe-wind", "value"), Input("dpe-current", "value"),
          Input("dpe-hs", "value"),
          Input("dpe-aux1", "value"), Input("dpe-aux2", "value"), Input("dpe-aux3", "value"),
          Input("dpe-overlays", "value"), Input("dpe-frame", "value"))
def _update(mode, case, heading, winddir, wind, current, hs, aux1, aux2, aux3,
            overlays, frame):
    if not (rs.available() and dp.available()):
        return (_placeholder_fig("Rescale/capability data not readable from the "
                                 "data volume."), None, None, None)
    if not (mode and case):
        return _placeholder_fig("Select an operating mode and analysis case."), None, None, None
    heading = float(heading or 0.0)
    winddir = float(winddir or 0.0)
    wind = float(wind or 0.0)
    current = max(float(current or 0.0), 0.0)
    hs = max(float(hs or 0.0), 0.0)
    overlays = overlays or []

    res = rs.assess(mode, case, heading, wind, winddir, current, hs)
    inc = res["incidence_deg"]

    fig = _polar_figure(mode, case, inc, wind, heading, winddir, frame,
                        overlays, current, hs)
    status = _status_card(res, current, hs)
    basis = _basis_card(mode, res, current, hs)
    aux = {"bus1": aux1 or 0, "bus2": aux2 or 0, "bus3": aux3 or 0}
    power = _power_block(mode, case, inc, wind, current, hs, aux)
    return fig, status, basis, power


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
        html.B("Rescaled from — " + mm["study_title"], style={"fontSize": "13px"}),
        html.Div(f'{mm["study_ref"]} \u00b7 {mm["study_note"]}', style={"color": MUTED}),
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
