"""
Dive-profile chart builder (Plotly), reusable for the USN and DCD schedule pages.

A profile is an ordered list of "legs":
    {"kind":"move", "to":<depth>, "rate_fpm":R, "gas":G, "style":S, "phase":P}
    {"kind":"hold", "depth":<depth>, "min":M, "gas":G, "phase":P}

Depths are given in the table's native unit ("fsw" or "m"); the builder converts
to the requested display unit and derives the time axis from the ascent/descent
rates. Each segment is coloured by breathing gas and (for moves) styled by rate;
the in-water and surface/chamber parts get different background shading, and the
legend lists both the gas colours and the line styles in use.

Gas colours:  air = blue, O2 = green, heliox = red, nitrox = yellow,
              surface (out of water) = grey (continuous).
Line styles:  30 ft/min ascent = solid, 40 ft/min = dashed,
              100 ft/min chamber blow-down = dotted.
"""
import plotly.graph_objects as go

M_PER_FT = 0.3048

GAS_COLOR = {"air": "#2563eb", "o2": "#16a34a", "heliox": "#dc2626",
             "nitrox": "#eab308", "surface": "#9ca3af"}
GAS_LABEL = {"air": "Air", "o2": "Oxygen", "heliox": "Heliox",
             "nitrox": "Nitrox", "surface": "Surface"}
GAS_ORDER = ["air", "o2", "heliox", "nitrox", "surface"]

# move style -> (plotly dash, legend label). "hold"/"descent" are solid and not
# listed in the line-style legend (holds are stops; descents read by direction).
STYLE_DASH = {"ascent": "solid", "surfacing": "dash", "chamber": "dot",
              "descent": "solid", "hold": "solid"}
STYLE_LABEL = {"ascent": "30 ft/min ascent", "surfacing": "40 ft/min",
               "chamber": "100 ft/min (chamber)"}
STYLE_ORDER = ["ascent", "surfacing", "chamber"]

BG_WATER = "#eff6ff"     # light blue
BG_SURFACE = "#f3f4f6"   # light grey


def _to_ft(d, native):
    return float(d) if native == "fsw" else float(d) / M_PER_FT


def _disp(d_ft, disp):
    return round(d_ft if disp == "ft" else d_ft * M_PER_FT, 1)


def build_figure(legs, native_unit="fsw", display_unit="ft", title=None):
    fig = go.Figure()
    t = 0.0
    depth_ft = 0.0
    gases = set()
    styles = set()
    surface_start = None

    def seg(t0, d0_ft, t1, d1_ft, gas, style):
        fig.add_trace(go.Scatter(
            x=[round(t0, 2), round(t1, 2)],
            y=[_disp(d0_ft, display_unit), _disp(d1_ft, display_unit)],
            mode="lines",
            line=dict(color=GAS_COLOR.get(gas, "#374151"), width=3,
                      dash=STYLE_DASH.get(style, "solid")),
            showlegend=False, hoverinfo="skip"))
        gases.add(gas)
        if style in STYLE_LABEL:
            styles.add(style)

    for leg in legs:
        phase = leg.get("phase", "water")
        if surface_start is None and phase != "water":
            surface_start = t
        if leg["kind"] == "move":
            to_ft = _to_ft(leg["to"], native_unit)
            rate = leg.get("rate_fpm") or 30
            dt = abs(to_ft - depth_ft) / rate
            seg(t, depth_ft, t + dt, to_ft, leg["gas"], leg.get("style", "ascent"))
            t += dt
            depth_ft = to_ft
        else:  # hold
            d_ft = _to_ft(leg["depth"], native_unit)
            depth_ft = d_ft
            m = leg.get("min") or 0
            seg(t, d_ft, t + m, d_ft, leg["gas"], "hold")
            t += m
    total = t or 1.0

    if surface_start is None:
        surface_start = total
    fig.add_vrect(x0=0, x1=surface_start, fillcolor=BG_WATER, opacity=0.7,
                  line_width=0, layer="below")
    if surface_start < total:
        fig.add_vrect(x0=surface_start, x1=total, fillcolor=BG_SURFACE, opacity=0.8,
                      line_width=0, layer="below")

    for g in GAS_ORDER:
        if g in gases:
            fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines",
                          line=dict(color=GAS_COLOR[g], width=3),
                          name=GAS_LABEL[g], legendgroup="gas"))
    for s in STYLE_ORDER:
        if s in styles:
            fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines",
                          line=dict(color="#6b7280", width=2, dash=STYLE_DASH[s]),
                          name=STYLE_LABEL[s], legendgroup="style"))

    ulabel = "ft" if display_unit == "ft" else "m"
    fig.update_layout(
        title=dict(text=title, font=dict(size=13), x=0) if title else None,
        xaxis=dict(title="Time (min)", showgrid=True, gridcolor="#e5e7eb",
                   zeroline=False, rangemode="tozero"),
        yaxis=dict(title=f"Depth ({ulabel})", autorange="reversed",
                   showgrid=True, gridcolor="#e5e7eb", zeroline=False,
                   rangemode="tozero"),
        margin=dict(l=60, r=20, t=40 if title else 16, b=44),
        height=380, plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    font=dict(size=11)),
        hovermode=False,
    )
    return fig
