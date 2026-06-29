"""
Load-Radius Charts — DSV Picasso 140 t crane, SWL vs outreach.

A MacGregor-style load-radius diagram: for the selected lift mode it plots the
main-hoist capacity envelope (the maximum SWL liftable at each outreach), with
the whip line (the auxiliary winch) and personnel-handling line overlaid, plus a
radius/load read-off and CSV export. All curves are derived from the same
validated crane data that drives the Main and Aux Lift Curves tools.
"""
import io
import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import plotly.graph_objects as go

from app.engines import crane
from app.engines import crane_aux

dash.register_page(__name__, path="/lifting/load-radius", name="Load-Radius Charts",
                   category="Lifting", order=4)

MUTED = "#64748b"
ACCENT = "#0f766e"
INK = "#0f172a"
GRID = "#e2e8f0"
WHIP = "#b45309"
PERS = "#7c3aed"
FAINT = "#cbd5e1"

_MODES = crane.list_modes()
_MODE_OPTS = [{"label": f'{m["label"]} · {m["tag"]}', "value": m["key"]} for m in _MODES]


def _whip_key(main_key):
    """Aux-winch mode that acts as the whip line for a given main mode."""
    return "subsea" if main_key in ("sts1", "sts2") else "deck"


def _figure(mode_key, show_whip, show_pers, overlay_all, marker_r=None):
    fig = go.Figure()

    # faint comparison lines for the other main modes
    if overlay_all:
        for m in _MODES:
            if m["key"] == mode_key:
                continue
            c = crane.swl_vs_radius(m["key"])
            fig.add_trace(go.Scatter(
                x=c["radius"], y=c["swl"], mode="lines",
                line=dict(color=FAINT, width=1), name=m["tag"],
                hovertemplate="%{x:.1f} m · %{y:.0f} t<extra></extra>", showlegend=False))

    # whip line (aux winch)
    if show_whip:
        cw = crane_aux.swl_vs_radius(_whip_key(mode_key))
        fig.add_trace(go.Scatter(
            x=cw["radius"], y=cw["swl"], mode="lines",
            line=dict(color=WHIP, width=2, dash="dash"), name="Whip line (aux)",
            hovertemplate="R %{x:.1f} m<br>Whip %{y:.1f} t<extra></extra>"))

    # personnel handling line (aux personnel mode)
    if show_pers:
        cp = crane_aux.swl_vs_radius("personnel")
        fig.add_trace(go.Scatter(
            x=cp["radius"], y=cp["swl"], mode="lines",
            line=dict(color=PERS, width=2, dash="dot"), name="Personnel handling",
            hovertemplate="R %{x:.1f} m<br>Personnel %{y:.1f} t<extra></extra>"))

    # main hoist curve (bold)
    c = crane.swl_vs_radius(mode_key)
    fig.add_trace(go.Scatter(
        x=c["radius"], y=c["swl"], mode="lines",
        line=dict(color=ACCENT, width=3), name="Main hoist",
        hovertemplate="R %{x:.1f} m<br>SWL %{y:.1f} t<extra></extra>"))

    # read-off marker on the main curve
    if marker_r is not None:
        swl = crane.swl_at_radius(mode_key, marker_r)
        if swl is not None:
            fig.add_trace(go.Scatter(
                x=[marker_r], y=[swl], mode="markers",
                marker=dict(symbol="cross", size=14, color=INK,
                            line=dict(color="white", width=2)),
                hovertemplate=f"{swl:.1f} t @ {marker_r:.1f} m<extra></extra>",
                showlegend=False))
            fig.add_shape(type="line", x0=marker_r, x1=marker_r, y0=0, y1=swl,
                          line=dict(color="#94a3b8", width=1, dash="dot"))

    fig.update_layout(
        margin=dict(l=55, r=12, t=10, b=45),
        xaxis_title="Radius [m]", yaxis_title="SWL [t]",
        plot_bgcolor="#ffffff", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK), height=540,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1),
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, dtick=2)
    fig.update_yaxes(gridcolor=GRID, zeroline=True, zerolinecolor="#94a3b8", rangemode="tozero")
    return fig


def _readline(label, value, unit="", strong=False):
    return html.Div([
        html.Span(label, style={"color": MUTED, "fontSize": "0.82rem"}),
        html.Span(f"{value}" + (f" {unit}" if unit else ""),
                  style={"color": ACCENT if strong else INK,
                         "fontFamily": "ui-monospace,monospace", "fontWeight": 700}),
    ], style={"display": "flex", "justifyContent": "space-between",
              "padding": "6px 12px", "borderBottom": f"1px solid {GRID}"})


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
        html.H3("Load-Radius Charts — 140 t main winch", style={"marginBottom": "2px"}),
        html.P("SWL vs outreach for the DSV Picasso crane. Each curve is the maximum "
               "SWL liftable at that radius (best jib position), with the whip line "
               "(aux winch) and personnel-handling line overlaid.",
               style={"color": MUTED, "marginTop": 0, "maxWidth": "760px"}),
        dcc.Store(id="lr-store"),
        html.Div([
            html.Div([
                html.Div([
                    html.Label("Lift mode", style={"fontSize": "0.75rem", "fontWeight": 600,
                                                   "color": MUTED, "marginRight": "8px"}),
                    dcc.Dropdown(id="lr-mode", options=_MODE_OPTS, value=first, clearable=False,
                                 style={"width": "260px"}),
                ], style={"display": "flex", "alignItems": "center", "gap": "8px",
                          "marginBottom": "8px"}),
                dcc.Graph(id="lr-graph", config={"displayModeBar": False}),
            ], style={"flex": "1 1 560px", "minWidth": "340px"}),
            html.Div([
                html.Div("Read off the chart", style={"fontWeight": 700, "marginBottom": "8px"}),
                _num("lr-radius", "Outreach", 16.0, 0.5, "m"),
                dcc.Slider(id="lr-radius-sl", min=6, max=36, step=0.5, value=16.0,
                           marks={6: "6", 21: "21", 36: "36"},
                           tooltip={"placement": "bottom"}),
                html.Div(id="lr-readout", style={"marginTop": "14px"}),
                html.Div("Reverse: outreach at a load", style={"fontWeight": 700,
                                                               "margin": "18px 0 6px"}),
                _num("lr-load", "Load to lift", 50.0, 1.0, "t"),
                html.Div(id="lr-load-readout", style={"marginTop": "8px"}),
                html.Div("Overlays", style={"fontWeight": 700, "margin": "18px 0 6px"}),
                dcc.Checklist(
                    id="lr-overlays",
                    options=[{"label": " Whip line (aux winch)", "value": "whip"},
                             {"label": " Personnel handling", "value": "pers"},
                             {"label": " Compare all modes (faint)", "value": "all"}],
                    value=["whip", "pers"],
                    style={"fontSize": "0.85rem"},
                    labelStyle={"display": "block", "marginBottom": "3px"},
                    inputStyle={"marginRight": "8px"}),
                html.Button("Download curve as CSV", id="lr-csv-btn", n_clicks=0,
                            style={"marginTop": "14px", "width": "100%", "padding": "9px",
                                   "borderRadius": "8px", "border": "none",
                                   "background": ACCENT, "color": "#fff", "fontWeight": 600,
                                   "cursor": "pointer"}),
                dcc.Download(id="lr-csv"),
            ], style={"flex": "0 0 300px", "minWidth": "280px"}),
        ], style={"display": "flex", "gap": "24px", "flexWrap": "wrap"}),
    ], style={"maxWidth": "1100px"})


# sync radius number <-> slider
@callback(Output("lr-radius", "value"), Output("lr-radius-sl", "value"),
          Input("lr-radius", "value"), Input("lr-radius-sl", "value"),
          prevent_initial_call=True)
def _sync_radius(num, sl):
    trig = dash.callback_context.triggered_id
    v = sl if trig == "lr-radius-sl" else num
    if v is None:
        return no_update, no_update
    v = max(6, min(36, v))
    return v, v


@callback(
    Output("lr-graph", "figure"),
    Output("lr-readout", "children"),
    Output("lr-load-readout", "children"),
    Output("lr-store", "data"),
    Input("lr-mode", "value"),
    Input("lr-radius", "value"),
    Input("lr-load", "value"),
    Input("lr-overlays", "value"),
)
def _update(mode, radius, load, overlays):
    overlays = overlays or []
    show_whip = "whip" in overlays
    show_pers = "pers" in overlays
    overlay_all = "all" in overlays
    r = radius if radius is not None else None

    fig = _figure(mode, show_whip, show_pers, overlay_all, marker_r=r)

    # radius -> SWL read-off
    rows = []
    if r is not None:
        main = crane.swl_at_radius(mode, r)
        whip = crane_aux.swl_at_radius(_whip_key(mode), r)
        pers = crane_aux.swl_at_radius("personnel", r)
        if main is None:
            readout = html.Div("Outreach outside the chart range.",
                               style={"color": MUTED, "padding": "12px"})
        else:
            rows = [_readline("Outreach", round(r, 1), "m"),
                    _readline("Main hoist SWL", round(main, 1), "t", strong=True)]
            if show_whip and whip is not None:
                rows.append(_readline("Whip line SWL", round(whip, 1), "t"))
            if show_pers and pers is not None:
                rows.append(_readline("Personnel SWL", round(pers, 1), "t"))
            readout = html.Div(rows, style={"background": "#fff", "borderRadius": "10px",
                                            "overflow": "hidden", "border": f"1px solid {GRID}"})
    else:
        readout = html.Div("Enter an outreach.", style={"color": MUTED, "padding": "12px"})

    # load -> max radius read-off
    if load is not None and load > 0:
        rmax = crane.max_radius_for_load(mode, load)
        if rmax is None:
            load_ro = html.Div(f"{load:g} t exceeds this mode's capacity at any radius.",
                               style={"color": "#b45309", "fontSize": "0.8rem", "padding": "6px 2px"})
        else:
            load_ro = html.Div([
                html.Span("Max outreach at ", style={"color": MUTED, "fontSize": "0.82rem"}),
                html.Span(f"{load:g} t", style={"fontWeight": 700}),
                html.Span(": ", style={"color": MUTED}),
                html.Span(f"{rmax:.1f} m", style={"fontWeight": 700, "color": ACCENT,
                                                  "fontFamily": "ui-monospace,monospace"}),
            ], style={"padding": "6px 2px"})
    else:
        load_ro = ""

    return fig, readout, load_ro, {"mode": mode, "radius": r}


@callback(
    Output("lr-csv", "data"),
    Input("lr-csv-btn", "n_clicks"),
    State("lr-mode", "value"),
    prevent_initial_call=True,
)
def _csv(_n, mode):
    tag = next((m["tag"] for m in _MODES if m["key"] == mode), mode)
    c = crane.swl_vs_radius(mode)
    cw = crane_aux.swl_vs_radius(_whip_key(mode))
    import numpy as np
    buf = io.StringIO()
    buf.write(f"Load-radius curve,{tag}\n")
    buf.write("Radius [m],Main hoist SWL [t],Whip line SWL [t]\n")
    for rr in c["radius"]:
        main = float(np.interp(rr, c["radius"], c["swl"]))
        whip = float(np.interp(rr, cw["radius"], cw["swl"])) if cw["radius"].size else float("nan")
        buf.write(f"{rr:.2f},{main:.2f},{whip:.2f}\n")
    return dict(content=buf.getvalue(), filename=f"load_radius_{mode}.csv")
