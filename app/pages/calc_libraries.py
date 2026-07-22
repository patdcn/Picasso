"""
Calculation - Calculation libraries (module v1).

Browse the equipment / personnel / misc libraries with their rates (any rate
set x region), and submit check-in requests: propose a new item with rates,
or a rate change for an existing item. Nothing lands in the library directly -
a library admin reviews every request on Admin -> Calculation module, and only
approval writes. Same moderation philosophy as the HIRA library.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, no_update

from app import auth
from app.calcmod import repo

dash.register_page(__name__, path="/calculation/libraries", name="Calculation libraries",
                   title="Calculation libraries", category="Calculation", order=4)

MODULE = "/calculation/libraries"

INK, MUTED, TEAL, LINE = "#1f2937", "#6b7280", "#0f766e", "#e5e7eb"
BTN = {"padding": "8px 14px", "borderRadius": "8px", "border": "none", "background": TEAL,
       "color": "#fff", "fontWeight": 600, "cursor": "pointer", "fontSize": "0.85rem"}
FIELD = {"padding": "7px 9px", "borderRadius": "8px", "border": f"1px solid {LINE}",
         "fontSize": "0.85rem", "boxSizing": "border-box", "marginRight": "8px"}
CARD = {"background": "#fff", "border": f"1px solid {LINE}", "borderRadius": "12px",
        "padding": "16px", "marginBottom": "16px"}
DD = {"display": "inline-block", "verticalAlign": "middle", "marginRight": "8px",
      "fontSize": "0.85rem"}

LIB_OPTS = [{"label": "Personnel", "value": "personnel"},
            {"label": "Equipment", "value": "equipment"},
            {"label": "Misc / consumables", "value": "misc"}]
DIV_OPTS = [{"label": n, "value": c} for c, n in
            (("CIV", "Civil"), ("OFF", "Offshore"), ("HYD", "Hydropower"))]
REG_OPTS = [{"label": r, "value": r} for r in ("EUR", "WAF", "UAE", "SEA")]


def _rate_table(lib, division, rate_set_id, region):
    items = repo.list_items(lib, division, with_rates_for=(rate_set_id, region))
    if not items:
        return html.P("No items in this library for this division.",
                      style={"color": MUTED})
    if lib == "personnel":
        cols = ("Code", "ERP no", "Function", "Currency", "Office", "Yard", "Offshore")
        get = lambda i: (i["code"], i.get("erp_no") or "", i["function"],
                         i.get("currency") or "", i.get("office_rate"),
                         i.get("yard_rate"), i.get("offshore_rate"))
    elif lib == "equipment":
        cols = ("Code", "ERP no", "Description", "Unit", "Ownership", "Currency", "Rate")
        get = lambda i: (i["code"], i.get("erp_no") or "", i["description"], i["unit"],
                         i["ownership"], i.get("currency") or "", i.get("rate"))
    else:
        cols = ("Code", "ERP no", "Category", "Description", "Unit", "Currency", "Rate")
        get = lambda i: (i["code"], i.get("erp_no") or "", i["category"],
                         i["description"], i["unit"], i.get("currency") or "",
                         i.get("rate"))
    th = {"textAlign": "left", "padding": "5px 9px", "fontSize": "0.75rem",
          "color": MUTED, "borderBottom": f"2px solid {LINE}"}
    td = {"padding": "5px 9px", "fontSize": "0.84rem"}
    body = []
    for i in items:
        vals = get(i)
        body.append(html.Tr(
            [html.Td(v if v is not None else html.Span("\u2014", style={"color": MUTED}),
                     style=td) for v in vals],
            style={"borderBottom": f"1px solid {LINE}"}))
    return html.Table([html.Thead(html.Tr([html.Th(c, style=th) for c in cols])),
                       html.Tbody(body)],
                      style={"borderCollapse": "collapse", "width": "100%"})


def layout(**_qs):
    user = auth.current_user()
    if not user:
        return html.Div()
    rs_opts = [{"label": f"{r['label']} \u00b7 {r['status']}", "value": r["id"]}
               for r in repo.list_rate_sets()]
    active = repo.active_rate_set()
    return html.Div([
        html.H3("Calculation libraries"),
        html.P("Rates shown per rate set and region; the ACTIVE set is what new "
               "calculations snapshot from. To add an item or change a rate, submit a "
               "check-in request below - a library admin reviews it before it lands.",
               style={"color": MUTED, "maxWidth": "760px"}),

        html.Div([
            dcc.Dropdown(id="cl-lib", options=LIB_OPTS, value="personnel",
                         clearable=False, style={**DD, "width": "190px"}),
            dcc.Dropdown(id="cl-div", options=DIV_OPTS, value="OFF",
                         clearable=False, style={**DD, "width": "160px"}),
            dcc.Dropdown(id="cl-rs", options=rs_opts,
                         value=active["id"] if active else None,
                         clearable=False, style={**DD, "width": "200px"}),
            dcc.Dropdown(id="cl-region", options=REG_OPTS, value="EUR",
                         clearable=False, style={**DD, "width": "120px"}),
        ], style={"marginBottom": "10px"}),
        html.Div(id="cl-table", style=CARD),

        html.Div([
            html.H4("Check-in request \u2014 new item", style={"marginTop": 0}),
            html.P("Propose a new library item with its rate for one region (further "
                   "regions can follow in later requests). The ERP number comes from "
                   "Business Central.", style={"color": MUTED, "fontSize": "0.83rem"}),
            html.Div([
                dcc.Dropdown(id="cl-req-lib", options=LIB_OPTS, placeholder="Library",
                             style={**DD, "width": "190px"}),
                dcc.Dropdown(id="cl-req-div", options=DIV_OPTS, placeholder="Division",
                             style={**DD, "width": "160px"}),
                dcc.Input(id="cl-req-code", placeholder="Code (e.g. PER-OFF-0012)",
                          style={**FIELD, "width": "190px"}),
                dcc.Input(id="cl-req-erp", placeholder="ERP no (Business Central)",
                          style={**FIELD, "width": "180px"}),
            ], style={"marginBottom": "8px"}),
            html.Div([
                dcc.Input(id="cl-req-desc", placeholder="Description / function",
                          style={**FIELD, "width": "320px"}),
                dcc.Input(id="cl-req-unit", placeholder="Unit (day / night / ton\u2026)",
                          style={**FIELD, "width": "160px"}),
                dcc.Input(id="cl-req-cat",
                          placeholder="Category (misc) / ownership (equipment)",
                          style={**FIELD, "width": "260px"}),
            ], style={"marginBottom": "8px"}),
            html.Div([
                dcc.Dropdown(id="cl-req-region", options=REG_OPTS, placeholder="Region",
                             style={**DD, "width": "120px"}),
                dcc.Input(id="cl-req-cur", placeholder="Currency (USD)", value="USD",
                          style={**FIELD, "width": "110px"}),
                dcc.Input(id="cl-req-rate", type="number",
                          placeholder="Rate (equipment/misc)",
                          style={**FIELD, "width": "170px"}),
                dcc.Input(id="cl-req-off", type="number", placeholder="Office rate",
                          style={**FIELD, "width": "120px"}),
                dcc.Input(id="cl-req-yard", type="number", placeholder="Yard rate",
                          style={**FIELD, "width": "120px"}),
                dcc.Input(id="cl-req-osh", type="number", placeholder="Offshore rate",
                          style={**FIELD, "width": "130px"}),
            ], style={"marginBottom": "8px"}),
            html.Div([
                dcc.Input(id="cl-req-note", placeholder="Note to the reviewer (optional)",
                          style={**FIELD, "width": "420px"}),
                html.Button("Submit for review", id="cl-req-btn", n_clicks=0, style=BTN),
            ]),
            html.Div(id="cl-req-status", style={"fontSize": "0.85rem", "marginTop": "8px",
                                                "minHeight": "1.1em"}),
        ], style=CARD),
    ])


@callback(Output("cl-table", "children"),
          Input("cl-lib", "value"), Input("cl-div", "value"),
          Input("cl-rs", "value"), Input("cl-region", "value"))
def _browse(lib, division, rs, region):
    if not (lib and division and rs and region):
        return no_update
    return _rate_table(lib, division, rs, region)


@callback(Output("cl-req-status", "children"),
          Input("cl-req-btn", "n_clicks"),
          State("cl-req-lib", "value"), State("cl-req-div", "value"),
          State("cl-req-code", "value"), State("cl-req-erp", "value"),
          State("cl-req-desc", "value"), State("cl-req-unit", "value"),
          State("cl-req-cat", "value"), State("cl-req-region", "value"),
          State("cl-req-cur", "value"), State("cl-req-rate", "value"),
          State("cl-req-off", "value"), State("cl-req-yard", "value"),
          State("cl-req-osh", "value"), State("cl-req-note", "value"),
          prevent_initial_call=True)
def _submit(n, lib, division, code, erp, desc, unit, cat, region, cur,
            rate, off, yard, osh, note):
    user = auth.current_user()
    if not n or not user:
        return no_update
    if not (lib and division and code and desc):
        return "Library, division, code and description are required."
    item = {"code": code.strip(), "erp_no": (erp or "").strip() or None}
    if lib == "personnel":
        item["function"] = desc.strip()
    else:
        item["description"] = desc.strip()
        item["unit"] = (unit or "day").strip()
        if lib == "equipment":
            item["ownership"] = (cat or "internal").strip().lower()
        else:
            item["category"] = (cat or "general").strip().lower()
    rates = []
    if region:
        rr = {"region": region, "currency": (cur or "USD").strip().upper()}
        if lib == "personnel":
            rr.update(office_rate=off, yard_rate=yard, offshore_rate=osh)
        else:
            rr.update(rate=rate)
        rates.append(rr)
    repo.submit_request(f"{lib}_item", division, {"item": item, "rates": rates},
                        user["email"], note=(note or "").strip() or None)
    return (f"Submitted for review: {code}. A library admin will approve or reject it "
            "on the Admin page.")
