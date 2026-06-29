"""
# LOAD_PLANNER_VERSION = "v6.1 defensive"
Load planner — inverse crane query for the 140 t main winch.

Enter a target load; the tool greys out everywhere the crane can't lift it, shows
only the feasible region of the load chart, constrains the jib-angle sliders to
feasible positions, and reports the point readout plus the maximum outreach and
maximum height achievable at that load.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import plotly.graph_objects as go

from app.engines import crane

dash.register_page(__name__, path="/lifting/load-planner", name="Load Planner",
                   category="Lifting", order=3)

MUTED = "#64748b"
ACCENT = "#0f766e"
INK = "#0f172a"
GRID = "#e2e8f0"

_MODES = crane.list_modes()
_MODE_OPTS = [{"label": f'{m["label"]} · {m["tag"]}', "value": m["key"]} for m in _MODES]


def _figure(mode_key, load_t, marker=None, linkage=None, min_height=None):
    g = crane.feasible_grid(mode_key, load_t, min_height=min_height)
    fig = go.Figure()
    # full envelope outline (faint grey) so the user sees what's been excluded
    full = crane.contour_grid(mode_key)
    fig.add_trace(go.Contour(
        x=full["x"], y=full["y"], z=full["z"],
        colorscale=[[0, "#eef2f7"], [1, "#eef2f7"]], showscale=False,
        contours=dict(showlines=False), hoverinfo="skip", connectgaps=False,
    ))
    # feasible region in colour
    fig.add_trace(go.Contour(
        x=g["x"], y=g["y"], z=g["z"],
        colorscale="Turbo", zmin=0, zmax=g["swl_max"],
        contours=dict(showlines=False, start=0, end=g["swl_max"], size=g["swl_max"] / 14),
        colorbar=dict(title="SWL [t]", thickness=14, len=0.9, outlinewidth=0),
        connectgaps=False,
        hovertemplate="R %{x:.1f} m<br>H %{y:.1f} m<br>SWL %{z:.1f} t<extra></extra>",
    ))
    # minimum hook-height floor: dashed line marking the excluded band below it
    if min_height is not None:
        fig.add_hline(y=float(min_height), line=dict(color="#b45309", width=1.5, dash="dash"),
                      annotation_text=f"min hook height {float(min_height):g} m",
                      annotation_position="top left",
                      annotation_font=dict(color="#b45309", size=11))
    if linkage:
        pr, pz = linkage["pivot"]; er, ez = linkage["elbow"]; tr, tz = linkage["tip"]
        base_r, _ = linkage["pedestal_base"]
        fig.add_trace(go.Scatter(x=[base_r, pr, er, tr], y=[0, pz, ez, tz],
            mode="lines+markers", line=dict(color="#0f172a", width=3),
            marker=dict(size=6, color="#0f172a"), hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=[tr, tr], y=[tz, 0], mode="lines",
            line=dict(color="#0f172a", width=1, dash="dot"), hoverinfo="skip", showlegend=False))
    if marker:
        fig.add_trace(go.Scatter(x=[marker["radius_m"]], y=[marker["height_m"]],
            mode="markers", marker=dict(symbol="cross", size=15, color="#0f172a",
            line=dict(color="white", width=2)),
            hovertemplate=f'{marker["swl_t"]} t<extra></extra>', showlegend=False))
    fig.update_layout(margin=dict(l=55, r=10, t=10, b=45),
        xaxis_title="Radius [m]", yaxis_title="Height above main deck [m]",
        plot_bgcolor="#ffffff", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK), showlegend=False, height=560)
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=True, zerolinecolor="#94a3b8")
    return fig


def _readline(label, value, unit="", strong=False):
    return html.Div([
        html.Span(label, style={"color": MUTED, "fontSize": "0.82rem"}),
        html.Span(f"{value}" + (f" {unit}" if unit else ""),
                  style={"color": ACCENT if strong else INK,
                         "fontFamily": "ui-monospace,monospace", "fontWeight": 700}),
    ], style={"display": "flex", "justifyContent": "space-between",
              "padding": "6px 12px", "borderBottom": f"1px solid {GRID}"})


def _readout_panel(r, extremes, load_t, feasible, min_height=None):
    if not feasible:
        if min_height is not None:
            msg = (f"No crane position can lift {load_t} t with the hook at or above "
                   f"{float(min_height):g} m in this mode.")
        else:
            msg = f"No crane position can lift {load_t} t in this mode."
        return html.Div(msg, style={"color": "#b45309", "padding": "12px", "fontWeight": 600})
    rows = []
    if extremes:
        rows += [
            _readline("Max outreach at load", extremes["max_outreach_m"], "m", strong=True),
            _readline("Max height at load", extremes["max_height_m"], "m", strong=True),
        ]
    if min_height is not None:
        rows.append(_readline("Min height under hook", f"{float(min_height):g}", "m"))
    if r:
        rows += [
            _readline("Rated load (SWL)", r["swl_t"], "t"),
            _readline("Radius", r["radius_m"], "m"),
            _readline("Height", r["height_m"], "m"),
            _readline("Main angle", r["main_deg"], "°"),
            _readline("Folding angle", r["fold_deg"], "°"),
            _readline("DAF", r["daf"], ""),
            _readline("Stiffness", r["stiffness_tm"] if r["stiffness_tm"] is not None else "—", "t/m"),
            _readline("Limiting component", r["limit_label"], ""),
        ]
        if r["swl_t"] < load_t:
            rows.append(html.Div("Current position cannot lift the target load",
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
    ], style={"marginBottom": "6px"})


def layout():
    first = _MODES[0]["key"]
    return html.Div([
        html.H3("Load Planner — 140 t main winch", style={"marginBottom": "2px"}),
        html.P("Enter a target load; the chart shows only where the crane can lift it, "
               "and the jib-angle sliders are limited to feasible positions.",
               style={"color": MUTED, "marginTop": 0, "maxWidth": "760px"}),
        dcc.Store(id="lp-store"),
        html.Div([
            html.Div([
                html.Div([
                    html.Label("Lift mode", style={"fontSize": "0.75rem", "fontWeight": 600,
                                                   "color": MUTED, "marginRight": "8px"}),
                    dcc.Dropdown(id="lp-mode", options=_MODE_OPTS, value=first, clearable=False,
                                 style={"width": "260px"}),
                ], style={"display": "flex", "alignItems": "center", "gap": "8px",
                          "marginBottom": "8px"}),
                dcc.Graph(id="lp-graph", config={"displayModeBar": False}),
            ], style={"flex": "1 1 560px", "minWidth": "340px"}),
            html.Div([
                html.Div("Target load", style={"fontWeight": 700, "marginBottom": "8px"}),
                _num("lp-load", "Load to lift", 50.0, 1.0, "t"),
                dcc.Slider(id="lp-load-sl", min=0, max=140, step=1, value=50,
                           marks={0: "0", 70: "70", 140: "140"},
                           tooltip={"placement": "bottom"}),
                html.Div([
                    dcc.Checklist(
                        id="lp-minh-on",
                        options=[{"label": " Limit by minimum height under hook", "value": "on"}],
                        value=[], style={"fontSize": "0.85rem"},
                        inputStyle={"marginRight": "6px"},
                    ),
                    _num("lp-minh", "Min height under hook", 5.0, 0.5, "m"),
                ], style={"marginTop": "12px", "padding": "10px 12px",
                          "background": "#f8fafc", "borderRadius": "8px",
                          "border": f"1px solid {GRID}"}),
                html.Div("Position the crane (feasible range only)",
                         style={"fontWeight": 700, "margin": "16px 0 8px"}),
                _num("lp-main", "Main jib angle", 30.0, 0.5, "°"),
                dcc.Slider(id="lp-main-sl", min=0, max=84, step=0.5, value=30.0,
                           marks={0: "0", 42: "42", 84: "84"},
                           tooltip={"placement": "bottom"}),
                html.Div(style={"height": "10px"}),
                _num("lp-fold", "Folding jib angle", 45.0, 0.5, "°"),
                dcc.Slider(id="lp-fold-sl", min=0, max=102, step=0.5, value=45.0,
                           marks={0: "0", 51: "51", 102: "102"},
                           tooltip={"placement": "bottom"}),
                html.Div(id="lp-readout", style={"marginTop": "14px"}),
            ], style={"flex": "0 0 320px", "minWidth": "300px"}),
        ], style={"display": "flex", "gap": "24px", "flexWrap": "wrap"}),
    ], style={"maxWidth": "1100px"})


# load number <-> slider
@callback(Output("lp-load", "value"), Output("lp-load-sl", "value"),
          Input("lp-load", "value"), Input("lp-load-sl", "value"),
          prevent_initial_call=True)
def _sync_load(num, sl):
    trig = dash.callback_context.triggered_id
    v = sl if trig == "lp-load-sl" else num
    if v is None:
        return no_update, no_update
    v = max(0, min(140, v))
    return v, v


# main/fold sliders constrained to feasible range for the load
@callback(
    Output("lp-main", "value"), Output("lp-main-sl", "value"),
    Output("lp-main-sl", "min"), Output("lp-main-sl", "max"),
    Output("lp-main-sl", "marks"),
    Output("lp-main", "min"), Output("lp-main", "max"),
    Output("lp-fold", "value"), Output("lp-fold-sl", "value"),
    Output("lp-fold-sl", "min"), Output("lp-fold-sl", "max"),
    Output("lp-fold-sl", "marks"),
    Output("lp-fold", "min"), Output("lp-fold", "max"),
    Input("lp-main", "value"), Input("lp-main-sl", "value"),
    Input("lp-fold", "value"), Input("lp-fold-sl", "value"),
    Input("lp-load", "value"), Input("lp-mode", "value"),
    Input("lp-minh-on", "value"), Input("lp-minh", "value"),
    prevent_initial_call=True,
)
def _sync_angles(m_num, m_sl, f_num, f_sl, load, mode, minh_on, minh):
    trig = dash.callback_context.triggered_id
    load = load if load is not None else 0
    mh = float(minh) if (minh_on and "on" in minh_on and minh is not None) else None
    main = m_sl if trig == "lp-main-sl" else m_num
    fold = f_sl if trig == "lp-fold-sl" else f_num
    if main is None:
        main = 30.0
    if fold is None:
        fold = 45.0

    def marks(lo, hi):
        mid = (lo + hi) / 2
        return {round(lo, 1): f"{lo:.0f}", round(mid, 1): f"{mid:.0f}", round(hi, 1): f"{hi:.0f}"}

    mspan = crane.feasible_main_span(mode, load, min_height=mh)
    if not mspan:
        # load (with height limit) infeasible everywhere: full ranges, values unchanged
        return (main, main, 0, 84, marks(0, 84), 0, 84,
                fold, fold, 0, 102, marks(0, 102), 0, 102)
    mlo, mhi = mspan
    if main < mlo or main > mhi:
        main = mhi
    fspan = crane.feasible_fold_span(mode, load, main, min_height=mh) or (0, 102)
    flo, fhi = fspan
    if fold < flo or fold > fhi:
        fold = fhi
    return (round(main, 1), round(main, 1), round(mlo, 1), round(mhi, 1), marks(mlo, mhi),
            round(mlo, 1), round(mhi, 1),
            round(fold, 1), round(fold, 1), round(flo, 1), round(fhi, 1), marks(flo, fhi),
            round(flo, 1), round(fhi, 1))


@callback(
    Output("lp-graph", "figure"),
    Output("lp-readout", "children"),
    Output("lp-store", "data"),
    Input("lp-mode", "value"), Input("lp-load", "value"),
    Input("lp-main", "value"), Input("lp-fold", "value"),
    Input("lp-minh-on", "value"), Input("lp-minh", "value"),
)
def _update(mode, load, main, fold, minh_on, minh):
    load = load if load is not None else 0
    mh = float(minh) if (minh_on and "on" in minh_on and minh is not None) else None
    try:
        extremes = crane.load_extremes(mode, load, min_height=mh)
    except Exception:
        extremes = None
    feasible = extremes is not None
    try:
        r = crane.query_angles(mode, main if main is not None else 0,
                               fold if fold is not None else 0)
    except Exception:
        r = None
    lk = crane.linkage_points(r["main_deg"], r["fold_deg"]) if r else None
    try:
        fig = _figure(mode, load, marker=r, linkage=lk, min_height=mh)
    except Exception:
        # last-resort: plain contour so the chart never goes blank
        g = crane.contour_grid(mode)
        fig = go.Figure(go.Contour(x=g["x"], y=g["y"], z=g["z"], colorscale="Turbo",
                                   contours=dict(showlines=False)))
        fig.update_layout(plot_bgcolor="#ffffff", paper_bgcolor="rgba(0,0,0,0)",
                          height=560, margin=dict(l=55, r=10, t=10, b=45),
                          xaxis_title="Radius [m]", yaxis_title="Height above main deck [m]")
    return fig, _readout_panel(r, extremes, load, feasible, min_height=mh), r
