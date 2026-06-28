"""Shared placeholder used by tools that aren't built yet, so the nav is fully
navigable and every group shows. Replace a page's layout with the real tool when ready."""
from dash import html


def placeholder(title: str, blurb: str = ""):
    return html.Div(
        [
            html.H3(title),
            html.P(blurb or "This tool isn't built yet — placeholder page.",
                   style={"color": "#6b7280", "maxWidth": "640px", "lineHeight": "1.5"}),
            html.Div("Coming soon", style={
                "display": "inline-block", "marginTop": "8px", "padding": "4px 10px",
                "borderRadius": "999px", "background": "#f3f4f6", "color": "#6b7280",
                "fontSize": "0.8rem"}),
        ]
    )
