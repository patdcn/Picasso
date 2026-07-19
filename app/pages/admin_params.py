"""
Admin - Cost & timing assumptions (admins only; guarded by /admin).

Editable shared assumptions used by the diving-bell comparison tools. Built from
the params registry, so new parameters appear here automatically.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, ALL

from app import params
from app.adminui import card, btn, status, back_link, INK, MUTED, ACCENT

dash.register_page(__name__, path="/admin/params", name="Cost & timing assumptions")


def _param_field(p, value):
    return html.Div([
        html.Label(p["label"] + (f"  [{p['unit']}]" if p["unit"] else ""),
                   style={"fontSize": "0.8rem", "fontWeight": 600, "color": INK}),
        dcc.Input(id={"type": "param-input", "key": p["key"]}, type="number",
                  value=value, step=p["step"], debounce=True, style={
                      "width": "100%", "padding": "8px 10px", "borderRadius": "8px",
                      "border": "1px solid #d1d5db", "marginBottom": "4px",
                      "boxSizing": "border-box", "fontFamily": "ui-monospace,monospace"}),
    ], style={"marginBottom": "8px"})


def layout():
    current = params.get_all()
    sections, last_cat = [], None
    for p in params.definitions():
        if p["category"] in ("DP fuel", "Transit fuel", "Harbour fuel"):
            continue                      # own admin section: /admin/fuel
        if p["category"] != last_cat:
            sections.append(html.Div(p["category"], style={
                "fontWeight": 700, "fontSize": "0.85rem", "color": MUTED,
                "margin": "10px 0 6px", "textTransform": "uppercase",
                "letterSpacing": "0.03em"}))
            last_cat = p["category"]
        sections.append(_param_field(p, current[p["key"]]))
    return html.Div([
        back_link(),
        html.H3("Cost & timing assumptions"),
        html.P("These values are used by the Single-vs-twin-bell and Single-vs-single-twin "
               "tools. Edit and save; both pages pick up the new values on their next load.",
               style={"color": MUTED, "maxWidth": "640px"}),
        card([
            *sections,
            html.Div(style={"height": "6px"}),
            btn("Save assumptions", "adm-param-save"),
            status("adm-param-status"),
        ]),
    ], style={"maxWidth": "680px"})


@callback(
    Output("adm-param-status", "children"),
    Input("adm-param-save", "n_clicks"),
    State({"type": "param-input", "key": ALL}, "value"),
    State({"type": "param-input", "key": ALL}, "id"),
    prevent_initial_call=True,
)
def _save_params(_n, values, ids):
    mapping = {i["key"]: v for i, v in zip(ids or [], values or [])}
    n, msg = params.set_many(mapping)
    return html.Span(msg, style={"color": ACCENT if n else "#b91c1c"})
