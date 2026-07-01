"""
Engineered Subsea Lift — DSV Picasso 140 t crane.

MacGregor-style engineered-subsea chart: the maximum dynamic load capacity
envelope, the SWL at the minimum DAF of 1.33, and the allowable lift for a
user-supplied DAF and lowering depth (paid-out wire weight subtracted). The DAF
here is entered manually; Stage 2 will compute it from the vessel RAOs and the
load shape and feed it into this same page.
"""
import io
import dash
from dash import html, dcc, Input, Output, State, callback, no_update
from app.pages._disclaimer import limits_footnote as _limits_footnote
import plotly.graph_objects as go

from app.engines import subsea

dash.register_page(__name__, path="/lifting/engineered-subsea", name="Engineered Subsea",
                   category="Picasso Offshore Crane", order=5)

MUTED = "#64748b"; ACCENT = "#0f766e"; INK = "#0f172a"; GRID = "#e2e8f0"
DYN = "#7c3aed"; BASE = "#94a3b8"; WARN = "#b45309"


def _fig(line, daf, depth, water, marker_r=None):
    c = subsea.curve(daf, depth, line, water)
    fig = go.Figure()
    if c is None:
        return fig
    r = c["radius"]
    fig.add_trace(go.Scatter(x=r, y=c["maxdyncap"], mode="lines", name="Max dynamic capacity",
                             line=dict(color=DYN, width=2, dash="dashdot"),
                             hovertemplate="R %{x:.1f} m<br>%{y:.1f} t<extra></extra>"))
    fig.add_trace(go.Scatter(x=r, y=c["swl133"], mode="lines", name="SWL @ DAF 1.33",
                             line=dict(color=BASE, width=2),
                             hovertemplate="R %{x:.1f} m<br>%{y:.1f} t<extra></extra>"))
    lbl = f"Allowable @ DAF {c['daf']:.2f}" + (f", {depth:g} m wire" if depth else "")
    fig.add_trace(go.Scatter(x=r, y=c["allowable"], mode="lines", name=lbl,
                             line=dict(color=ACCENT, width=3),
                             hovertemplate="R %{x:.1f} m<br>%{y:.1f} t<extra></extra>"))
    if marker_r is not None:
        a = subsea.allowable(marker_r, daf, depth, line, water)
        if a is not None:
            fig.add_trace(go.Scatter(x=[marker_r], y=[a], mode="markers",
                                     marker=dict(symbol="cross", size=14, color=INK,
                                                 line=dict(color="white", width=2)),
                                     showlegend=False,
                                     hovertemplate=f"{a:.1f} t @ {marker_r:.1f} m<extra></extra>"))
            fig.add_shape(type="line", x0=marker_r, x1=marker_r, y0=0, y1=max(a, 0),
                          line=dict(color="#94a3b8", width=1, dash="dot"))
    fig.update_layout(margin=dict(l=55, r=12, t=10, b=45), xaxis_title="Radius [m]",
                      yaxis_title="SWL [t]", plot_bgcolor="#fff", paper_bgcolor="rgba(0,0,0,0)",
                      font=dict(color=INK), height=520,
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1))
    fig.update_xaxes(gridcolor=GRID, zeroline=False, dtick=2)
    fig.update_yaxes(gridcolor=GRID, zeroline=True, zerolinecolor="#94a3b8", rangemode="tozero")
    return fig


def _row(label, value, unit="", strong=False, warn=False):
    col = WARN if warn else (ACCENT if strong else INK)
    return html.Div([
        html.Span(label, style={"color": MUTED, "fontSize": "0.82rem"}),
        html.Span(f"{value}" + (f" {unit}" if unit else ""),
                  style={"color": col, "fontFamily": "ui-monospace,monospace", "fontWeight": 700}),
    ], style={"display": "flex", "justifyContent": "space-between",
              "padding": "6px 12px", "borderBottom": f"1px solid {GRID}"})


def _num(id_, label, value, step, unit=""):
    return html.Div([
        html.Label(label + (f" [{unit}]" if unit else ""),
                   style={"fontSize": "0.75rem", "fontWeight": 600, "color": MUTED}),
        dcc.Input(id=id_, type="number", value=value, step=step, debounce=True,
                  style={"width": "100%", "padding": "6px 8px", "borderRadius": "6px",
                         "border": f"1px solid {GRID}", "boxSizing": "border-box"}),
    ], style={"marginBottom": "8px"})


def _banner():
    if subsea.is_interim():
        return html.Div([
            html.Strong("Interim capacity data. "),
            "The max-dynamic-capacity curve is recovered from sea-state data, not the official "
            "MacGregor table. Replace app/data/crane/maxdyncap.json before any operational use.",
        ], style={"background": "#fffbeb", "border": f"1px solid {WARN}", "color": "#92400e",
                  "borderRadius": "8px", "padding": "10px 14px", "fontSize": "0.85rem",
                  "marginBottom": "14px"})
    return html.Div([
        html.Span("Capacity source: ", style={"fontWeight": 600}),
        "max dynamic capacity = SWL \u00d7 DAF, derived from the MacGregor subsea data "
        "(Hs 1.0 & 2.0). Decision-support only \u2014 the lift engineer sets the DAF and "
        "remains responsible.",
    ], style={"background": "#f8fafc", "border": f"1px solid {GRID}", "color": MUTED,
              "borderRadius": "8px", "padding": "8px 14px", "fontSize": "0.8rem",
              "marginBottom": "14px"})


def layout():
    return html.Div([
        html.H3("Engineered Subsea Lift — 140 t crane", style={"marginBottom": "2px"}),
        html.P("SWL = max dynamic load capacity \u00f7 DAF, minus the weight of paid-out wire. "
               "Minimum DAF is 1.33. Enter the DAF for your sea state and lift; Stage 2 will "
               "compute it from the vessel RAOs and load shape.",
               style={"color": MUTED, "marginTop": 0, "maxWidth": "780px"}),
        _banner(),
        dcc.Store(id="es-store"),
        html.Div([
            html.Div([dcc.Graph(id="es-graph", config={"displayModeBar": False})],
                     style={"flex": "1 1 560px", "minWidth": "340px"}),
            html.Div([
                html.Div("Lift inputs", style={"fontWeight": 700, "marginBottom": "8px"}),
                html.Div([
                    html.Label("Line", style={"fontSize": "0.75rem", "fontWeight": 600,
                                              "color": MUTED}),
                    dcc.RadioItems(id="es-line",
                                   options=[{"label": " Main hoist", "value": "main"},
                                            {"label": " Whip line", "value": "whip"}],
                                   value="main", inline=True, inputStyle={"marginRight": "5px"},
                                   labelStyle={"marginRight": "12px", "fontSize": "0.85rem"}),
                ], style={"marginBottom": "8px"}),
                _num("es-daf", "Dynamic amplification factor (DAF)", 1.33, 0.01),
                html.Div("Floored at 1.33.", style={"fontSize": "0.72rem", "color": MUTED,
                                                    "marginTop": "-4px", "marginBottom": "8px"}),
                _num("es-depth", "Lowering depth (paid-out wire)", 0.0, 10.0, "m"),
                html.Div([
                    html.Label("Wire weight", style={"fontSize": "0.75rem", "fontWeight": 600,
                                                     "color": MUTED}),
                    dcc.RadioItems(id="es-water",
                                   options=[{"label": " In-water", "value": "wet"},
                                            {"label": " Dry", "value": "dry"}],
                                   value="wet", inline=True, inputStyle={"marginRight": "5px"},
                                   labelStyle={"marginRight": "12px", "fontSize": "0.85rem"}),
                ], style={"marginBottom": "10px"}),
                html.Div("Read off the chart", style={"fontWeight": 700, "margin": "8px 0"}),
                _num("es-radius", "Outreach", 15.0, 0.5, "m"),
                dcc.Slider(id="es-radius-sl", min=7, max=36, step=0.5, value=15.0,
                           marks={7: "7", 21: "21", 36: "36"}, tooltip={"placement": "bottom"}),
                html.Div(id="es-readout", style={"marginTop": "12px"}),
                html.Button("Download curve as CSV", id="es-csv-btn", n_clicks=0,
                            style={"marginTop": "14px", "width": "100%", "padding": "9px",
                                   "borderRadius": "8px", "border": "none", "background": ACCENT,
                                   "color": "#fff", "fontWeight": 600, "cursor": "pointer"}),
                dcc.Download(id="es-csv"),
            ], style={"flex": "0 0 300px", "minWidth": "280px"}),
        ], style={"display": "flex", "gap": "24px", "flexWrap": "wrap"}),
        html.Div("SWL by DAF at standard radii (at rope exit, before wire)",
                 style={"fontWeight": 700, "margin": "20px 0 8px"}),
        html.Div(id="es-table"),
        _limits_footnote(),
    ], style={"maxWidth": "1100px"})


@callback(Output("es-radius", "value"), Output("es-radius-sl", "value"),
          Input("es-radius", "value"), Input("es-radius-sl", "value"),
          prevent_initial_call=True)
def _sync(num, sl):
    v = sl if dash.callback_context.triggered_id == "es-radius-sl" else num
    if v is None:
        return no_update, no_update
    v = max(7, min(36, v))
    return v, v


@callback(Output("es-graph", "figure"), Output("es-readout", "children"),
          Output("es-table", "children"), Output("es-store", "data"),
          Input("es-line", "value"), Input("es-daf", "value"), Input("es-depth", "value"),
          Input("es-water", "value"), Input("es-radius", "value"))
def _update(line, daf, depth, water, radius):
    daf = daf if daf is not None else 1.33
    depth = depth or 0.0
    fig = _fig(line, daf, depth, water, marker_r=radius)

    if radius is not None and subsea.maxdyncap_at(radius, line) is not None:
        mc = subsea.maxdyncap_at(radius, line)
        s133 = subsea.swl_at_daf(radius, 1.33, line)
        sdaf = subsea.swl_at_daf(radius, daf, line)
        wire = depth * subsea.wire_t_per_m(line, water)
        allow = subsea.allowable(radius, daf, depth, line, water)
        rows = [_row("Outreach", round(radius, 1), "m"),
                _row("Max dynamic capacity", round(mc, 1), "t"),
                _row("SWL @ DAF 1.33", round(s133, 1), "t"),
                _row(f"SWL @ DAF {subsea.floor_daf(daf):.2f}", round(sdaf, 1), "t")]
        if depth:
            rows.append(_row("Paid-out wire", f"-{wire:.1f}", "t"))
        rows.append(_row("Allowable lift", round(allow, 1), "t",
                         strong=allow >= 0, warn=allow < 0))
        readout = html.Div(rows, style={"background": "#fff", "borderRadius": "10px",
                                        "overflow": "hidden", "border": f"1px solid {GRID}"})
    else:
        readout = html.Div("Outreach outside range." if radius else "Enter an outreach.",
                           style={"color": MUTED, "padding": "12px"})

    rows_t, dafs = subsea.daf_table(line=line)
    header = html.Tr([html.Th("Radius [m]", style={"textAlign": "left", "padding": "6px 10px"}),
                      html.Th("Max dyn [t]", style={"padding": "6px 10px"})]
                     + [html.Th(f"DAF {d}", style={"padding": "6px 10px"}) for d in dafs])
    body = []
    for r in rows_t:
        body.append(html.Tr(
            [html.Td(f'{r["radius"]:g}', style={"padding": "5px 10px", "fontWeight": 600}),
             html.Td(f'{r["maxdyncap"]:.1f}', style={"padding": "5px 10px", "textAlign": "center",
                                                     "color": DYN})]
            + [html.Td(f'{r["swl"][f"{d}"]:.1f}', style={"padding": "5px 10px",
                                                         "textAlign": "center"}) for d in dafs]))
    table = html.Table([html.Thead(header), html.Tbody(body)],
                       style={"borderCollapse": "collapse", "fontSize": "0.85rem",
                              "fontFamily": "ui-monospace,monospace",
                              "border": f"1px solid {GRID}", "background": "#fff"})
    return fig, readout, table, {"line": line, "daf": daf}


@callback(Output("es-csv", "data"), Input("es-csv-btn", "n_clicks"),
          State("es-line", "value"), State("es-daf", "value"), State("es-depth", "value"),
          State("es-water", "value"), prevent_initial_call=True)
def _csv(_n, line, daf, depth, water):
    c = subsea.curve(daf or 1.33, depth or 0.0, line, water)
    buf = io.StringIO()
    buf.write(f"Engineered subsea,{line},DAF {c['daf']:.2f},depth {depth or 0:g} m,{water}\n")
    buf.write("Radius [m],Max dynamic capacity [t],SWL@1.33 [t],SWL@DAF [t],Allowable [t]\n")
    for i, rr in enumerate(c["radius"]):
        buf.write(f"{rr:.2f},{c['maxdyncap'][i]:.2f},{c['swl133'][i]:.2f},"
                  f"{c['swl_daf'][i]:.2f},{c['allowable'][i]:.2f}\n")
    return dict(content=buf.getvalue(), filename=f"engineered_subsea_{line}.csv")
