"""
Shared operational-limits footnote for the lifting pages.

Single source of truth for the crane's operational limits disclaimer, shown at
the foot of the Main Lift, Aux Lift, Load Planner, Load-Radius and Engineered
Subsea pages. Edit the values here once and every page updates.
"""
from dash import html

_MUTED = "#64748b"
_GRID = "#e2e8f0"
_INK = "#334155"

# (label, value) — the crane's operational limits from the GA / manual.
_LIMITS = [
    ("Max wind velocity", "25 m/s"),
    ("Max trim", "2\u00b0"),
    ("Max heel", "5\u00b0"),
    ("Ice & snow", "Not permitted"),
]


def limits_footnote():
    """Operational-limits disclaimer rendered at the bottom of a lifting page."""
    items = []
    for i, (label, val) in enumerate(_LIMITS):
        items.append(html.Span([
            html.Span(label + ": ", style={"color": _MUTED}),
            html.Span(val, style={"color": _INK, "fontWeight": 600}),
        ]))
        if i < len(_LIMITS) - 1:
            items.append(html.Span("\u2002\u00b7\u2002", style={"color": "#cbd5e1"}))
    return html.Div([
        html.Div("Operational limits", style={
            "fontWeight": 700, "fontSize": "0.74rem", "color": _MUTED,
            "textTransform": "uppercase", "letterSpacing": "0.05em",
            "marginBottom": "4px"}),
        html.Div(items, style={"fontSize": "0.82rem", "lineHeight": "1.5"}),
        html.Div("Load charts are valid only within these limits; the lift "
                 "engineer / operator remains responsible for each lift.",
                 style={"fontSize": "0.74rem", "color": _MUTED, "marginTop": "5px"}),
    ], style={"marginTop": "28px", "paddingTop": "12px",
              "borderTop": f"1px solid {_GRID}"})
