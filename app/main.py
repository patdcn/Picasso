"""
DSV Picasso Engineering Portal — application entrypoint.

This is the real portal foundation, kept deliberately minimal for the first deploy.
Right now it registers one placeholder page so we can prove the full chain works:
    GitHub push -> Dokploy build -> container runs -> reachable on your IP.

Once this is green, engines/, pages/, core/ etc. get added into this same structure.
"""
import os
import dash
from dash import Dash, html

# `use_pages=True` is what makes this a multi-tool portal rather than a single app.
# Pages live in app/pages/ and self-register via dash.register_page(...).
app = Dash(__name__, use_pages=True, title="DSV Picasso Engineering Portal")

# Gunicorn targets this `server` object in production (see Dockerfile CMD).
server = app.server

# Shared shell: a header + a slot where the active page renders.
app.layout = html.Div(
    [
        html.Div(
            [
                html.H2(
                    "DSV Picasso Engineering Portal",
                    style={"margin": 0, "fontFamily": "system-ui, sans-serif"},
                ),
                html.Span(
                    "DCN Diving",
                    style={"color": "#6b7280", "fontFamily": "system-ui, sans-serif"},
                ),
            ],
            style={
                "padding": "14px 20px",
                "borderBottom": "1px solid #e5e7eb",
                "display": "flex",
                "alignItems": "baseline",
                "gap": "12px",
            },
        ),
        html.Div(dash.page_container, style={"padding": "24px"}),
    ]
)

if __name__ == "__main__":
    # Local dev only. Production runs via gunicorn (see Dockerfile).
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8050")), debug=True)
