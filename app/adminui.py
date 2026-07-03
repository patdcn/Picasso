"""Small shared UI helpers for the admin pages (hub + sub-pages)."""
from dash import html, dcc

INK = "#1f2937"
MUTED = "#6b7280"
ACCENT = "#0f766e"


def card(children):
    return html.Div(children, style={
        "background": "#fff", "border": "1px solid #e5e7eb", "borderRadius": "12px",
        "padding": "18px", "marginBottom": "18px", "maxWidth": "640px"})


def input_field(id_, ph, type_="text"):
    return dcc.Input(id=id_, type=type_, placeholder=ph, style={
        "width": "100%", "padding": "8px 10px", "borderRadius": "8px",
        "border": "1px solid #d1d5db", "marginBottom": "8px", "boxSizing": "border-box"})


def btn(label, id_, primary=True):
    bg = ACCENT if primary else "#fff"
    fg = "#fff" if primary else "#b91c1c"
    border = "none" if primary else "1px solid #fecaca"
    return html.Button(label, id=id_, n_clicks=0, style={
        "padding": "9px 16px", "borderRadius": "8px", "border": border,
        "background": bg, "color": fg, "fontWeight": 600, "cursor": "pointer",
        "marginRight": "8px"})


def status(id_):
    return html.Div(id=id_, style={"fontSize": "0.85rem", "marginTop": "10px",
                                   "minHeight": "1.1em"})


def hub_card(title, description, href, cta):
    """A tappable block for the Administration hub that links to a dedicated page."""
    return card([
        html.H4(title, style={"marginTop": 0}),
        html.P(description, style={"color": MUTED, "fontSize": "0.85rem", "marginTop": 0}),
        dcc.Link(cta + " \u2192", href=href, style={"color": ACCENT, "fontWeight": 600}),
    ])


def back_link(href="/admin", label="\u2190 Back to Administration"):
    return dcc.Link(label, href=href,
                    style={"color": ACCENT, "fontWeight": 600, "fontSize": "0.85rem",
                           "display": "inline-block", "marginBottom": "14px"})
