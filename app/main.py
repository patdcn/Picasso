"""
DSV Picasso Engineering Portal — application entrypoint.

Portal shell: persistent header + collapsible grouped sidebar + page content area.
Tools live in app/pages/ and self-register (Dash Pages). The sidebar is generated
from the page registry and grouped per app/nav.py.
"""
import os
import dash
from dash import Dash, html, dcc, Input, Output, State

app = Dash(__name__, use_pages=True, title="DSV Picasso Engineering Portal",
           suppress_callback_exceptions=True)
server = app.server  # gunicorn target

from app.nav import build_nav  # noqa: E402  (after app init; uses page registry at runtime)

# ---- Header (with sidebar toggle) ----
header = html.Header(
    [
        html.Button("\u2630", id="nav-toggle", className="nav-toggle", n_clicks=0,
                    title="Show/hide menu"),
        html.H2("DSV Picasso Engineering Portal", className="app-title"),
        html.Span("DCN Diving", className="app-subtitle"),
    ],
    className="app-header",
)

# ---- Shell: sidebar + content ----
app.layout = html.Div(
    [
        dcc.Location(id="url"),
        dcc.Store(id="nav-open", data=True),  # sidebar visible by default
        header,
        html.Div(
            [
                html.Nav(id="sidebar", className="sidebar"),
                html.Main(dash.page_container, className="content"),
            ],
            id="app-shell",
            className="app-shell",
        ),
    ]
)


# Build/refresh the sidebar on navigation (gives active-link highlighting for free).
@app.callback(Output("sidebar", "children"), Input("url", "pathname"))
def _render_nav(pathname):
    return build_nav(pathname)


# Toggle the sidebar open/closed. The class drives the CSS (incl. responsive behaviour).
@app.callback(
    Output("app-shell", "className"),
    Output("nav-open", "data"),
    Input("nav-toggle", "n_clicks"),
    State("nav-open", "data"),
    prevent_initial_call=True,
)
def _toggle_nav(_clicks, is_open):
    is_open = not is_open
    return ("app-shell" if is_open else "app-shell collapsed"), is_open


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8050")), debug=True)
