"""
Admin - Fuel consumption (admins only; guarded by /admin).

The DG specific fuel oil consumption curve and fuel density behind the DP
Environment Planner's fuel estimate. Registry category "DP fuel" — rendered
here instead of the general parameters page. Values are ELECTRICAL basis
(g per kWe·h): MAN L27/38 project guide engine figures divided by the 0.96
alternator efficiency implied by the 2,851 kWe DG rating.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, ALL

from app import params, dpdocs, dp_fuel
from app.adminui import card, btn, status, back_link, INK, MUTED, ACCENT

dash.register_page(__name__, path="/admin/fuel", name="Fuel consumption")


def _field(p, value):
    return html.Div([
        html.Label(p["label"] + (f"  [{p['unit']}]" if p["unit"] else ""),
                   style={"fontSize": "0.8rem", "fontWeight": 600, "color": INK}),
        dcc.Input(id={"type": "fuel-param", "key": p["key"]}, type="number",
                  value=value, step=p["step"], debounce=True, style={
                      "width": "100%", "padding": "8px 10px", "borderRadius": "8px",
                      "border": "1px solid #d1d5db", "marginBottom": "4px",
                      "boxSizing": "border-box",
                      "fontFamily": "ui-monospace,monospace"}),
    ], style={"marginBottom": "8px"})


def layout():
    current = params.get_all()
    fields = []
    for cat, title in (("DP fuel", "DP — DG SFOC curve & density"),
                       ("Transit fuel", "Transit — propulsion service point")):
        fields.append(html.Div(title, style={
            "fontWeight": 700, "fontSize": "0.85rem", "color": INK,
            "margin": "10px 0 6px", "borderBottom": "1px solid #e2e8f0",
            "paddingBottom": "3px"}))
        fields += [_field(p, current[p["key"]]) for p in params.definitions()
                   if p["category"] == cat]
    return html.Div([
        back_link(),
        html.H3("Fuel consumption"),
        html.P(["DG SFOC anchor points (piecewise-linear, held flat below 25% "
                "and above 100%) and fuel density, used by the DP Environment "
                "Planner's expected-consumption estimate. Electrical basis "
                "(g/kWe\u00b7h). Reference values: ",
                dpdocs.link("engine_pg", "MAN L27/38 GenSet project guide"),
                " Tier II sheet, 9L27/38 @ 330 kW/cyl / 720 rpm, engine g/kWh "
                "\u00f7 0.96 alternator \u2192 216 / 191 / 190 / 189 / 192 at "
                "25/50/75/85/100%; ISO reference, excl. the +5% guarantee "
                "tolerance. Validated against Jul\u2013Oct 2025 fuel "
                "monitoring (on-DP median 15.8 m\u00b3/day)."],
               style={"color": MUTED, "maxWidth": "680px"}),
        card([
            *fields,
            html.Div(style={"height": "6px"}),
            btn("Save fuel parameters", "adm-fuel-save"),
            status("adm-fuel-status"),
        ]),
    ], style={"maxWidth": "680px"})


@callback(
    Output("adm-fuel-status", "children"),
    Input("adm-fuel-save", "n_clicks"),
    State({"type": "fuel-param", "key": ALL}, "value"),
    State({"type": "fuel-param", "key": ALL}, "id"),
    prevent_initial_call=True,
)
def _save(_n, values, ids):
    mapping = {i["key"]: v for i, v in zip(ids or [], values or [])}
    n, msg = params.set_many(mapping)
    return html.Span(msg, style={"color": ACCENT if n else "#b91c1c"})
