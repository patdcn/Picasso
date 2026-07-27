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
    get_series_era5_async, era5_credentials_present,
    historical_windows, window_bands, DEPTHS,
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
                    html.Div([html.Div("Work location", style={**_H, "margin": 0}),
                        html.Button("⤢ Expand", id="ws-map-expand", n_clicks=0, className="no-print",
                            style={"marginLeft": "auto", "background": SOFT, "border": f"1px solid {GRID}",
                                   "borderRadius": "6px", "padding": "3px 8px", "cursor": "pointer",
                                   "font": "600 10px system-ui", "color": MUTED})],
                        style={"display": "flex", "alignItems": "center", "marginBottom": "10px"}),
                    html.Div(id="ws-map-wrap", className="ws-map-wrap", children=[
                        dl.Map(id="ws-map", center=[DEFAULT_LAT, DEFAULT_LON], zoom=6,
                               style={"height": "100%", "width": "100%", "borderRadius": "8px"},
                               children=[
                            dl.LayersControl(position="topright", collapsed=True, children=[
                                dl.BaseLayer(dl.TileLayer(
                                    url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
                                    attribution="© OpenStreetMap, © CARTO"),
                                    name="Light map", checked=True),
                                dl.BaseLayer(dl.TileLayer(
                                    url="https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}",
                                    attribution="Esri Ocean Basemap"),
                                    name="Ocean / bathymetry", checked=False),
                                dl.Overlay(dl.TileLayer(
                                    url="https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png",
                                    attribution="© OpenSeaMap contributors (CC-BY-SA)"),
                                    name="Sea marks (OpenSeaMap)", checked=False),
                                dl.Overlay(dl.WMSTileLayer(
                                    url="https://ows.emodnet-humanactivities.eu/wms",
                                    layers="platforms", format="image/png", transparent=True,
                                    attribution="EMODnet Human Activities (CC-BY 4.0)"),
                                    name="Oil & gas platforms (EMODnet)", checked=False),
                                dl.Overlay(dl.WMSTileLayer(
                                    url="https://ows.emodnet-humanactivities.eu/wms",
                                    layers="pipelines", format="image/png", transparent=True,
                                    attribution="EMODnet Human Activities (CC-BY 4.0)"),
                                    name="Pipelines (EMODnet)", checked=False),
                                dl.Overlay(dl.WMSTileLayer(
                                    url="https://ows.emodnet-humanactivities.eu/wms",
                                    layers="activelicenses", format="image/png", transparent=True,
                                    attribution="EMODnet Human Activities (CC-BY 4.0)"),
                                    name="Licence blocks (EMODnet)", checked=False),
                                dl.Overlay(dl.WMSTileLayer(
                                    url="https://data.nstauthority.co.uk/arcgis/services/Public_WGS84/UKCS_Licensed_and_Unlicensed_Blocks_WGS84/MapServer/WMSServer",
                                    layers="0", format="image/png", transparent=True,
                                    attribution="NSTA / UK OGL"),
                                    name="UK blocks (NSTA)", checked=False),
                            ]),
                            dl.LayerGroup(id="ws-marker")]),
                    ]),
                    html.Div([
                        html.Div([_lbl("Latitude"), _num("ws-lat", DEFAULT_LAT, 0.0001)]),
                        html.Div([_lbl("Longitude"), _num("ws-lon", DEFAULT_LON, 0.0001)]),
                    ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "10px",
                              "marginTop": "10px"}),
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
                    dcc.Checklist(id="ws-era5",
                        options=[{"label": " Compare Hs & wind vs ERA5 (independent 2nd source)",
                                  "value": "on"}],
                        value=[], inputStyle={"marginRight": "6px"},
                        style={"font": "12px system-ui", "color": MUTED, "marginTop": "12px"}),
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

dash.clientside_callback(
    "function(n){ const expanded = (n % 2 === 1);"
    " setTimeout(function(){ window.dispatchEvent(new Event('resize')); }, 250);"
    " return expanded ? 'ws-map-wrap ws-map-expanded' : 'ws-map-wrap'; }",
    Output("ws-map-wrap", "className"),
    Input("ws-map-expand", "n_clicks"),
    prevent_initial_call=True,
)

dash.clientside_callback(
    "function(d){ const s=k=>({display: d===k ? 'block':'none'}); "
    "return [s('cur_surf'), s('cur_mid'), s('cur_bottom')]; }",
    Output("ws-screen-cur_surf", "style"),
    Output("ws-screen-cur_mid", "style"),
    Output("ws-screen-cur_bottom", "style"),
    Input("ws-depth", "value"),
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
    is_ibi = cds.product_id.startswith("IBI")
    label = html.Span(["Regime: ", html.B(reg.label, style={"color": ACCENT}),
        html.Span(f"  ·  currents {'IBI (tide-resolving)' if is_ibi else 'GLORYS (global, daily-mean)'}",
                  style={"color": DIM})])
    return [dl.Marker(position=[lat, lon])], [lat, lon], label


@callback(Output("ws-single-pane", "style"), Output("ws-campaign-pane", "style"),
          Input("ws-mode", "value"))
def _panes(mode):
    show, hide = {"display": "block"}, {"display": "none"}
    return (show, hide) if mode == "single" else (hide, show)


def _assemble(lat, lon, sd, ed, pctile, lookback, halflife, recency, mode,
              dur, nom, hs, wind, cs, cm, cb, era5_on):
    """Build the results view. Returns (children, era5_pending)."""
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
        return _error(f"Check inputs: {e}"), False

    try:
        df, source, meta = get_series(lat, lon)
    except Exception as e:
        return _error(f"Data unavailable: {e}"), False

    try:
        clim = build_climatology(df, lat, lon, start, end, cfg)
        res = assess(df, start, end, mode, hs_max=hs, wind_max=wind, cur_limits=cur_limits,
                     duration_h=float(dur or 6), nominal_days=float(nom or 20), cfg=cfg, n_runs=500)
        bands, _L = window_bands(df, start, end, cfg)
    except Exception as e:
        return _error(f"Assessment failed for this window: {e}"), False

    era5_bands, era5_note, era5_pending = None, "", False
    if era5_on and "on" in era5_on:
        status, e5df, e5msg = get_series_era5_async(lat, lon, start, end, cfg)
        if status == "ready" and e5df is not None:
            try:
                era5_bands, _ = window_bands(e5df, start, end, cfg)
                era5_note = "ERA5 overlay (dashed)."
            except Exception as e:
                era5_note = f"ERA5 comparison unavailable: {e}"
        elif status == "pending":
            era5_note = e5msg
            era5_pending = True
        else:
            era5_note = e5msg

    ui = dict(lat=lat, lon=lon, mode=mode, hs=hs, wind=wind, cur_limits=cur_limits,
              dur=float(dur or 6), nom=float(nom or 20), cfg=cfg, bands=bands,
              era5_bands=era5_bands, era5_note=era5_note)
    return _render(res, clim, source, int(pctile or 80), start, end, meta, ui), era5_pending


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
          State("ws-era5", "value"),
          prevent_initial_call=True)
def _run(_, lat, lon, sd, ed, pctile, lookback, halflife, recency, mode,
         dur, nom, hs, wind, cs, cm, cb, era5_on):
    args = [lat, lon, sd, ed, pctile, lookback, halflife, recency, mode,
            dur, nom, hs, wind, cs, cm, cb, era5_on]
    children, pending = _assemble(*args)
    if pending:
        # ERA5 is fetching in the background; poll the cache until it's ready
        return html.Div([children,
            dcc.Store(id="ws-era5-store", data=args),
            dcc.Interval(id="ws-era5-poll", interval=6000, n_intervals=0)])
    return children


@callback(Output("ws-results", "children", allow_duplicate=True),
          Output("ws-era5-poll", "disabled"),
          Input("ws-era5-poll", "n_intervals"),
          State("ws-era5-store", "data"),
          prevent_initial_call=True)
def _poll_era5(_n, args):
    if not args:
        return no_update, True
    children, pending = _assemble(*args)
    if pending:
        return no_update, False          # still fetching — keep polling
    return html.Div([children]), True    # ready (or failed) — replace, stop polling


# ---------- helpers ----------
def _error(msg):
    return html.Div(msg, style={"padding": "18px", "color": NOGO, "background": NOGO_BG,
        "border": f"1px solid {NOGO}", "borderRadius": "10px", "font": "13px 'IBM Plex Mono'"})


DEPTH_LABEL = {"cur_surf": "Surface", "cur_mid": "Mid-water", "cur_bottom": "Bottom"}

def _band(fig, row, x, b, color, name, unit="", legend=True, band_legend=None):
    if b is None:
        return
    p10, p50, p90 = b["p10"], b["p50"], b["p90"]
    import numpy as _np
    if not _np.any(_np.isfinite(p50)):
        return
    fig.add_trace(go.Scatter(x=list(x) + list(x[::-1]),
        y=list(p90) + list(p10[::-1]), fill="toself",
        fillcolor=_rgba(color, 0.13), line=dict(width=0), hoverinfo="skip",
        name=(band_legend or ""), showlegend=bool(band_legend),
        legendgroup="cmems_band"), row, 1)
    fig.add_trace(go.Scatter(x=x, y=p50, line=dict(color=color, width=1.8),
        name=name + " (P50)", showlegend=legend,
        hovertemplate=f"{name}: %{{y:.2f}} {unit}<extra></extra>"), row, 1)


def _era5_over(fig, row, xe, b, unit, name, band_legend=False):
    import numpy as _np
    if b is None or not _np.any(_np.isfinite(b["p50"])):
        return
    p10, p50, p90 = b["p10"], b["p50"], b["p90"]
    fig.add_trace(go.Scatter(x=list(xe) + list(xe[::-1]),
        y=list(p90) + list(p10[::-1]), fill="toself",
        fillcolor=_rgba(INK, 0.07), line=dict(width=0), hoverinfo="skip",
        name="ERA5 P10–P90 spread", showlegend=band_legend,
        legendgroup="era5_band"), row, 1)
    fig.add_trace(go.Scatter(x=xe, y=p50, line=dict(color=INK, width=1.3, dash="dash"),
        name=name + " (P50)", showlegend=True,
        hovertemplate=f"{name}: %{{y:.2f}} {unit}<extra></extra>"), row, 1)

def _rgba(hexc, a):
    h = hexc.lstrip("#")
    return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{a})"

def _strip(bands, L, lim, depth_key, era5_bands=None):
    """Climatological band strip for ONE depth: current(depth), Hs, wind.
    Each panel shows the P50 line with a P10-P90 shaded band across look-back years.
    If era5_bands is given, ERA5's P50 is overlaid (dashed) on Hs and wind."""
    import numpy as np
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                        subplot_titles=(f"Current — {DEPTH_LABEL[depth_key]} (kn)",
                                        "Wave Hs (m)", "Wind (kn)"))
    if bands is None:
        return fig
    L = len(bands["hs"]["p50"])
    x = np.arange(L) / 24.0
    _band(fig, 1, x, bands.get(depth_key), DEPTH_COL[depth_key], f"CMEMS {DEPTH_LABEL[depth_key]}",
          "kn", band_legend="CMEMS P10–P90 spread")
    fig.add_hline(y=lim[depth_key], line=dict(color=NOGO, dash="dot", width=1), row=1, col=1)
    _band(fig, 2, x, bands.get("hs"), WAVE, "CMEMS Hs", "m")
    fig.add_hline(y=lim["hs"], line=dict(color=NOGO, dash="dot", width=1), row=2, col=1)
    _band(fig, 3, x, bands.get("wind"), WIND, "CMEMS wind", "kn")
    fig.add_hline(y=lim["wind"], line=dict(color=NOGO, dash="dot", width=1), row=3, col=1)

    if era5_bands is not None:
        xe = np.arange(len(era5_bands["hs"]["p50"])) / 24.0
        _era5_over(fig, 2, xe, era5_bands.get("hs"), "m", "ERA5 Hs", band_legend=True)
        _era5_over(fig, 3, xe, era5_bands.get("wind"), "kn", "ERA5 wind", band_legend=False)

    fig.update_xaxes(title_text="days into execution window", row=3, col=1)
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


def _progress_one(d, L_days):
    fig = go.Figure()
    if d.progress_days:
        fig.add_trace(go.Scatter(x=d.progress_days, y=d.progress_pct,
            line=dict(color=DEPTH_COL[d.cur_key], width=1.8), name=d.label))
    fig.add_hline(y=100, line=dict(color=MUTED, dash="dot", width=1))
    fig.add_vline(x=L_days, line=dict(color=NOGO, dash="dash", width=1),
                  annotation_text="client window", annotation_position="top")
    fig.update_layout(height=220, margin=dict(l=48, r=14, t=14, b=36),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#ffffff",
        font=dict(color=MUTED, size=10, family="IBM Plex Mono"), showlegend=False,
        xaxis_title="elapsed days", yaxis_title="work complete (%)")
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, range=[0, 105])
    return fig


def _explanation(mode, hs, wind, cur_limits, dur, nom, start, end, cfg):
    op = (f"a single weather-sensitive task needing {dur:g} h of continuous good weather"
          if mode == "single" else
          f"a campaign with {nom:g} days of nominal (good-weather) working time")
    return html.Div([
        html.Div("How to read this sheet", style={"font": "600 12px system-ui",
            "textTransform": "uppercase", "letterSpacing": ".04em", "color": MUTED, "marginBottom": "6px"}),
        html.P(["This assessment uses ", html.B("Copernicus Marine reanalysis"),
                " — a modelled hindcast of past sea state, wind and currents (not a weather "
                "forecast). Because the execution period is too far ahead to forecast, workability "
                "is derived from the statistics of past years for the same calendar months."],
               style={"margin": "0 0 5px"}),
        html.P([html.B("Operation & limits: "), f"{op}. A given hour is workable when significant "
                f"wave height ≤ {hs:g} m, wind ≤ {wind:g} kn, and the current at that depth is within "
                f"its limit (surface {cur_limits['cur_surf']:g} / mid {cur_limits['cur_mid']:g} / "
                f"bottom {cur_limits['cur_bottom']:g} kn)."], style={"margin": "0 0 5px"}),
        html.P([html.B("Climatology: "), f"built from the last {cfg.lookback_years} years of reanalysis, "
                f"filtered to the execution months, with {cfg.recency} recency weighting so recent "
                "years count for more (guarding against a shifting climate)."], style={"margin": "0 0 5px"}),
        html.P([html.B("P50 / P80 / P90: "), "percentiles across those historical years. P50 is the "
                "median (expected) outcome, P80 the recommended planning/budget figure (only 1 year in 5 "
                "is worse), P90 a conservative cover. Price the spread against P80."],
               style={"margin": "0 0 6px"}),
        html.P([html.B("ERA5 cross-check: "), "where shown, the dashed lines on the Hs and wind panels "
                "are ERA5 (ECMWF) — a fully independent reanalysis from a different provider. It is a "
                "second opinion on wave and wind only (ERA5 has no currents); close agreement with "
                "CMEMS corroborates the workability basis. Note both assimilate satellite data, so "
                "agreement is a consistency check rather than fully independent validation."],
               style={"margin": "0"}),
    ], style={"font": "11.5px system-ui", "color": MUTED, "lineHeight": "1.5",
              "background": SOFT, "border": f"1px solid {GRID}", "borderRadius": "8px",
              "padding": "11px 13px", "marginBottom": "14px"})


def _summary_line(lat, lon, start, end, mode, res):
    reg = classify_region(lat, lon)
    op = (f"single task · {res.duration_h} h window" if mode == "single"
          else f"campaign · {res.nominal_hours/24:.0f} d nominal")
    return html.Div([html.B(reg.label), f"  ·  {lat:.3f}, {lon:.3f}  ·  ",
        f"{pd.Timestamp(start):%d %b %Y} → {pd.Timestamp(end):%d %b %Y}  ·  {op}"],
        style={"font": "11.5px 'IBM Plex Mono'", "color": INK, "marginBottom": "10px"})


def _banner(source, meta):
    meta = meta or {}
    if source == "demo":
        err = meta.get("error", "")
        msg = ("Showing DEMO data — configure CMEMS credentials for live reanalysis."
               if not err else f"Live fetch failed, showing DEMO data. Reason: {err}")
        return html.Div(msg, style={"font": "12px 'IBM Plex Mono'", "color": MARG,
            "background": MARG_BG, "border": f"1px solid {MARG}", "borderRadius": "8px",
            "padding": "8px 10px", "marginBottom": "12px"})
    note = meta.get("current_note", "")
    if source == "live" and meta.get("current_source") == "GLOBAL":
        txt = "Live reanalysis. Currents from global GLORYS (regional IBI unavailable here) — daily-mean. " + note
    else:
        txt = "Live reanalysis. " + note
    return html.Div(txt, style={"font": "12px 'IBM Plex Mono'", "color": MUTED, "background": SOFT,
        "border": f"1px solid {GRID}", "borderRadius": "8px", "padding": "8px 10px", "marginBottom": "12px"})


def _clim_panel(clim):
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
    return html.Div([
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


def _depth_figures(d, res, pctile, start, end, ui):
    """Strip + (campaign) progress for one depth — used both on screen and per print page."""
    L_days = (end - start).days or 1
    lim = dict(hs=ui["hs"], wind=ui["wind"], **ui["cur_limits"])
    kids = [html.Div([html.Div(f"Metocean strip · {DEPTH_LABEL[d.cur_key]} · climatological band "
                               f"(P50 line, P10–P90 shaded) over {ui['cfg'].lookback_years} yr", style=_H),
                      dcc.Graph(figure=_strip(ui["bands"], (end - start).days * 24 or 24, lim, d.cur_key,
                                              era5_bands=ui.get("era5_bands")),
                                config={"displayModeBar": False}),
                      (html.Div([
                          html.B("Reading this: "),
                          "the solid coloured line is the CMEMS median (P50) for each hour of the "
                          "window; the shaded band is the P10–P90 spread across the look-back years "
                          "(band top = rough 1-in-10 year, bottom = calm 1-in-10 year). The red "
                          "dotted line is your workability limit — where the band crosses it, that "
                          "fraction of years breaches the limit, which is why P80/P90 in the cards "
                          "sit above P50. Dashed dark lines (Hs & wind) are ERA5, an independent "
                          "reanalysis shown as a cross-check; where ERA5 sits on the CMEMS line the "
                          "two sources agree. Currents are CMEMS only (ERA5 has none)."],
                                style={"font": "11px system-ui", "color": DIM, "marginTop": "4px",
                                       "lineHeight": "1.5"})
                       if ui.get("era5_bands") is not None else
                       html.Div([html.B("Reading this: "),
                          "the solid line is the CMEMS median (P50); the shaded band is the P10–P90 "
                          "spread across the look-back years (top = rough 1-in-10 year, bottom = calm "
                          "1-in-10 year). The red dotted line is your workability limit — where the "
                          "band crosses it, that fraction of years breaches it, which is why P80/P90 "
                          "in the cards sit above P50."],
                                style={"font": "11px system-ui", "color": DIM, "marginTop": "4px",
                                       "lineHeight": "1.5"}))],
                     style=_CARD)]
    if res.mode == "campaign":
        kids.append(html.Div([
            html.Div(f"Cumulative progress · {DEPTH_LABEL[d.cur_key]} · nominal work vs elapsed", style=_H),
            dcc.Graph(figure=_progress_one(d, L_days), config={"displayModeBar": False}),
            html.Div("Work-complete (%) against elapsed days; the gap to the client-window line is the "
                     "weather delay. A flat stretch is unworkable weather.",
                     style={"font": "11px system-ui", "color": DIM, "marginTop": "4px"}),
        ], style=_CARD))
    return kids


def _render(res, clim, source, pctile, start, end, meta=None, ui=None):
    ui = ui or {}
    L_days = (end - start).days or 1
    banner = _banner(source, meta)
    era5_note = ui.get("era5_note")
    era5_banner = None
    if era5_note:
        ok = "overlay" in era5_note
        era5_banner = html.Div(era5_note, style={"font": "12px 'IBM Plex Mono'",
            "color": (MUTED if ok else MARG), "background": (SOFT if ok else MARG_BG),
            "border": f"1px solid {GRID if ok else MARG}", "borderRadius": "8px",
            "padding": "8px 10px", "marginBottom": "12px"})

    if res.mode == "single":
        title = f"Single task · {res.duration_h} h continuous window · {res.n_years} historical years"
        card_fn = lambda d: _depth_card_single(d)
    else:
        title = (f"Campaign · {res.nominal_hours/24:.0f} d nominal work · client window {L_days} d · "
                 f"P{pctile} · {res.n_years} historical years")
        card_fn = lambda d: _depth_card_campaign(d, pctile, L_days)

    overview = html.Div([html.Div(title, style=_H),
        html.Div([card_fn(d) for d in res.depths],
                 style={"display": "grid", "gridTemplateColumns": "repeat(3,1fr)", "gap": "10px"})],
        style=_CARD)

    toggle = html.Div([
        html.Span("Show depth: ", style={"font": "600 12px system-ui", "color": MUTED, "marginRight": "8px"}),
        dcc.RadioItems(id="ws-depth",
            options=[{"label": f" {d.label}", "value": d.cur_key} for d in res.depths],
            value=res.depths[0].cur_key, inline=True,
            inputStyle={"marginRight": "5px"}, labelStyle={"marginRight": "16px"},
            style={"display": "inline-block", "font": "13px system-ui"}),
    ], className="no-print", style={"marginBottom": "10px"})

    # on-screen per-depth panels (only selected shown; toggled clientside)
    screen_panels = []
    for i, d in enumerate(res.depths):
        screen_panels.append(html.Div(_depth_figures(d, res, pctile, start, end, ui),
            id=f"ws-screen-{d.cur_key}",
            style={"display": "block" if i == 0 else "none"}))

    # print sheets: one page per depth, each self-contained with the explanation
    sheets = []
    for d in res.depths:
        sheets.append(html.Div([
            _explanation(res.mode, ui.get("hs"), ui.get("wind"), ui.get("cur_limits"),
                         ui.get("dur"), ui.get("nom"), start, end, ui.get("cfg")),
            _summary_line(ui.get("lat"), ui.get("lon"), start, end, res.mode, res),
            html.Div(f"{DEPTH_LABEL[d.cur_key]} depth", style={"font": "600 14px system-ui",
                     "color": INK, "margin": "0 0 8px"}),
            html.Div([card_fn(d)], style={"maxWidth": "320px", "marginBottom": "12px"}),
            *_depth_figures(d, res, pctile, start, end, ui),
            _clim_panel(clim),
        ], className="ws-sheet"))
    print_block = html.Div(sheets, className="ws-printonly")

    footer_note = html.Div("Currents from daily-mean reanalysis don't resolve the tidal cycle at "
        "tide-dominated sites; confirm slack against tide tables. Bottom is the deepest wet model level "
        "(the seabed at this cell); mid-water is half that depth.",
        style={"font": "11px system-ui", "color": DIM, "lineHeight": "1.5", "marginTop": "8px"})

    return html.Div([
        banner, era5_banner,
        html.Div(_explanation(res.mode, ui.get("hs"), ui.get("wind"), ui.get("cur_limits"),
                              ui.get("dur"), ui.get("nom"), start, end, ui.get("cfg")),
                 className="no-print"),
        html.Div([overview, toggle, *screen_panels, _clim_panel(clim), footer_note],
                 className="no-print"),
        print_block,
    ])
