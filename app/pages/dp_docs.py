"""
Reference — Picasso DP document library.

Lists the DP source documents stored on the private data volume at
/data/docs/dp/ (capability studies, FMEA material, trials, single-line).
Documents open in a new tab via the /dp-doc route. Files never enter the
public repository. Upload via Admin -> Data volume files into docs/dp, using
the expected filenames shown for the known documents so the DP portals'
citation hyperlinks pick them up automatically.
"""
import dash
from dash import html

from app import dpdocs

dash.register_page(__name__, path="/reference/picasso-dp", name="Picasso DP",
                   category="Reference", order=2)

MUTED = "#64748b"
GRID = "#e2e8f0"
INK = "#0f172a"
_CARD = {"background": "#fff", "border": f"1px solid {GRID}",
         "borderRadius": "10px", "padding": "14px 16px", "marginBottom": "14px"}


def layout():
    docs = dpdocs.list_docs()

    if docs:
        rows = [html.Div([
            html.A(d["title"], href=f'/dp-doc/{d["filename"]}', target="_blank",
                   style={"fontWeight": 600, "textDecoration": "underline"}),
            html.Div(d["filename"], style={"fontSize": "11px", "color": MUTED,
                                           "fontFamily": "ui-monospace,monospace"}),
        ], style={"padding": "8px 0", "borderBottom": f"1px solid {GRID}"})
            for d in docs]
        doc_block = html.Div(rows)
    else:
        doc_block = html.Div(
            "No documents on the volume yet (docs/dp).",
            style={"color": MUTED})

    children = [
        html.H2("Picasso DP — reference documents", style={"color": INK}),
        html.Div("Source documents behind the DP Station Keeping portals. "
                 "Stored on the private data volume (docs/dp) — not in the "
                 "public repository. Links open in a new tab.",
                 style={"color": MUTED, "fontSize": "13px", "marginBottom": "12px"}),
        html.Div(doc_block, style=_CARD),
    ]
    return html.Div(children, style={"maxWidth": "860px"})
