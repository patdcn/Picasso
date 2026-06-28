"""
Reference — General arrangements.

Shows GA drawings stored on the data volume at /data/tools/ga/. Each GA is a pair
of files sharing a key: <key>.pdf (download) and <key>.png (preview). A small
manifest (ga/manifest.json) gives titles and order; if absent, files are listed
by key. Files are served through a Flask route registered in app.main.
"""
import os
import json
import dash
from dash import html

dash.register_page(__name__, path="/reference/ga", name="General arrangements",
                   category="Reference", order=1)

GA_DIR = os.getenv("GA_DATA_DIR", "/data/tools/ga")
MUTED = "#64748b"
GRID = "#e2e8f0"


def _gas():
    """Return [{key, title, png, pdf}] for GAs present on the volume."""
    if not os.path.isdir(GA_DIR):
        return []
    manifest = {}
    mpath = os.path.join(GA_DIR, "manifest.json")
    if os.path.exists(mpath):
        try:
            manifest = {g["key"]: g for g in json.load(open(mpath))}
        except Exception:
            manifest = {}
    out = []
    seen = set()
    # manifest order first, then any extra files
    keys = list(manifest.keys()) + [
        f[:-4] for f in sorted(os.listdir(GA_DIR))
        if f.endswith(".pdf") and f[:-4] not in manifest
    ]
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        pdf = os.path.join(GA_DIR, f"{key}.pdf")
        png = os.path.join(GA_DIR, f"{key}.png")
        if not os.path.exists(pdf):
            continue
        out.append({
            "key": key,
            "title": manifest.get(key, {}).get("title", key.replace("_", " ").title()),
            "has_png": os.path.exists(png),
        })
    return out


def _card(ga):
    children = [html.H4(ga["title"], style={"margin": "0 0 8px"})]
    if ga["has_png"]:
        children.append(html.Img(
            src=f"/ga-file/{ga['key']}.png",
            style={"width": "100%", "border": f"1px solid {GRID}", "borderRadius": "8px"}))
    else:
        children.append(html.Div("Preview not available.",
                                 style={"color": MUTED, "fontSize": "0.85rem"}))
    children.append(html.A("Download PDF", href=f"/ga-file/{ga['key']}.pdf", target="_blank",
                           style={"display": "inline-block", "marginTop": "10px",
                                  "color": "#0f766e", "fontWeight": 600,
                                  "textDecoration": "none"}))
    return html.Div(children, style={"background": "#fff", "border": f"1px solid {GRID}",
                                     "borderRadius": "12px", "padding": "16px",
                                     "marginBottom": "20px", "maxWidth": "900px"})


def layout():
    gas = _gas()
    if not gas:
        return html.Div([
            html.H3("General arrangements"),
            html.P("No GA drawings have been uploaded yet. Add <key>.pdf and "
                   "<key>.png pairs to the data volume under /data/tools/ga/ to "
                   "show them here.", style={"color": MUTED, "maxWidth": "640px"}),
        ])
    return html.Div([
        html.H3("General arrangements"),
        html.P("Reference drawings for the DSV Picasso and its equipment.",
               style={"color": MUTED}),
        *[_card(g) for g in gas],
    ], style={"maxWidth": "940px"})
