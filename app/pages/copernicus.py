"""
Weather Stats — Copernicus.

Metocean workability for a tender. Pick a work location and the client's fixed
execution window; the tool pulls Copernicus Marine reanalysis (WAVERYS waves,
L4 wind, GLORYS/IBI currents), builds recency-weighted seasonal statistics with
a trend diagnostic, and reports workability at three levels of the water column
— Surface, Mid-water, Bottom — against Hs, wind and per-depth current limits.

Two modes:
  Single task — a weather-sensitive operation needing N continuous hours.
  Campaign    — a programme whose NOMINAL (good-weather) duration is D days;
                weather stretches the calendar around it.

Live data needs Copernicus Marine credentials in the environment
(CMEMS_USERNAME / CMEMS_PASSWORD); without them the page runs on synthetic demo
data behind an amber banner. Reanalysis is cached to the /data volume.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, clientside_callback, no_update
import dash_leaflet as dl
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import pandas as pd

from app.engines import metocean as mo
from app import reports
from app.engines.metocean import (
    build_climatology, ClimatologyConfig, assess,
    classify_region, current_dataset_for, get_series, credentials_present,
    historical_windows, DEPTHS,
)

dash.register_page(__name__, path="/weather/copernicus", name="Copernicus",
                   category="Weather Stats", order=1)

# ---- portal light theme ----
INK = "#0f172a"; MUTED = "#64748b"; DIM = "#94a3b8"; GRID = "#e2e8f0"
ACCENT = "#0f766e"; PANEL = "#ffffff"; SOFT = "#f8fafc"
GO = "#16a34a"; MARG = "#d97706"; NOGO = "#dc2626"
GO_BG = "#dcfce7"; MARG_BG = "#fef9c3"; NOGO_BG = "#fee2e2"
CUR_S = "#0891b2"; CUR_M = "#0d9488"; CUR_B = "#7c3aed"; WAVE = "#2563eb"; WIND = "#ca8a04"
DEPTH_COL = {"cur_surf": CUR_S, "cur_mid": CUR_M, "cur_bottom": CUR_B}

DEFAULT_LAT, DEFAULT_LON = 53.02, 3.24

_CARD = {"background": PANEL, "border": f"1px solid {GRID}", "borderRadius": "10px",
         "padding": "14px 16px", "marginBottom": "14px"}
_H = {"font": "600 13px system-ui", "textTransform": "uppercase", "letterSpacing": ".05em",
      "color": MUTED, "margin": "0 0 10px"}


def _lbl(t):
    return html.Div(t, style={"font": "600 11px system-ui", "letterSpacing": ".03em",
        "textTransform": "uppercase", "color": MUTED, "margin": "0 0 4px"})

def _num(id_, val, step=0.1, **kw):
    return dcc.Input(id=id_, type="number", value=val, step=step, debounce=True,
        style={"width": "100%", "border": f"1px solid {GRID}", "color": INK,
               "font": "13px 'IBM Plex Mono',monospace", "padding": "7px 9px",
               "borderRadius": "6px", "background": PANEL}, **kw)


def layout():
    return html.Div(style={"maxWidth": "1160px"}, children=[
        reports.print_header(),
        html.Div([
            html.H3("Weather Stats — Copernicus", style={"marginBottom": "2px"}),
            html.P("Metocean workability at Surface / Mid-water / Bottom for a work location "
                   "and the client's execution window, from Copernicus Marine reanalysis.",
                   style={"color": MUTED, "marginTop": "0", "maxWidth": "760px"}),
            html.Div(id="ws-src-banner", style={"marginBottom": "12px"}),
        ], className="no-print"),

        html.Div(id="ws-grid", style={"display": "grid", "gridTemplateColumns": "360px 1fr",
                        "gap": "16px", "alignItems": "start"}, children=[

            # ---------- controls ----------
            html.Div(className="no-print", children=[
                html.Div([
                    html.Div("Work location", style=_H),
                    dl.Map(id="ws-map", center=[DEFAULT_LAT, DEFAULT_LON], zoom=6,
                           style={"height": "190px", "borderRadius": "8px", "marginBottom": "10px"},
                           children=[dl.TileLayer(
                               url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"),
                               dl.LayerGroup(id="ws-marker")]),
                    html.Div([
                        html.Div([_lbl("Latitude"), _num("ws-lat", DEFAULT_LAT, 0.0001)]),
                        html.Div([_lbl("Longitude"), _num("ws-lon", DEFAULT_LON, 0.0001)]),
                    ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "10px"}),
                    html.Div(id="ws-regime", style={"marginTop": "10px", "font": "11.5px 'IBM Plex Mono'",
                        "color": INK, "background": SOFT, "border": f"1px solid {GRID}",
                        "borderRadius": "6px", "padding": "8px 10px"}),
                ], style=_CARD),

                html.Div([
                    html.Div("Execution window (client-fixed)", style=_H),
                    dcc.DatePickerRange(id="ws-dates", start_date="2026-09-01", end_date="2026-09-30",
                        display_format="DD MMM YYYY"),
                    html.Div([_lbl("Budget percentile"), dcc.Dropdown(id="ws-pctile",
                        options=[{"label": "P50 (median)", "value": 50},
                                 {"label": "P80 (recommended)", "value": 80},
                                 {"label": "P90 (conservative)", "value": 90}],
                        value=80, clearable=False)], style={"marginTop": "10px"}),
                ], style=_CARD),

                html.Div([
                    html.Div("Climatology", style=_H),
                    html.Div([
                        html.P(["How the wave & wind statistics are built from history. The execution "
                                "period is usually too far ahead to forecast, so workability comes from "
                                "the ", html.B("statistics of past years"), " for the same calendar "
                                "months — not a forecast of the actual days."], style={"margin": "0 0 6px"}),
                        html.P([html.B("Look-back"), " — how many years of reanalysis to use. ~30 balances "
                                "sampling the storm tail against climate drift; the actual span used is "
                                "shown in the results."], style={"margin": "0 0 6px"}),
                        html.P([html.B("Recency weighting"), " — whether recent years count for more, so a "
                                "shifting climate doesn't bias the result. ", html.B("Exponential"),
                                " fades older years smoothly; ", html.B("Linear"), " evenly; ",
                                html.B("None"), " treats all years equally."], style={"margin": "0 0 6px"}),
                        html.P([html.B("Half-life"), " — years at which a year counts half as much as the "
                                "most recent (exponential only)."], style={"margin": "0"}),
                    ], style={"font": "11.5px system-ui", "color": MUTED, "lineHeight": "1.5",
                              "background": SOFT, "border": f"1px solid {GRID}", "borderRadius": "8px",
                              "padding": "10px 11px", "marginBottom": "12px"}),
                    html.Div([
                        html.Div([_lbl("Look-back (yr)"), _num("ws-lookback", 30, 1)]),
                        html.Div([_lbl("Recency half-life"), _num("ws-halflife", 10, 1)]),
                    ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "10px"}),
                    html.Div([_lbl("Recency weighting"), dcc.Dropdown(id="ws-recency",
                        options=[{"label": "Exponential", "value": "exponential"},
                                 {"label": "Linear", "value": "linear"},
                                 {"label": "None (flat)", "value": "none"}],
                        value="exponential", clearable=False)], style={"marginTop": "10px"}),
                ], style=_CARD),

                html.Div([
                    html.Div("Operation", style=_H),
                    dcc.RadioItems(id="ws-mode",
                        options=[{"label": " Single task", "value": "single"},
                                 {"label": " Campaign", "value": "campaign"}],
                        value="single", inline=True,
                        inputStyle={"marginRight": "5px"}, labelStyle={"marginRight": "16px"},
                        style={"marginBottom": "10px", "font": "13px system-ui"}),

                    html.Div(id="ws-single-pane", children=[
                        html.Div([_lbl("Continuous window needed (h)"), _num("ws-dur", 6, 0.5)]),
                        html.Div("A weather-sensitive operation that must run in one unbroken window "
                                 "(a lift, a tie-in).", style={"font": "11px system-ui", "color": DIM,
                                 "marginTop": "6px"}),
                    ]),
                    html.Div(id="ws-campaign-pane", children=[
                        html.Div([_lbl("Nominal duration — good weather (days)"), _num("ws-nom", 20, 1)]),
                        html.Div("The planned working time assuming perfect weather. Weather delay is "
                                 "added on top to give the elapsed calendar time.",
                                 style={"font": "11px system-ui", "color": DIM, "marginTop": "6px"}),
                    ], style={"display": "none"}),
                ], style=_CARD),

                html.Div([
                    html.Div("Operating limits", style=_H),
                    html.Div([
                        html.Div([_lbl("Max Hs (m)"), _num("ws-hs", 1.5, 0.1)]),
                        html.Div([_lbl("Max wind (kn)"), _num("ws-wind", 20, 1)]),
                    ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "10px"}),
                    html.Div("Current limit per depth (kn):", style={"font": "11px system-ui",
                             "color": MUTED, "margin": "10px 0 6px"}),
                    html.Div([
                        html.Div([_lbl("Surface"), _num("ws-cs", 1.0, 0.1)]),
                        html.Div([_lbl("Mid-water"), _num("ws-cm", 0.8, 0.1)]),
                        html.Div([_lbl("Bottom"), _num("ws-cb", 0.6, 0.1)]),
                    ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr 1fr", "gap": "8px"}),
                ], style=_CARD),

                html.Button("Assess workability", id="ws-run", n_clicks=0,
                    style={"width": "100%", "background": ACCENT, "color": "#fff",
                           "border": "0", "padding": "11px", "borderRadius": "8px", "cursor": "pointer",
                           "font": "600 14px system-ui"}),
            ]),

            # ---------- results ----------
            html.Div([
                html.Div(html.Button([html.Span("\u2913\u2002"), "Print result"],
                    id="ws-print-btn", n_clicks=0,
                    style={"background": PANEL, "border": f"1px solid {GRID}", "color": INK,
                           "padding": "7px 12px", "borderRadius": "6px", "cursor": "pointer",
                           "font": "600 12px system-ui"}),
                    className="no-print", style={"display": "flex", "justifyContent": "flex-end",
                                                 "marginBottom": "10px"}),
                html.Div(id="ws-print-sink", style={"display": "none"}),
                dcc.Loading(type="default", color=ACCENT, children=html.Div(id="ws-results", children=[
                    html.Div("Set location, window, operation and limits, then run.",
                             style={"padding": "56px 20px", "textAlign": "center", "color": DIM,
                                    "border": f"1px dashed {GRID}", "borderRadius": "10px",
                                    "font": "15px system-ui"})])),
            ]),
        ]),
        reports.print_footer(),
    ])


# ============================ callbacks ============================
dash.clientside_callback(
    "function(n){ if(n){ setTimeout(function(){ window.print(); }, 60); } return ''; }",
    Output("ws-print-sink", "children"), Input("ws-print-btn", "n_clicks"),
    prevent_initial_call=True,
)


@callback(Output("ws-src-banner", "children"), Input("ws-run", "n_clicks"))
def _banner(_):
    if credentials_present():
        return html.Div("● Live Copernicus Marine reanalysis",
            style={"font": "12px 'IBM Plex Mono'", "color": GO, "background": GO_BG,
                   "border": f"1px solid {GO}", "borderRadius": "6px", "padding": "6px 10px",
                   "display": "inline-block"})
    return html.Div("● DEMO data — set CMEMS_USERNAME / CMEMS_PASSWORD in the environment for live reanalysis",
        style={"font": "12px 'IBM Plex Mono'", "color": MARG, "background": MARG_BG,
               "border": f"1px solid {MARG}", "borderRadius": "6px", "padding": "6px 10px",
               "display": "inline-block"})


@callback(Output("ws-lat", "value"), Output("ws-lon", "value"),
          Input("ws-map", "clickData"), prevent_initial_call=True)
def _mapclick(cd):
    if not cd or "latlng" not in cd:
        return no_update, no_update
    return round(cd["latlng"]["lat"], 4), round(cd["latlng"]["lng"], 4)


@callback(Output("ws-marker", "children"), Output("ws-map", "center"),
          Output("ws-regime", "children"),
          Input("ws-lat", "value"), Input("ws-lon", "value"))
def _marker(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return no_update, no_update, "Regime: —"
    reg = classify_region(lat, lon)
    cds = current_dataset_for(lat, lon)
    label = html.Span(["Regime: ", html.B(reg.label, style={"color": ACCENT}),
        html.Span(f"  ·  currents {cds.product_id.split('_')[0]} "
                  f"{'(tide-resolving)' if reg.prefer_ibi else '(daily-mean)'}",
                  style={"color": DIM})])
    return [dl.Marker(position=[lat, lon])], [lat, lon], label


@callback(Output("ws-single-pane", "style"), Output("ws-campaign-pane", "style"),
          Input("ws-mode", "value"))
def _panes(mode):
    show, hide = {"display": "block"}, {"display": "none"}
    return (show, hide) if mode == "single" else (hide, show)


@callback(Output("ws-results", "children"),
          Input("ws-run", "n_clicks"),
          State("ws-lat", "value"), State("ws-lon", "value"),
          State("ws-dates", "start_date"), State("ws-dates", "end_date"),
          State("ws-pctile", "value"),
          State("ws-lookback", "value"), State("ws-halflife", "value"),
          State("ws-recency", "value"), State("ws-mode", "value"),
          State("ws-dur", "value"), State("ws-nom", "value"),
          State("ws-hs", "value"), State("ws-wind", "value"),
          State("ws-cs", "value"), State("ws-cm", "value"), State("ws-cb", "value"),
          prevent_initial_call=True)
def _run(_, lat, lon, sd, ed, pctile, lookback, halflife, recency, mode,
         dur, nom, hs, wind, cs, cm, cb):
    try:
        lat, lon = float(lat), float(lon)
        start, end = pd.Timestamp(sd), pd.Timestamp(ed)
        cfg = ClimatologyConfig(lookback_years=int(lookback or 30),
                                recency=recency or "exponential",
                                half_life_years=float(halflife or 10), trend_stat="p95")
        cur_limits = {"cur_surf": float(cs or 1.0), "cur_mid": float(cm or 0.8),
                      "cur_bottom": float(cb or 0.6)}
        hs = float(hs or 1.5); wind = float(wind or 20)
    except Exception as e:
        return _error(f"Check inputs: {e}")

    try:
        df, source, meta = get_series(lat, lon)   # depth model is internal now
    except Exception as e:
        return _error(f"Data unavailable: {e}")

    try:
        clim = build_climatology(df, lat, lon, start, end, cfg)
        res = assess(df, start, end, mode, hs_max=hs, wind_max=wind, cur_limits=cur_limits,
                     duration_h=float(dur or 6), nominal_days=float(nom or 20), cfg=cfg, n_runs=500)
    except Exception as e:
        return _error(f"Assessment failed for this window: {e}")
    strip = _strip(df, start, end, cfg, dict(hs=hs, wind=wind, **cur_limits))
    return _render(res, clim, source, int(pctile or 80), start, end, strip, meta)


# ---------- helpers ----------
def _error(msg):
    return html.Div(msg, style={"padding": "18px", "color": NOGO, "background": NOGO_BG,
        "border": f"1px solid {NOGO}", "borderRadius": "10px", "font": "13px 'IBM Plex Mono'"})


def _strip(df, start, end, cfg, lim):
    wins, L = historical_windows(df, start, end, cfg, overrun_buffer_days=0)
    if not wins:
        return go.Figure()
    arr = wins[-1][2]
    n = min(L, len(arr["hs"]))
    t = np.arange(n) / 24.0
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.07,
                        subplot_titles=("Current (kn)", "Wave Hs (m)", "Wind (kn)"))
    fig.add_trace(go.Scatter(x=t, y=arr["cur_surf"][:n], name="Surface", line=dict(color=CUR_S, width=1.2)), 1, 1)
    fig.add_trace(go.Scatter(x=t, y=arr["cur_mid"][:n], name="Mid", line=dict(color=CUR_M, width=1.2)), 1, 1)
    fig.add_trace(go.Scatter(x=t, y=arr["cur_bottom"][:n], name="Bottom", line=dict(color=CUR_B, width=1.2)), 1, 1)
    for key in ("cur_surf", "cur_mid", "cur_bottom"):
        fig.add_hline(y=lim[key], line=dict(color=DEPTH_COL[key], dash="dot", width=1), row=1, col=1)
    fig.add_trace(go.Scatter(x=t, y=arr["hs"][:n], line=dict(color=WAVE, width=1.3), showlegend=False), 2, 1)
    fig.add_hline(y=lim["hs"], line=dict(color=NOGO, dash="dot", width=1), row=2, col=1)
    fig.add_trace(go.Scatter(x=t, y=arr["wind"][:n], line=dict(color=WIND, width=1.3), showlegend=False), 3, 1)
    fig.add_hline(y=lim["wind"], line=dict(color=NOGO, dash="dot", width=1), row=3, col=1)
    fig.update_xaxes(title_text="days into window", row=3, col=1)
    fig.update_layout(height=380, margin=dict(l=44, r=14, t=26, b=34),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#ffffff",
        font=dict(color=MUTED, size=10, family="IBM Plex Mono"),
        legend=dict(orientation="h", y=1.15, x=0, font=dict(size=10)))
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    for a in fig.layout.annotations:
        a.font.update(size=11, color=INK)
    return fig


def _depth_card_single(d):
    col = GO if d.exists_pct >= 80 else (MARG if d.exists_pct >= 50 else NOGO)
    bg = GO_BG if d.exists_pct >= 80 else (MARG_BG if d.exists_pct >= 50 else NOGO_BG)
    dm = f"{d.depth_m:.0f} m" if d.depth_m is not None else "n/a"
    avail = "" if d.available else " · current n/a, on Hs+wind"
    return html.Div([
        html.Div([html.Span("● ", style={"color": DEPTH_COL[d.cur_key]}),
                  html.B(d.label), html.Span(f"  {dm}{avail}", style={"color": DIM, "fontSize": "11px"})],
                 style={"font": "13px system-ui", "marginBottom": "4px"}),
        html.Div([f"{d.exists_pct:.0f}", html.Span(" %", style={"fontSize": "14px", "color": MUTED})],
                 style={"font": "700 30px system-ui", "color": col, "lineHeight": "1"}),
        html.Div(f"of years had the window · wait P50 {d.wait_p50/24:.1f} d / P80 {d.wait_p80/24:.1f} d",
                 style={"font": "11px system-ui", "color": MUTED, "marginTop": "3px"}),
    ], style={"background": bg, "border": f"1px solid {col}", "borderRadius": "10px", "padding": "12px 14px"})


def _depth_card_campaign(d, pctile, L_days):
    pick = {50: d.elapsed_p50, 80: d.elapsed_p80, 90: d.elapsed_p90}[pctile] / 24
    fits = pick <= L_days and not d.censored
    col = GO if fits else NOGO
    bg = GO_BG if fits else NOGO_BG
    dm = f"{d.depth_m:.0f} m" if d.depth_m is not None else "n/a"
    avail = "" if d.available else " · current n/a, on Hs+wind"
    if d.censored:
        big = [f"≥{d.horizon_h/24:.0f}", html.Span(" d", style={"fontSize": "14px", "color": MUTED})]
        sub = f"does not complete in {d.horizon_h/24:.0f} d at these limits · INFEASIBLE"
    else:
        big = [f"{pick:.0f}", html.Span(" d elapsed", style={"fontSize": "14px", "color": MUTED})]
        sub = (f"P50 {d.elapsed_p50/24:.0f} · P80 {d.elapsed_p80/24:.0f} · P90 {d.elapsed_p90/24:.0f} d · "
               + ("fits" if fits else "OVERRUNS"))
    return html.Div([
        html.Div([html.Span("● ", style={"color": DEPTH_COL[d.cur_key]}),
                  html.B(d.label), html.Span(f"  {dm}{avail}", style={"color": DIM, "fontSize": "11px"})],
                 style={"font": "13px system-ui", "marginBottom": "4px"}),
        html.Div(big, style={"font": "700 30px system-ui", "color": col, "lineHeight": "1"}),
        html.Div(sub, style={"font": "11px system-ui", "color": MUTED, "marginTop": "3px"}),
    ], style={"background": bg, "border": f"1px solid {col}", "borderRadius": "10px", "padding": "12px 14px"})


def _progress_chart(res, L_days):
    fig = go.Figure()
    for d in res.depths:
        if not d.progress_days:
            continue
        fig.add_trace(go.Scatter(x=d.progress_days, y=d.progress_pct, name=d.label,
            line=dict(color=DEPTH_COL[d.cur_key], width=1.6)))
    fig.add_hline(y=100, line=dict(color=MUTED, dash="dot", width=1))
    fig.add_vline(x=L_days, line=dict(color=NOGO, dash="dash", width=1),
                  annotation_text="client window", annotation_position="top")
    fig.update_layout(height=240, margin=dict(l=48, r=14, t=14, b=36),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#ffffff",
        font=dict(color=MUTED, size=10, family="IBM Plex Mono"),
        legend=dict(orientation="h", y=1.16, x=0, font=dict(size=10)),
        xaxis_title="elapsed days", yaxis_title="work complete (%)")
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, range=[0, 105])
    return fig


def _render(res, clim, source, pctile, start, end, strip, meta=None):
    L_days = (end - start).days or 1
    meta = meta or {}
    banner = None
    if source == "demo":
        err = meta.get("error", "")
        msg = ("Showing DEMO data — configure CMEMS credentials for live reanalysis."
               if not err else f"Live fetch failed, showing DEMO data. Reason: {err}")
        banner = html.Div(msg, style={"font": "12px 'IBM Plex Mono'", "color": MARG,
            "background": MARG_BG, "border": f"1px solid {MARG}", "borderRadius": "8px",
            "padding": "8px 10px", "marginBottom": "12px"})
    elif source == "live" and meta.get("current_source") == "GLOBAL":
        banner = html.Div("Live reanalysis. Currents from global GLORYS (regional IBI unavailable "
                          "here) — coarser, daily-mean, no tidal cycle. " + meta.get("current_note", ""),
            style={"font": "12px 'IBM Plex Mono'", "color": MUTED, "background": SOFT,
                   "border": f"1px solid {GRID}", "borderRadius": "8px", "padding": "8px 10px",
                   "marginBottom": "12px"})
    elif source == "live":
        banner = html.Div("Live reanalysis. " + meta.get("current_note", ""),
            style={"font": "12px 'IBM Plex Mono'", "color": MUTED, "background": SOFT,
                   "border": f"1px solid {GRID}", "borderRadius": "8px", "padding": "8px 10px",
                   "marginBottom": "12px"})

    if res.mode == "single":
        title = f"Single task · {res.duration_h} h continuous window · {res.n_years} historical years"
        cards = [_depth_card_single(d) for d in res.depths]
    else:
        title = (f"Campaign · {res.nominal_hours/24:.0f} d nominal work · client window {L_days} d · "
                 f"P{pctile} · {res.n_years} historical years")
        cards = [_depth_card_campaign(d, pctile, L_days) for d in res.depths]

    head = html.Div([html.Div(title, style=_H),
        html.Div(cards, style={"display": "grid", "gridTemplateColumns": "repeat(3,1fr)", "gap": "10px"})],
        style=_CARD)

    progress_panel = None
    if res.mode == "campaign":
        progress_panel = html.Div([
            html.Div("Cumulative progress · nominal work vs elapsed calendar (weather delay)", style=_H),
            dcc.Graph(figure=_progress_chart(res, L_days), config={"displayModeBar": False}),
            html.Div("Each curve is the mean fraction of the nominal work completed as calendar days "
                     "elapse; the gap between the client-window line and where a curve reaches 100% is "
                     "the weather delay. A curve that flattens is a stretch of unworkable weather.",
                     style={"font": "11px system-ui", "color": DIM, "marginTop": "4px"}),
        ], style=_CARD)

    def trend_line(k):
        tr = clim.trends.get(k)
        if not tr:
            return None
        sig = "significant" if tr.significant else "not significant"
        c = MARG if tr.significant else DIM
        return html.Div([html.B(k.upper() + " ", style={"color": INK}),
            f"{tr.slope_per_decade:+.3f}/decade ({tr.stat}), p={tr.p_value:.3f} ",
            html.Span(f"[{sig}]", style={"color": c})],
            style={"font": "11.5px 'IBM Plex Mono'", "margin": "2px 0"})

    clim_panel = html.Div([
        html.Div("Climatology & trend", style=_H),
        html.Div(f"months {clim.months} · look-back {clim.lookback_years} y · recency {clim.recency}",
                 style={"font": "11px system-ui", "color": DIM, "marginBottom": "8px"}),
        *[html.Div([html.B(k.upper() + "  ", style={"color": INK}),
                    f"mean {s.w_mean:.2f} · P50 {s.p50:.2f} · P80 {s.p80:.2f} · P90 {s.p90:.2f}"],
                   style={"font": "11.5px 'IBM Plex Mono'", "color": MUTED, "margin": "2px 0"})
          for k, s in clim.summaries.items()],
        html.Hr(style={"border": "none", "borderTop": f"1px solid {GRID}", "margin": "10px 0"}),
        *[x for x in (trend_line("hs"), trend_line("wind")) if x],
    ], style=_CARD)

    return html.Div([
        banner, head, progress_panel,
        html.Div([html.Div("Metocean strip · representative recent-year window", style=_H),
                  dcc.Graph(figure=strip, config={"displayModeBar": False})], style=_CARD),
        clim_panel,
        html.Div("Currents from daily-mean reanalysis don't resolve the tidal cycle at tide-dominated "
                 "sites; confirm slack against tide tables. Bottom is the deepest wet model level (the "
                 "seabed at this cell); mid-water is half that depth. Wave/wind statistics are "
                 "recency-weighted over the look-back window.",
                 style={"font": "11px system-ui", "color": DIM, "lineHeight": "1.5"}),
    ])
