"""
Weather Stats — Copernicus.

Metocean workability for a tender. Pick a work location and the client's fixed
execution window; the tool pulls Copernicus Marine reanalysis (WAVERYS waves,
L4 wind, GLORYS/IBI currents at surface + working depth), builds recency-weighted
seasonal statistics with a trend diagnostic, and returns single-window or
sequenced-campaign workability tested against the window.

Live data requires Copernicus Marine credentials in the environment
(CMEMS_USERNAME / CMEMS_PASSWORD, set in Dokploy). Without them the page runs on
synthetic demo data behind an amber banner. The numeric reanalysis is cached to
the /data volume; the first assessment per location is slow, the rest instant.
"""
import dash
from dash import html, dcc, dash_table, Input, Output, State, callback, no_update
import dash_leaflet as dl
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

from app.engines import metocean as mo
from app.engines.metocean import (
    build_climatology, ClimatologyConfig, assess, TaskType,
    classify_region, current_dataset_for, get_series, credentials_present,
    historical_windows,
)

dash.register_page(__name__, path="/weather/copernicus", name="Copernicus",
                   category="Weather Stats", order=1)

# ---- portal light theme ----
INK = "#0f172a"; MUTED = "#64748b"; DIM = "#94a3b8"; GRID = "#e2e8f0"
ACCENT = "#0f766e"; PANEL = "#ffffff"; SOFT = "#f8fafc"
GO = "#16a34a"; MARG = "#d97706"; NOGO = "#dc2626"
GO_BG = "#dcfce7"; MARG_BG = "#fef9c3"; NOGO_BG = "#fee2e2"
CUR_S = "#0891b2"; CUR_B = "#7c3aed"; WAVE = "#2563eb"; WIND = "#ca8a04"

DEFAULT_LAT, DEFAULT_LON = 53.02, 3.24

_CARD = {"background": PANEL, "border": f"1px solid {GRID}", "borderRadius": "10px",
         "padding": "14px 16px", "marginBottom": "14px"}
_H = {"font": "600 13px system-ui", "textTransform": "uppercase", "letterSpacing": ".05em",
      "color": MUTED, "margin": "0 0 10px"}

TASK_COLUMNS = [
    {"name": "Task", "id": "name", "type": "text"},
    {"name": "h", "id": "duration_h", "type": "numeric"},
    {"name": "off", "id": "off", "type": "numeric"},
    {"name": "Hs", "id": "hs_max", "type": "numeric"},
    {"name": "Wind", "id": "wind_max", "type": "numeric"},
    {"name": "Surf", "id": "cur_surf_max", "type": "numeric"},
    {"name": "Bot", "id": "cur_bottom_max", "type": "numeric"},
    {"name": "Reset", "id": "resetup_h", "type": "numeric"},
]
DEFAULT_TASK_ROWS = [
    dict(name="As-found survey", duration_h=2, off=4, hs_max=2.0, wind_max=25, cur_surf_max=1.2, cur_bottom_max=0.9, resetup_h=0.1),
    dict(name="Dredge / expose", duration_h=1, off=20, hs_max=1.5, wind_max=20, cur_surf_max=1.0, cur_bottom_max=0.8, resetup_h=0.1),
    dict(name="Cut / flange", duration_h=1, off=10, hs_max=1.2, wind_max=18, cur_surf_max=0.6, cur_bottom_max=0.5, resetup_h=0.5),
    dict(name="Rig & recover", duration_h=2, off=5, hs_max=1.5, wind_max=20, cur_surf_max=0.8, cur_bottom_max=0.7, resetup_h=2.0),
    dict(name="Backfill", duration_h=1, off=8, hs_max=1.8, wind_max=22, cur_surf_max=1.1, cur_bottom_max=0.9, resetup_h=0.1),
]


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
        html.H3("Weather Stats — Copernicus", style={"marginBottom": "2px"}),
        html.P("Metocean workability for a work location and the client's execution window, "
               "from Copernicus Marine reanalysis.",
               style={"color": MUTED, "marginTop": "0", "maxWidth": "720px"}),
        html.Div(id="ws-src-banner", style={"marginBottom": "12px"}),

        html.Div(style={"display": "grid", "gridTemplateColumns": "360px 1fr", "gap": "16px",
                        "alignItems": "start"}, children=[

            # ---------- controls ----------
            html.Div([
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
                    html.Div([
                        html.Div([_lbl("Working depth (m)"), _num("ws-depth", 34, 1)]),
                        html.Div([_lbl("Budget percentile"), dcc.Dropdown(id="ws-pctile",
                            options=[{"label": "P50 (median)", "value": 50},
                                     {"label": "P80 (recommended)", "value": 80},
                                     {"label": "P90 (conservative)", "value": 90}],
                            value=80, clearable=False)]),
                    ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "10px", "marginTop": "10px"}),
                ], style=_CARD),

                html.Div([
                    html.Div("Climatology", style=_H),
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
                    html.Div("Scope", style=_H),
                    dcc.RadioItems(id="ws-mode",
                        options=[{"label": " Single window", "value": "single"},
                                 {"label": " Campaign", "value": "campaign"}],
                        value="campaign", inline=True,
                        inputStyle={"marginRight": "5px"}, labelStyle={"marginRight": "16px"},
                        style={"marginBottom": "10px", "font": "13px system-ui"}),

                    html.Div(id="ws-single-pane", children=[
                        html.Div([
                            html.Div([_lbl("Task length (h)"), _num("ws-s-dur", 6, 0.5)]),
                            html.Div([_lbl("Max Hs (m)"), _num("ws-s-hs", 1.5, 0.1)]),
                        ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "10px"}),
                        html.Div([
                            html.Div([_lbl("Max wind (kn)"), _num("ws-s-wind", 20, 1)]),
                            html.Div([_lbl("Surf cur (kn)"), _num("ws-s-sc", 0.8, 0.1)]),
                        ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "10px", "marginTop": "10px"}),
                        html.Div([_lbl("Bottom cur — diver (kn)"), _num("ws-s-bc", 0.6, 0.1)],
                                 style={"marginTop": "10px"}),
                    ]),

                    html.Div(id="ws-campaign-pane", children=[
                        html.Div("Each row is a task type: h/unit × off, run top-to-bottom. "
                                 "Reset = hours added if a unit is interrupted.",
                                 style={"font": "11px system-ui", "color": DIM, "marginBottom": "8px"}),
                        dash_table.DataTable(id="ws-tasks", columns=TASK_COLUMNS, data=DEFAULT_TASK_ROWS,
                            editable=True, row_deletable=True, style_table={"overflowX": "auto"},
                            style_cell={"border": f"1px solid {GRID}", "font": "11px 'IBM Plex Mono'",
                                        "padding": "4px", "textAlign": "center", "color": INK},
                            style_header={"background": SOFT, "color": MUTED, "border": f"1px solid {GRID}",
                                          "font": "600 10px system-ui", "textTransform": "uppercase"},
                            style_cell_conditional=[{"if": {"column_id": "name"}, "textAlign": "left", "minWidth": "92px"}]),
                        html.Button("+ Add task type", id="ws-addrow", n_clicks=0,
                            style={"width": "100%", "marginTop": "8px", "background": SOFT,
                                   "border": f"1px dashed {GRID}", "color": MUTED, "padding": "7px",
                                   "borderRadius": "6px", "cursor": "pointer", "font": "600 11px system-ui"}),
                    ]),

                    html.Button("Assess workability", id="ws-run", n_clicks=0,
                        style={"width": "100%", "marginTop": "14px", "background": ACCENT, "color": "#fff",
                               "border": "0", "padding": "11px", "borderRadius": "8px", "cursor": "pointer",
                               "font": "600 14px system-ui"}),
                ], style=_CARD),
            ]),

            # ---------- results ----------
            dcc.Loading(type="default", color=ACCENT, children=html.Div(id="ws-results", children=[
                html.Div("Set location, window and scope, then run.",
                         style={"padding": "56px 20px", "textAlign": "center", "color": DIM,
                                "border": f"1px dashed {GRID}", "borderRadius": "10px",
                                "font": "15px system-ui"})])),
        ]),
    ])


# ============================ callbacks ============================
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


@callback(Output("ws-tasks", "data"), Input("ws-addrow", "n_clicks"),
          State("ws-tasks", "data"), prevent_initial_call=True)
def _addrow(_, rows):
    rows = rows or []
    rows.append(dict(name="Task", duration_h=1, off=1, hs_max=1.5, wind_max=20,
                     cur_surf_max=0.8, cur_bottom_max=0.6, resetup_h=0.1))
    return rows


@callback(Output("ws-results", "children"),
          Input("ws-run", "n_clicks"),
          State("ws-lat", "value"), State("ws-lon", "value"),
          State("ws-dates", "start_date"), State("ws-dates", "end_date"),
          State("ws-depth", "value"), State("ws-pctile", "value"),
          State("ws-lookback", "value"), State("ws-halflife", "value"),
          State("ws-recency", "value"), State("ws-mode", "value"),
          State("ws-s-dur", "value"), State("ws-s-hs", "value"),
          State("ws-s-wind", "value"), State("ws-s-sc", "value"), State("ws-s-bc", "value"),
          State("ws-tasks", "data"), prevent_initial_call=True)
def _run(_, lat, lon, sd, ed, depth, pctile, lookback, halflife, recency, mode,
         s_dur, s_hs, s_wind, s_sc, s_bc, task_rows):
    try:
        lat, lon = float(lat), float(lon)
        start, end = pd.Timestamp(sd), pd.Timestamp(ed)
        depth = float(depth or 34)
        cfg = ClimatologyConfig(lookback_years=int(lookback or 30),
                                recency=recency or "exponential",
                                half_life_years=float(halflife or 10), trend_stat="p95")
    except Exception as e:
        return _error(f"Check inputs: {e}")

    try:
        df, source, meta = get_series(lat, lon, depth)
    except Exception as e:
        return _error(f"Data unavailable: {e}")

    clim = build_climatology(df, lat, lon, start, end, cfg)

    if mode == "single":
        task = TaskType("Operation", int(round(float(s_dur or 6))), 1,
                        float(s_hs or 1.5), float(s_wind or 20),
                        float(s_sc or 0.8), float(s_bc or 0.6))
        res = assess(df, start, end, tasks=[task], mode="single", cfg=cfg, n_runs=500)
    else:
        tasks = _parse_tasks(task_rows)
        if not tasks:
            return _error("Add at least one task row.")
        res = assess(df, start, end, tasks=tasks, mode="campaign", cfg=cfg, n_runs=500)

    strip = _strip(df, start, end, cfg, _strip_limits(mode, s_hs, s_wind, s_sc, s_bc, task_rows))
    return _render(res, clim, source, int(pctile or 80), start, end, strip, mode, meta)


# ---------- helpers ----------
def _parse_tasks(rows):
    out = []
    for r in rows or []:
        try:
            out.append(TaskType(str(r.get("name") or "Task"),
                int(round(float(r["duration_h"]))), int(round(float(r["off"]))),
                float(r["hs_max"]), float(r["wind_max"]),
                float(r["cur_surf_max"]), float(r["cur_bottom_max"]),
                float(r.get("resetup_h") or 0)))
        except (KeyError, TypeError, ValueError):
            continue
    return out

def _strip_limits(mode, s_hs, s_wind, s_sc, s_bc, rows):
    if mode == "single":
        return dict(hs=float(s_hs or 1.5), wind=float(s_wind or 20),
                    sc=float(s_sc or 0.8), bc=float(s_bc or 0.6))
    ts = _parse_tasks(rows)
    if not ts:
        return dict(hs=1.5, wind=20, sc=0.8, bc=0.6)
    return dict(hs=min(t.hs_max for t in ts), wind=min(t.wind_max for t in ts),
                sc=min(t.cur_surf_max for t in ts), bc=min(t.cur_bottom_max for t in ts))

def _error(msg):
    return html.Div(msg, style={"padding": "18px", "color": NOGO, "background": NOGO_BG,
        "border": f"1px solid {NOGO}", "borderRadius": "10px", "font": "13px 'IBM Plex Mono'"})

def _card(k, v, u="", color=INK):
    return html.Div([html.Div(k, style={"font": "600 10.5px system-ui", "textTransform": "uppercase",
        "letterSpacing": ".04em", "color": MUTED}),
        html.Div([str(v), html.Span(u, style={"fontSize": "12px", "color": DIM})],
            style={"font": "22px 'IBM Plex Mono'", "marginTop": "5px", "color": color})],
        style={"background": PANEL, "border": f"1px solid {GRID}", "padding": "12px 14px",
               "borderRadius": "10px"})

def _strip(df, start, end, cfg, lim):
    wins, L = historical_windows(df, start, end, cfg, overrun_buffer_days=0)
    if not wins:
        return go.Figure()
    arr = wins[-1][2]
    n = min(L, len(arr["hs"]))
    import numpy as np
    t = np.arange(n) / 24.0
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.07,
                        subplot_titles=("Current (kn)", "Wave Hs (m)", "Wind (kn)"))
    fig.add_trace(go.Scatter(x=t, y=arr["cur_surf"][:n], name="Surface", line=dict(color=CUR_S, width=1.3)), 1, 1)
    fig.add_trace(go.Scatter(x=t, y=arr["cur_bottom"][:n], name="Bottom", line=dict(color=CUR_B, width=1.3)), 1, 1)
    fig.add_hline(y=lim["sc"], line=dict(color=NOGO, dash="dot", width=1), row=1, col=1)
    fig.add_hline(y=lim["bc"], line=dict(color=CUR_B, dash="dot", width=1), row=1, col=1)
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

def _render(res, clim, source, pctile, start, end, strip, mode, meta=None):
    L_days = (end - start).days or 1
    meta = meta or {}
    banner = None
    if source == "demo":
        err = meta.get("error", "")
        msg = ("Showing DEMO data — configure CMEMS credentials for live reanalysis."
               if not err else
               f"Live fetch failed, showing DEMO data. Reason: {err}")
        banner = html.Div(msg,
            style={"font": "12px 'IBM Plex Mono'", "color": MARG, "background": MARG_BG,
                   "border": f"1px solid {MARG}", "borderRadius": "8px", "padding": "8px 10px",
                   "marginBottom": "12px"})
    elif meta.get("current_source") in ("", "none"):
        # live waves/wind but currents unavailable — say so rather than showing zeros silently
        note = meta.get("current_note", "")
        banner = html.Div("Live waves & wind. Currents unavailable for this point"
                          + (f" ({note})" if note else "") + " — current traces are blank.",
            style={"font": "12px 'IBM Plex Mono'", "color": MARG, "background": MARG_BG,
                   "border": f"1px solid {MARG}", "borderRadius": "8px", "padding": "8px 10px",
                   "marginBottom": "12px"})
    elif source == "live" and meta.get("current_source") == "GLOBAL":
        banner = html.Div("Live reanalysis. Currents from global GLORYS (regional IBI "
                          "unavailable here) — coarser, daily-mean, no tidal cycle.",
            style={"font": "12px 'IBM Plex Mono'", "color": MUTED, "background": SOFT,
                   "border": f"1px solid {GRID}", "borderRadius": "8px", "padding": "8px 10px",
                   "marginBottom": "12px"})

    if mode == "campaign":
        pick = {50: res.dur_p50, 80: res.dur_p80, 90: res.dur_p90}[pctile] / 24
        fits = pick <= L_days
        col, bg = (GO, GO_BG) if fits else (NOGO, NOGO_BG)
        head = html.Div([
            html.Div(f"Campaign duration · P{pctile}", style=_H),
            html.Div([f"{pick:.1f}", html.Span(" days elapsed", style={"fontSize": "20px", "color": MUTED})],
                style={"font": "700 42px system-ui", "color": col, "lineHeight": ".95", "margin": "2px 0 6px"}),
            html.Div([f"P50 {res.dur_p50/24:.1f} d · P80 {res.dur_p80/24:.1f} d · P90 {res.dur_p90/24:.1f} d",
                      html.Br(), f"Client window {L_days} d → ",
                      html.B("FITS" if fits else "OVERRUNS", style={"color": col})],
                style={"font": "13px system-ui", "color": MUTED}),
        ], style={**_CARD, "background": bg, "borderColor": col})
        cards = html.Div([
            _card("Productive work", f"{res.productive_hours/24:.1f}", " d"),
            _card("Weather waiting", f"{(pick - res.productive_hours/24):.1f}", " d", MARG),
            _card("Fits window", f"{res.fit_pct:.0f}", " %", GO if res.fit_pct >= 80 else MARG),
            _card("Bottleneck", res.bottleneck or "—"),
        ], style={"display": "grid", "gridTemplateColumns": "repeat(4,1fr)", "gap": "10px", "marginBottom": "14px"})
    else:
        col = GO if res.exists_pct >= 80 else (MARG if res.exists_pct >= 50 else NOGO)
        bg = GO_BG if res.exists_pct >= 80 else (MARG_BG if res.exists_pct >= 50 else NOGO_BG)
        head = html.Div([
            html.Div("Single window feasibility", style=_H),
            html.Div([f"{res.exists_pct:.0f}", html.Span(" % of years", style={"fontSize": "20px", "color": MUTED})],
                style={"font": "700 42px system-ui", "color": col, "lineHeight": ".95", "margin": "2px 0 6px"}),
            html.Div(f"had a workable {res.productive_hours} h window in the period. "
                     f"Wait to first window: P50 {res.wait_p50/24:.1f} d · P80 {res.wait_p80/24:.1f} d.",
                     style={"font": "13px system-ui", "color": MUTED}),
        ], style={**_CARD, "background": bg, "borderColor": col})
        cards = None

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
        banner, head, cards,
        html.Div([html.Div("Metocean strip · representative recent-year window", style=_H),
                  dcc.Graph(figure=strip, config={"displayModeBar": False})], style=_CARD),
        clim_panel,
        html.Div("Currents from daily-mean reanalysis do not resolve the tidal cycle at tide-dominated "
                 "sites; confirm slack against tide tables. Wave/wind statistics are recency-weighted over "
                 "the look-back window. Duration is a distribution across historical years — price against P80.",
                 style={"font": "11px system-ui", "color": DIM, "lineHeight": "1.5"}),
    ])
