"""
Crane curves — DSV Picasso 140 t main winch load chart.

Replicates the MacGregor "Load chart window": a filled SWL contour (radius vs
height above main deck) per lift mode, a point-query readout (by jib angles or by
radius+height, with a Best-lift / Nearest-grid toggle), load-geometry inputs, and
CSV export of the queried point.
"""
import io
import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import numpy as np
import plotly.graph_objects as go

from app.engines import crane

dash.register_page(__name__, path="/lifting/crane-curves", name="Crane curves", category="Lifting")

MUTED = "#64748b"
ACCENT = "#0f766e"
PANEL = "#0b1220"
PANEL_TEXT = "#86efac"

_MODES = crane.list_modes()
_MODE_OPTS = [{"label": f'{m["label"]} · {m["tag"]}', "value": m["key"]} for m in _MODES]


def _figure(mode_key, marker=None):
    cf = crane.contour_field(mode_key)
    R, H, P = cf["radius"], cf["height"], cf["swl"]
    fig = go.Figure()
    fig.add_trace(go.Contour(
        x=R.ravel(), y=H.ravel(), z=P.ravel(),
        colorscale="Turbo", contours=dict(showlines=False),
        colorbar=dict(title="SWL [t]", thickness=14, len=0.9),
        connectgaps=True, line_smoothing=0.85,
    ))
    if marker:
        fig.add_trace(go.Scatter(
            x=[marker["radius_m"]], y=[marker["height_m"]],
            mode="markers", marker=dict(symbol="cross", size=16, color="white",
                                        line=dict(color="black", width=2)),
            name="Query",
        ))
    fig.update_layout(
        margin=dict(l=55, r=10, t=10, b=45),
        xaxis_title="Radius [m]", yaxis_title="Height above main deck [m]",
        plot_bgcolor="#0b1220", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#cbd5e1"), showlegend=False, height=560,
    )
    fig.update_xaxes(gridcolor="#1e293b", zeroline=False)
    fig.update_yaxes(gridcolor="#1e293b", zeroline=True, zerolinecolor="#334155")
    return fig


def _readline(label, value, unit=""):
    return html.Div([
        html.Span(label, style={"color": "#94a3b8", "fontSize": "0.82rem"}),
        html.Span(f"{value}" + (f" {unit}" if unit else ""),
                  style={"color": PANEL_TEXT, "fontFamily": "ui-monospace,monospace",
                         "fontWeight": 600}),
    ], style={"display": "flex", "justifyContent": "space-between",
              "padding": "5px 10px", "borderBottom": "1px solid #1e293b"})


def _readout_panel(r):
    if not r:
        return html.Div("Point outside the load chart envelope.",
                        style={"color": MUTED, "padding": "12px"})
    rows = [
        _readline("Rated load (SWL)", r["swl_t"], "t"),
        _readline("Radius", r["radius_m"], "m"),
        _readline("Height", r["height_m"], "m"),
        _readline("Main angle", r["main_deg"], "°"),
        _readline("Folding angle", r["fold_deg"], "°"),
        _readline("DAF", r["daf"], ""),
        _readline("Stiffness", r["stiffness_tm"] if r["stiffness_tm"] is not None else "—", "t/m"),
        _readline("Limiting component", r["limit_label"], ""),
        _readline("Lowest point", r["lowest_point_m"], "m"),
    ]
    if r.get("snapped"):
        rows.append(html.Div("Snapped to nearest data point",
                             style={"color": "#fbbf24", "fontSize": "0.72rem",
                                    "padding": "6px 10px"}))
    return html.Div(rows, style={"background": PANEL, "borderRadius": "10px",
                                 "overflow": "hidden", "border": "1px solid #1e293b"})


def _num(id_, label, value, step=0.1, unit=""):
    return html.Div([
        html.Label(label + (f" [{unit}]" if unit else ""),
                   style={"fontSize": "0.75rem", "fontWeight": 600, "color": MUTED}),
        dcc.Input(id=id_, type="number", value=value, step=step, debounce=True,
                  style={"width": "100%", "padding": "6px 8px", "borderRadius": "6px",
                         "border": "1px solid #cbd5e1", "boxSizing": "border-box"}),
    ], style={"marginBottom": "8px"})


def layout():
    first = _MODES[0]["key"]
    return html.Div([
        html.H3("Crane curves — 140 t main winch", style={"marginBottom": "2px"}),
        html.P("GPOKa 5000-140-36 AHC subsea crane · DSV Picasso · main lift. "
               "Heights are referenced to the Picasso main deck.",
               style={"color": MUTED, "marginTop": 0, "maxWidth": "760px"}),
        dcc.Store(id="cr-store"),
        html.Div([
            html.Div([
                html.Div([
                    html.Label("Lift mode", style={"fontSize": "0.75rem", "fontWeight": 600,
                                                   "color": MUTED, "marginRight": "8px"}),
                    dcc.Dropdown(id="cr-mode", options=_MODE_OPTS, value=first, clearable=False,
                                 style={"width": "260px"}),
                ], style={"display": "flex", "alignItems": "center", "gap": "8px",
                          "marginBottom": "8px"}),
                dcc.Graph(id="cr-graph", config={"displayModeBar": False}),
            ], style={"flex": "1 1 560px", "minWidth": "340px"}),
            html.Div([
                html.Div("Position the crane", style={"fontWeight": 700, "marginBottom": "8px"}),
                dcc.Tabs(id="cr-mode-tab", value="angles", children=[
                    dcc.Tab(label="By jib angles", value="angles", children=[
                        html.Div([
                            _num("cr-main", "Main jib angle", 30.0, 0.5, "°"),
                            _num("cr-fold", "Folding jib angle", 45.0, 0.5, "°"),
                        ], style={"paddingTop": "10px"}),
                    ]),
                    dcc.Tab(label="By radius + height", value="rh", children=[
                        html.Div([
                            _num("cr-radius", "Radius", 20.0, 0.5, "m"),
                            _num("cr-height", "Height above deck", 10.0, 0.5, "m"),
                            html.Label("When several solutions exist",
                                       style={"fontSize": "0.75rem", "fontWeight": 600,
                                              "color": MUTED}),
                            dcc.RadioItems(
                                id="cr-rule",
                                options=[{"label": " Best lift (highest SWL)", "value": "best"},
                                         {"label": " Nearest grid point", "value": "nearest"}],
                                value="best",
                                style={"fontSize": "0.85rem", "marginTop": "4px"},
                                labelStyle={"display": "block", "marginBottom": "3px"},
                            ),
                        ], style={"paddingTop": "10px"}),
                    ]),
                ]),
                html.Details([
                    html.Summary("Load geometry",
                                 style={"cursor": "pointer", "fontWeight": 600,
                                        "fontSize": "0.85rem", "margin": "12px 0 6px"}),
                    _num("cr-wire", "Wire length a", 0.0, 0.5, "m"),
                    _num("cr-rig", "Rigging height c", 0.0, 0.5, "m"),
                    _num("cr-loadh", "Load height d", 0.0, 0.5, "m"),
                    _num("cr-loadw", "Load width e", 0.0, 0.5, "m"),
                ], open=False),
                html.Div(id="cr-readout", style={"marginTop": "12px"}),
                html.Button("Download point as CSV", id="cr-csv-btn", n_clicks=0,
                            style={"marginTop": "12px", "width": "100%", "padding": "9px",
                                   "borderRadius": "8px", "border": "none",
                                   "background": ACCENT, "color": "#fff", "fontWeight": 600,
                                   "cursor": "pointer"}),
                dcc.Download(id="cr-csv"),
            ], style={"flex": "0 0 320px", "minWidth": "300px"}),
        ], style={"display": "flex", "gap": "24px", "flexWrap": "wrap"}),
    ], style={"maxWidth": "1100px"})


def _solve(mode, tab, main, fold, radius, height, rule, wire, rig, loadh):
    geom = {"wire_a": wire or 0.0, "rigging_c": rig or 0.0, "load_d": loadh or 0.0}
    if tab == "rh":
        return crane.query_point(mode, radius if radius is not None else 0,
                                 height if height is not None else 0,
                                 rule=rule or "best", geom=geom)
    return crane.query_angles(mode, main if main is not None else 0,
                              fold if fold is not None else 0, geom=geom)


@callback(
    Output("cr-graph", "figure"),
    Output("cr-readout", "children"),
    Output("cr-store", "data"),
    Input("cr-mode", "value"),
    Input("cr-mode-tab", "value"),
    Input("cr-main", "value"), Input("cr-fold", "value"),
    Input("cr-radius", "value"), Input("cr-height", "value"), Input("cr-rule", "value"),
    Input("cr-wire", "value"), Input("cr-rig", "value"), Input("cr-loadh", "value"),
)
def _update(mode, tab, main, fold, radius, height, rule, wire, rig, loadh):
    r = _solve(mode, tab, main, fold, radius, height, rule, wire, rig, loadh)
    fig = _figure(mode, marker=r)
    return fig, _readout_panel(r), r


@callback(
    Output("cr-csv", "data"),
    Input("cr-csv-btn", "n_clicks"),
    State("cr-store", "data"),
    State("cr-mode", "value"),
    prevent_initial_call=True,
)
def _csv(_n, r, mode):
    if not r:
        return no_update
    tag = next((m["tag"] for m in _MODES if m["key"] == mode), mode)
    buf = io.StringIO()
    buf.write("Parameter,Value,Unit\n")
    buf.write(f"Lift mode,{tag},\n")
    buf.write(f"Rated load (SWL),{r['swl_t']},t\n")
    buf.write(f"DAF,{r['daf']},-\n")
    buf.write(f"Radius,{r['radius_m']},m\n")
    buf.write(f"Height above deck,{r['height_m']},m\n")
    buf.write(f"Main angle,{r['main_deg']},deg\n")
    buf.write(f"Folding angle,{r['fold_deg']},deg\n")
    buf.write(f"Stiffness,{r['stiffness_tm']},t/m\n")
    buf.write(f"Limiting component,{r['limit_label']},\n")
    buf.write(f"Lowest point,{r['lowest_point_m']},m\n")
    return dict(content=buf.getvalue(), filename=f"crane_{mode}_point.csv")
