"""
Home page — the smoke test.

If you can see this in your browser at http://<your-ip>:<port>, the whole chain works:
GitHub -> Dokploy build -> container -> reachable. Everything after this is just
adding real tools (envelope, twin-bell, seafastening, RAO) as more pages.
"""
import dash
from dash import html

dash.register_page(__name__, path="/", name="Home")

layout = html.Div(
    [
        html.H3("It works ✅", style={"fontFamily": "system-ui, sans-serif"}),
        html.P(
            "The Picasso portal foundation is deployed and reachable. "
            "Next step: port the 140T main hoist envelope tool in as the first real page.",
            style={"fontFamily": "system-ui, sans-serif", "color": "#374151",
                   "maxWidth": "640px", "lineHeight": "1.5"},
        ),
    ]
)
