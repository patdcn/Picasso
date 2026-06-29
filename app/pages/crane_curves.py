"""
Crane curves — DSV Picasso 140 t main winch load chart.

Filled SWL contour (radius vs height above main deck) per lift mode, with a moving
crane schematic overlaid, a point-query readout (by jib angles with sliders, or by
radius+height with a Best-lift / Nearest-grid toggle), and CSV export.
"""
import io
import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import plotly.graph_objects as go

from app.engines import crane

dash.register_page(__name__, path="/lifting/crane-curves", name="Crane curves", category="Lifting")

MUTED = "#64748b"
ACCENT = "#0f766e"
INK = "#0f172a"
GRID = "#e2e8f0"

_MODES = crane.list_modes()
_MODE_OPTS = [{"label": f'{m["label"]} · {m["tag"]}', "value": m["key"]} for m in _MODES]


def _figure(mode_key, marker=None, linkage=None):
    g = crane.contour_grid(mode_key)
    fig = go.Figure()
    fig.add_trace(go.Contour(
        x=g["x"], y=g["y"], z=g["z"],
        colorscale="Turbo", zmin=0, zmax=g["swl_max"],
        contours=dict(showlines=False, start=0, end=g["swl_max"], size=g["swl_max"] / 14),
        colorbar=dict(title="SWL [t]", thickness=14, len=0.9, outlinewidth=0),
        connectgaps=False,
        hovertemplate="R %{x:.1f} m<br>H %{y:.1f} m<br>SWL %{z:.1f} t<extra></extra>",
    ))

    # Crane schematic linkage (pedestal -> main jib -> folding jib -> wire drop)
    if linkage:
        pr, pz = linkage["pivot"]
        er, ez = linkage["elbow"]
        tr, tz = linkage["tip"]
        base_r, _ = linkage["pedestal_base"]
        # pedestal column (deck up to pivot) + jibs
        fig.add_trace(go.Scatter(
            x=[base_r, pr, er, tr], y=[0, pz, ez, tz],
            mode="lines+markers",
            line=dict(color="#0f172a", width=3),
            marker=dict(size=6, color="#0f172a"),
            hoverinfo="skip", showlegend=False,
        ))
        # wire drop from tip down to the load (down to deck level for reference)
        fig.add_trace(go.Scatter(
            x=[tr, tr], y=[tz, 0],
            mode="lines", line=dict(color="#0f172a", width=1, dash="dot"),
            hoverinfo="skip", showlegend=False,
        ))

    if marker:
        fig.add_trace(go.Scatter(
            x=[marker["radius_m"]], y=[marker["height_m"]],
            mode="markers",
            marker=dict(symbol="cross", size=15, color="#0f172a",
                        line=dict(color="white", width=2)),
            hovertemplate=f'{marker["swl_t"]} t<extra></extra>', showlegend=False,
        ))

    fig.update_layout(
        margin=dict(l=55, r=10, t=10, b=45),
        xaxis_title="Radius [m]", yaxis_title="Height above main deck [m]",
        plot_bgcolor="#ffffff", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK), showlegend=False, height=560,
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=True, zerolinecolor="#94a3b8")
    return fig


def _readline(label, value, unit=""):
    return html.Div([
        html.Span(label, style={"color": MUTED, "fontSize": "0.82rem"}),
        html.Span(f"{value}" + (f" {unit}" if unit else ""),
                  style={"color": INK, "fontFamily": "ui-monospace,monospace",
                         "fontWeight": 700}),
    ], style={"display": "flex", "justifyContent": "space-between",
              "padding": "6px 12px", "borderBottom": f"1px solid {GRID}"})


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
    ]
    if r.get("snapped"):
        rows.append(html.Div("Snapped to nearest data point",
                             style={"color": "#b45309", "fontSize": "0.72rem",
                                    "padding": "6px 12px"}))
    return html.Div(rows, style={"background": "#fff", "borderRadius": "10px",
                                 "overflow": "hidden", "border": f"1px solid {GRID}"})


def _num(id_, label, value, step=0.1, unit=""):
    return html.Div([
        html.Label(label + (f" [{unit}]" if unit else ""),
                   style={"fontSize": "0.75rem", "fontWeight": 600, "color": MUTED}),
        dcc.Input(id=id_, type="number", value=value, step=step, debounce=True,
                  style={"width": "100%", "padding": "6px 8px", "borderRadius": "6px",
                         "border": f"1px solid {GRID}", "boxSizing": "border-box"}),
    ], style={"marginBottom": "4px"})


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
                            dcc.Slider(id="cr-main-sl", min=0, max=84, step=0.5, value=30.0,
                                       marks={0: "0", 42: "42", 84: "84"},
                                       tooltip={"placement": "bottom"}),
                            html.Div(style={"height": "10px"}),
                            _num("cr-fold", "Folding jib angle", 45.0, 0.5, "°"),
                            dcc.Slider(id="cr-fold-sl", min=0, max=102, step=0.5, value=45.0,
                                       marks={0: "0", 51: "51", 102: "102"},
                                       tooltip={"placement": "bottom"}),
                        ], style={"paddingTop": "12px"}),
                    ]),
                    dcc.Tab(label="By radius + height", value="rh", children=[
                        html.Div([
                            _num("cr-radius", "Radius", 20.0, 0.5, "m"),
                            dcc.Slider(id="cr-radius-sl", min=7, max=36, step=0.5, value=20.0,
                                       marks={7: "7", 21: "21", 36: "36"},
                                       tooltip={"placement": "bottom"}),
                            html.Div(style={"height": "10px"}),
                            _num("cr-height", "Height above deck", 10.0, 0.5, "m"),
                            dcc.Slider(id="cr-height-sl", min=0, max=45, step=0.5, value=10.0,
                                       marks={0: "0", 22: "22", 45: "45"},
                                       tooltip={"placement": "bottom"}),
                            html.Label("When several solutions exist",
                                       style={"fontSize": "0.75rem", "fontWeight": 600,
                                              "color": MUTED, "marginTop": "10px",
                                              "display": "block"}),
                            dcc.RadioItems(
                                id="cr-rule",
                                options=[{"label": " Best lift (highest SWL)", "value": "best"},
                                         {"label": " Nearest grid point", "value": "nearest"}],
                                value="best",
                                style={"fontSize": "0.85rem", "marginTop": "4px"},
                                labelStyle={"display": "block", "marginBottom": "3px"},
                            ),
                        ], style={"paddingTop": "12px"}),
                    ]),
                ]),
                html.Div(id="cr-readout", style={"marginTop": "14px"}),
                html.Button("Download point as CSV", id="cr-csv-btn", n_clicks=0,
                            style={"marginTop": "12px", "width": "100%", "padding": "9px",
                                   "borderRadius": "8px", "border": "none",
                                   "background": ACCENT, "color": "#fff", "fontWeight": 600,
                                   "cursor": "pointer"}),
                dcc.Download(id="cr-csv"),
            ], style={"flex": "0 0 320px", "minWidth": "300px"}),
        ], style={"display": "flex", "gap": "24px", "flexWrap": "wrap"}),
    ], style={"maxWidth": "1100px"})


# --- sync number <-> slider for main and folding angle ---
@callback(Output("cr-main", "value"), Output("cr-main-sl", "value"),
          Input("cr-main", "value"), Input("cr-main-sl", "value"),
          prevent_initial_call=True)
def _sync_main(num, sl):
    trig = dash.callback_context.triggered_id
    v = sl if trig == "cr-main-sl" else num
    if v is None:
        return no_update, no_update
    v = max(0, min(84, v))
    return v, v


@callback(Output("cr-fold", "value"), Output("cr-fold-sl", "value"),
          Input("cr-fold", "value"), Input("cr-fold-sl", "value"),
          prevent_initial_call=True)
def _sync_fold(num, sl):
    trig = dash.callback_context.triggered_id
    v = sl if trig == "cr-fold-sl" else num
    if v is None:
        return no_update, no_update
    v = max(0, min(102, v))
    return v, v


@callback(
    Output("cr-radius", "value"), Output("cr-radius-sl", "value"),
    Output("cr-radius-sl", "min"), Output("cr-radius-sl", "max"),
    Output("cr-height", "value"), Output("cr-height-sl", "value"),
    Output("cr-height-sl", "min"), Output("cr-height-sl", "max"),
    Input("cr-radius", "value"), Input("cr-radius-sl", "value"),
    Input("cr-height", "value"), Input("cr-height-sl", "value"),
    Input("cr-mode", "value"),
    prevent_initial_call=True,
)
def _sync_rh(r_num, r_sl, h_num, h_sl, mode):
    """
    Dynamic mutual envelope constraint. Whichever control moved is the 'driver';
    we clamp it into the mode's overall span, then re-range and clamp the other
    axis to what's actually reachable at the driver's value. This keeps the
    radius+height pair inside the crane's reach at all times.
    """
    trig = dash.callback_context.triggered_id
    fs = crane.full_span(mode)

    # current values, falling back sensibly
    radius = r_sl if trig == "cr-radius-sl" else r_num
    height = h_sl if trig == "cr-height-sl" else h_num
    if radius is None:
        radius = (fs["r_min"] + fs["r_max"]) / 2
    if height is None:
        height = (fs["h_min"] + fs["h_max"]) / 2

    def clamp(v, lo, hi):
        return max(lo, min(hi, v))

    if trig in ("cr-height", "cr-height-sl", "cr-mode"):
        # height is the driver -> re-range radius to what's reachable at this height
        height = clamp(height, fs["h_min"], fs["h_max"])
        span = crane.reachable_radius_span(mode, height)
        if span:
            rlo, rhi = span
            radius = clamp(radius, rlo, rhi)
        else:
            rlo, rhi = fs["r_min"], fs["r_max"]
        # height slider keeps full mode range; radius slider gets the reachable span
        return (round(radius, 1), round(radius, 1), round(rlo, 1), round(rhi, 1),
                round(height, 1), round(height, 1), round(fs["h_min"], 1), round(fs["h_max"], 1))
    else:
        # radius is the driver -> re-range height to what's reachable at this radius
        radius = clamp(radius, fs["r_min"], fs["r_max"])
        span = crane.reachable_height_span(mode, radius)
        if span:
            hlo, hhi = span
            height = clamp(height, hlo, hhi)
        else:
            hlo, hhi = fs["h_min"], fs["h_max"]
        return (round(radius, 1), round(radius, 1), round(fs["r_min"], 1), round(fs["r_max"], 1),
                round(height, 1), round(height, 1), round(hlo, 1), round(hhi, 1))


def _solve(mode, tab, main, fold, radius, height, rule):
    if tab == "rh":
        return crane.query_point(mode, radius if radius is not None else 0,
                                 height if height is not None else 0, rule=rule or "best")
    return crane.query_angles(mode, main if main is not None else 0,
                              fold if fold is not None else 0)


@callback(
    Output("cr-graph", "figure"),
    Output("cr-readout", "children"),
    Output("cr-store", "data"),
    Input("cr-mode", "value"),
    Input("cr-mode-tab", "value"),
    Input("cr-main", "value"), Input("cr-fold", "value"),
    Input("cr-radius", "value"), Input("cr-height", "value"), Input("cr-rule", "value"),
)
def _update(mode, tab, main, fold, radius, height, rule):
    r = _solve(mode, tab, main, fold, radius, height, rule)
    lk = None
    if r:
        lk = crane.linkage_points(r["main_deg"], r["fold_deg"])
    fig = _figure(mode, marker=r, linkage=lk)
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
    return dict(content=buf.getvalue(), filename=f"crane_{mode}_point.csv")
