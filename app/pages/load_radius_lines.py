"""
Capacity Envelope — DSV Picasso 140 t main winch, iso-load line chart.

The same radius-vs-height working envelope as the filled-contour tools, but drawn
as labelled iso-load lines (e.g. 20/40/.../140 t) — the classic crane load-chart
look. Includes the moving crane schematic, a radius+height point read-off, and
CSV export. Line-chart counterpart to the filled contour; same validated crane
data as the Main/Aux Lift Curves and Load-Radius tools.
"""
import io
import dash
from dash import html, dcc, Input, Output, State, callback, no_update
from app.pages._disclaimer import limits_footnote as _limits_footnote
import plotly.graph_objects as go

from app.engines import crane

dash.register_page(__name__, path="/lifting/load-envelope", name="Capacity Envelope",
                   category="Picasso Offshore Crane", order=5)

MUTED = "#64748b"
ACCENT = "#0f766e"
INK = "#0f172a"
GRID = "#e2e8f0"

_MODES = crane.list_modes()
_MODE_OPTS = [{"label": f'{m["label"]} · {m["tag"]}', "value": m["key"]} for m in _MODES]


def _nice_step(vmax):
    """Pick a round iso-load spacing giving roughly 5-8 labelled lines."""
    for s in (5, 10, 20, 25, 50, 100, 200):
        if vmax / s <= 8:
            return s
    return 250


def _figure(mode_key, step=None, marker=None, linkage=None):
    import numpy as np
    g = crane.contour_grid(mode_key)
    step = step or _nice_step(g["swl_max"])

    # Fill the unreachable area (NaN) with 0, then pad a one-cell zero border, so
    # every iso-load level closes into a loop around the region where SWL >= level
    # instead of being cut where the reachable area meets the plot edge.
    x = np.asarray(g["x"], dtype=float)
    y = np.asarray(g["y"], dtype=float)
    z = np.where(np.isnan(np.array(g["z"], dtype=float)), 0.0, g["z"])
    dx = (x[-1] - x[0]) / (len(x) - 1)
    dy = (y[-1] - y[0]) / (len(y) - 1)
    x = np.concatenate([[x[0] - dx], x, [x[-1] + dx]])
    y = np.concatenate([[y[0] - dy], y, [y[-1] + dy]])
    z = np.pad(z, 1, mode="constant", constant_values=0.0)

    fig = go.Figure()
    fig.add_trace(go.Contour(
        x=x, y=y, z=z,
        colorscale="Turbo", zmin=0, zmax=g["swl_max"],
        contours=dict(coloring="lines", showlabels=True,
                      start=step, end=g["swl_max"], size=step,
                      labelfont=dict(size=11, color=INK)),
        line=dict(width=2, smoothing=1.3),
        showscale=False, connectgaps=True,
        hovertemplate="R %{x:.1f} m<br>H %{y:.1f} m<br>SWL %{z:.1f} t<extra></extra>",
    ))

    # crane schematic linkage (pedestal -> main jib -> folding jib -> wire drop)
    if linkage:
        pr, pz = linkage["pivot"]
        er, ez = linkage["elbow"]
        tr, tz = linkage["tip"]
        base_r, _ = linkage["pedestal_base"]
        fig.add_trace(go.Scatter(
            x=[base_r, pr, er, tr], y=[0, pz, ez, tz],
            mode="lines+markers", line=dict(color=INK, width=3),
            marker=dict(size=6, color=INK), hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(
            x=[tr, tr], y=[tz, 0], mode="lines",
            line=dict(color=INK, width=1, dash="dot"),
            hoverinfo="skip", showlegend=False))

    # read-off marker
    if marker:
        fig.add_trace(go.Scatter(
            x=[marker["radius_m"]], y=[marker["height_m"]], mode="markers",
            marker=dict(symbol="cross", size=15, color=INK,
                        line=dict(color="white", width=2)),
            hovertemplate=f'{marker["swl_t"]} t<extra></extra>', showlegend=False))

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


def _marks(lo, hi):
    mid = (lo + hi) / 2
    return {round(lo, 1): f"{lo:.0f}", round(mid, 1): f"{mid:.0f}", round(hi, 1): f"{hi:.0f}"}


def layout():
    first = _MODES[0]["key"]
    fs = crane.full_span(first)
    r0 = round((fs["r_min"] + fs["r_max"]) / 2, 1)
    h0 = round((fs["h_min"] + fs["h_max"]) / 2, 1)
    return html.Div([
        html.H3("Capacity Envelope — 140 t main winch", style={"marginBottom": "2px"}),
        html.P("Iso-load lines over the radius/height working envelope for the DSV "
               "Picasso crane — the load-chart (line) view of the filled contour. "
               "Heights are referenced to the Picasso main deck.",
               style={"color": MUTED, "marginTop": 0, "maxWidth": "760px"}),
        dcc.Store(id="le-store"),
        html.Div([
            html.Div([
                html.Div([
                    html.Label("Lift mode", style={"fontSize": "0.75rem", "fontWeight": 600,
                                                   "color": MUTED, "marginRight": "8px"}),
                    dcc.Dropdown(id="le-mode", options=_MODE_OPTS, value=first, clearable=False,
                                 style={"width": "260px"}),
                    html.Label("Iso spacing [t]", style={"fontSize": "0.75rem", "fontWeight": 600,
                                                         "color": MUTED, "margin": "0 8px 0 16px"}),
                    dcc.Dropdown(id="le-step", clearable=False, value=20,
                                 options=[{"label": f"{s} t", "value": s}
                                          for s in (10, 20, 25, 40, 50, 100)],
                                 style={"width": "110px"}),
                ], style={"display": "flex", "alignItems": "center", "gap": "8px",
                          "marginBottom": "8px", "flexWrap": "wrap"}),
                dcc.Graph(id="le-graph", config={"displayModeBar": False}),
            ], style={"flex": "1 1 560px", "minWidth": "340px"}),
            html.Div([
                html.Div("Read off the envelope", style={"fontWeight": 700, "marginBottom": "8px"}),
                _num("le-radius", "Radius", r0, 0.5, "m"),
                dcc.Slider(id="le-radius-sl", min=round(fs["r_min"], 1), max=round(fs["r_max"], 1),
                           step=0.5, value=r0, marks=_marks(fs["r_min"], fs["r_max"]),
                           tooltip={"placement": "bottom"}),
                html.Div(style={"height": "10px"}),
                _num("le-height", "Height above deck", h0, 0.5, "m"),
                dcc.Slider(id="le-height-sl", min=round(fs["h_min"], 1), max=round(fs["h_max"], 1),
                           step=0.5, value=h0, marks=_marks(fs["h_min"], fs["h_max"]),
                           tooltip={"placement": "bottom"}),
                html.Label("When several solutions exist",
                           style={"fontSize": "0.75rem", "fontWeight": 600, "color": MUTED,
                                  "marginTop": "10px", "display": "block"}),
                dcc.RadioItems(
                    id="le-rule",
                    options=[{"label": " Best lift (highest SWL)", "value": "best"},
                             {"label": " Nearest grid point", "value": "nearest"}],
                    value="best", style={"fontSize": "0.85rem", "marginTop": "4px"},
                    labelStyle={"display": "block", "marginBottom": "3px"}),
                html.Div(id="le-readout", style={"marginTop": "14px"}),
                html.Button("Download point as CSV", id="le-csv-btn", n_clicks=0,
                            style={"marginTop": "12px", "width": "100%", "padding": "9px",
                                   "borderRadius": "8px", "border": "none",
                                   "background": ACCENT, "color": "#fff", "fontWeight": 600,
                                   "cursor": "pointer"}),
                dcc.Download(id="le-csv"),
            ], style={"flex": "0 0 300px", "minWidth": "280px"}),
        ], style={"display": "flex", "gap": "24px", "flexWrap": "wrap"}),
        _limits_footnote(),
    ], style={"maxWidth": "1100px"})


# radius <-> height sliders with dynamic reachable re-ranging (same rule as Aux)
@callback(
    Output("le-radius", "value"), Output("le-radius-sl", "value"),
    Output("le-radius-sl", "min"), Output("le-radius-sl", "max"), Output("le-radius-sl", "marks"),
    Output("le-radius", "min"), Output("le-radius", "max"),
    Output("le-height", "value"), Output("le-height-sl", "value"),
    Output("le-height-sl", "min"), Output("le-height-sl", "max"), Output("le-height-sl", "marks"),
    Output("le-height", "min"), Output("le-height", "max"),
    Input("le-radius", "value"), Input("le-radius-sl", "value"),
    Input("le-height", "value"), Input("le-height-sl", "value"),
    Input("le-mode", "value"),
    prevent_initial_call=True,
)
def _sync_rh(r_num, r_sl, h_num, h_sl, mode):
    trig = dash.callback_context.triggered_id
    fs = crane.full_span(mode)
    radius = r_sl if trig == "le-radius-sl" else r_num
    height = h_sl if trig == "le-height-sl" else h_num
    if radius is None:
        radius = (fs["r_min"] + fs["r_max"]) / 2
    if height is None:
        height = (fs["h_min"] + fs["h_max"]) / 2

    def clamp(v, lo, hi):
        return max(lo, min(hi, v))

    if trig in ("le-height", "le-height-sl", "le-mode"):
        height = clamp(height, fs["h_min"], fs["h_max"])
        rlo, rhi = crane.reachable_radius_span(mode, height) or (fs["r_min"], fs["r_max"])
        if radius < rlo or radius > rhi:
            radius = rhi
        return (
            round(radius, 1), round(radius, 1), round(rlo, 1), round(rhi, 1), _marks(rlo, rhi),
            round(rlo, 1), round(rhi, 1),
            round(height, 1), round(height, 1), round(fs["h_min"], 1), round(fs["h_max"], 1),
            _marks(fs["h_min"], fs["h_max"]), round(fs["h_min"], 1), round(fs["h_max"], 1),
        )
    else:
        radius = clamp(radius, fs["r_min"], fs["r_max"])
        hlo, hhi = crane.reachable_height_span(mode, radius) or (fs["h_min"], fs["h_max"])
        if height < hlo or height > hhi:
            height = hhi
        return (
            round(radius, 1), round(radius, 1), round(fs["r_min"], 1), round(fs["r_max"], 1),
            _marks(fs["r_min"], fs["r_max"]), round(fs["r_min"], 1), round(fs["r_max"], 1),
            round(height, 1), round(height, 1), round(hlo, 1), round(hhi, 1), _marks(hlo, hhi),
            round(hlo, 1), round(hhi, 1),
        )


@callback(
    Output("le-graph", "figure"),
    Output("le-readout", "children"),
    Output("le-store", "data"),
    Input("le-mode", "value"),
    Input("le-step", "value"),
    Input("le-radius", "value"), Input("le-height", "value"), Input("le-rule", "value"),
)
def _update(mode, step, radius, height, rule):
    r = crane.query_point(mode, radius if radius is not None else 0,
                          height if height is not None else 0, rule=rule or "best")
    lk = crane.linkage_points(r["main_deg"], r["fold_deg"]) if r else None
    fig = _figure(mode, step=step, marker=r, linkage=lk)
    return fig, _readout_panel(r), r


@callback(
    Output("le-csv", "data"),
    Input("le-csv-btn", "n_clicks"),
    State("le-store", "data"),
    State("le-mode", "value"),
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
    return dict(content=buf.getvalue(), filename=f"capacity_envelope_{mode}_point.csv")
