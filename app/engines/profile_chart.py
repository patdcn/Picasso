"""
Dive-profile chart builder (Plotly), reusable for the USN and DCD schedule pages.

A profile is an ordered list of "legs":
    {"kind":"move", "to":<depth>, "rate_fpm":R, "gas":G, "style":S, "phase":P}
    {"kind":"hold", "depth":<depth>, "min":M, "gas":G, "phase":P}

Depths are given in the table's native unit ("fsw" or "m"); the builder converts
to the requested display unit. The time axis is *compressed* (each leg is plotted
at duration**WARP so long bottom/stop times condense and short segments stretch),
so it is deliberately not to scale; tick labels still show real elapsed minutes.
Segments are coloured by breathing gas and (moves) styled by ascent rate; the
in-water and surface/chamber parts get different background shading; hovering a
segment shows its gas, depth and duration; the legend sits under the chart.

Gas colours:  air = blue, O2 = green, heliox = red, nitrox = yellow,
              surface (out of water) = grey (continuous).
Line styles:  30 ft/min ascent = solid, 40 ft/min = dashed,
              100 ft/min chamber blow-down = dotted.
"""
import math
import plotly.graph_objects as go

M_PER_FT = 0.3048
WARP = 0.6                       # <1 compresses long durations, stretches short ones

GAS_COLOR = {"air": "#2563eb", "o2": "#16a34a", "heliox": "#dc2626",
             "nitrox": "#eab308", "surface": "#9ca3af"}
GAS_LABEL = {"air": "Air", "o2": "Oxygen", "heliox": "Heliox",
             "nitrox": "Nitrox", "surface": "Surface"}
GAS_ORDER = ["air", "o2", "heliox", "nitrox", "surface"]

STYLE_DASH = {"ascent": "solid", "surfacing": "dash", "chamber": "dot",
              "descent": "solid", "hold": "solid"}
STYLE_LABEL = {"ascent": "30 ft/min ascent", "surfacing": "40 ft/min",
               "chamber": "100 ft/min (chamber)"}
STYLE_ORDER = ["ascent", "surfacing", "chamber"]

BG_WATER = "#dbeafe"     # light blue
BG_SURFACE = "#e5e7eb"   # light grey


def _to_ft(d, native):
    return float(d) if native == "fsw" else float(d) / M_PER_FT


def _disp(d_ft, disp):
    return round(d_ft if disp == "ft" else d_ft * M_PER_FT, 1)


def _warp(d):
    return max(float(d), 0.0) ** WARP


def _nice_ticks(total, n=6):
    if total <= 0:
        return [0]
    raw = total / n
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = 10 * mag
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            step = m * mag
            break
    ticks, v = [], 0.0
    while v <= total + 1e-9:
        ticks.append(round(v, 6))
        v += step
    return ticks


def build_figure(legs, native_unit="fsw", display_unit="ft", title=None, style_labels=None):
    fig = go.Figure()
    labels = dict(STYLE_LABEL)
    if style_labels:
        labels.update(style_labels)
    rt = wt = depth_ft = 0.0
    real_pts, warp_pts = [0.0], [0.0]
    gases, styles = set(), set()
    surf_wt = None
    ulabel = "ft" if display_unit == "ft" else "m"

    def seg(w0, d0, w1, d1, gas, style, hover):
        fig.add_trace(go.Scatter(
            x=[round(w0, 3), round(w1, 3)],
            y=[_disp(d0, display_unit), _disp(d1, display_unit)],
            mode="lines",
            line=dict(color=GAS_COLOR.get(gas, "#374151"), width=3,
                      dash=STYLE_DASH.get(style, "solid")),
            text=[hover, hover], hoverinfo="text", showlegend=False))
        gases.add(gas)
        if style in STYLE_LABEL:
            styles.add(style)

    for leg in legs:
        if surf_wt is None and leg.get("phase", "water") != "water":
            surf_wt = wt
        if leg["kind"] == "move":
            to_ft = _to_ft(leg["to"], native_unit)
            rate = leg.get("rate_fpm") or 30
            dur = abs(to_ft - depth_ft) / rate
            w = _warp(dur)
            gas, style = leg["gas"], leg.get("style", "ascent")
            direction = "descend" if to_ft > depth_ft else "ascend"
            hover = (f"{GAS_LABEL.get(gas, gas)} · {direction} {rate:g} ft/min<br>"
                     f"to {_disp(to_ft, display_unit):g} {ulabel} · t≈{rt + dur:.0f} min")
            seg(wt, depth_ft, wt + w, to_ft, gas, style, hover)
            wt += w
            rt += dur
            depth_ft = to_ft
        else:
            d_ft = _to_ft(leg["depth"], native_unit)
            depth_ft = d_ft
            m = leg.get("min") or 0
            gas = leg["gas"]
            where = "surface" if gas == "surface" else f"{_disp(d_ft, display_unit):g} {ulabel} stop"
            hover = f"{GAS_LABEL.get(gas, gas)} · {where}<br>{m:g} min · t≈{rt + m:.0f} min"
            w = _warp(m)
            seg(wt, d_ft, wt + w, d_ft, gas, "hold", hover)
            wt += w
            rt += m
        real_pts.append(rt)
        warp_pts.append(wt)

    total_w = wt or 1.0
    total_r = rt or 1.0
    if surf_wt is None:
        surf_wt = total_w

    fig.add_vrect(x0=0, x1=surf_wt, fillcolor=BG_WATER, opacity=0.55, line_width=0, layer="below")
    fig.add_annotation(x=surf_wt / 2, y=1.0, yref="paper", yanchor="bottom",
                       text="in water", showarrow=False, font=dict(size=11, color="#2563eb"))
    if surf_wt < total_w:
        fig.add_vrect(x0=surf_wt, x1=total_w, fillcolor=BG_SURFACE, opacity=0.7,
                      line_width=0, layer="below")
        fig.add_annotation(x=(surf_wt + total_w) / 2, y=1.0, yref="paper", yanchor="bottom",
                           text="surface / chamber", showarrow=False,
                           font=dict(size=11, color="#6b7280"))

    for g in GAS_ORDER:
        if g in gases:
            fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines",
                          line=dict(color=GAS_COLOR[g], width=3), name=GAS_LABEL[g],
                          legendgroup="gas", hoverinfo="skip"))
    for s in STYLE_ORDER:
        if s in styles:
            fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines",
                          line=dict(color="#6b7280", width=2, dash=STYLE_DASH[s]),
                          name=labels[s], legendgroup="style", hoverinfo="skip"))

    ticks = _nice_ticks(total_r)

    def interp(rv):
        for k in range(1, len(real_pts)):
            if rv <= real_pts[k] or k == len(real_pts) - 1:
                r0, r1 = real_pts[k - 1], real_pts[k]
                w0, w1 = warp_pts[k - 1], warp_pts[k]
                return w1 if r1 == r0 else w0 + (w1 - w0) * (rv - r0) / (r1 - r0)
        return warp_pts[-1]

    fig.update_layout(
        title=dict(text=title, font=dict(size=13), x=0) if title else None,
        xaxis=dict(title="Time (min · compressed)", showgrid=True, gridcolor="#e5e7eb",
                   zeroline=False, range=[0, total_w * 1.02],
                   tickvals=[interp(v) for v in ticks], ticktext=[f"{v:g}" for v in ticks]),
        yaxis=dict(title=f"Depth ({ulabel})", autorange="reversed", showgrid=True,
                   gridcolor="#e5e7eb", zeroline=False, rangemode="tozero"),
        margin=dict(l=60, r=20, t=44 if title else 30, b=88),
        height=410, plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", yanchor="top", y=-0.18, x=0, font=dict(size=11)),
        hovermode="closest",
    )
    return fig
