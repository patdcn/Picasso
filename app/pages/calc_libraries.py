"""
Calculation - Calculation libraries (module v1, Rev 2 form).

Browse the three libraries (personnel / equipment / misc) with their rates
per rate set x region, and submit check-in requests. The form adapts to the
library: personnel shows the three basis rates and an internal/external
ownership flag (agency labor = external); equipment shows unit + ownership +
one rate; misc shows unit + a sub-category (admin-manageable, each mapped to
the materials or subcontracting element) + one rate.

Codes are suggested automatically as PREFIX-DIV-NNNN (PER/EQP/MSC). The
4-digit number identifies the CONCEPT across divisions: pick a counterpart
("same item, other division") to reuse its number, otherwise the next free
number across the whole library is proposed. Code and ERP number are checked
live - a duplicate turns the field red and blocks submission; the database
UNIQUE constraints remain the hard backstop.

Library admins additionally see the check-in queue here (the /admin area is
portal-admin only), and approve or reject requests inline.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ALL, ctx
from dash.exceptions import PreventUpdate

from app import auth
from app.calcmod import repo

dash.register_page(__name__, path="/calculation/libraries", name="Calculation libraries",
                   title="Calculation libraries", category="Calculation", order=4)

MODULE = "/calculation/libraries"

INK, MUTED, TEAL, LINE, RED = "#1f2937", "#6b7280", "#0f766e", "#e5e7eb", "#b91c1c"
BTN = {"padding": "8px 14px", "borderRadius": "8px", "border": "none", "background": TEAL,
       "color": "#fff", "fontWeight": 600, "cursor": "pointer", "fontSize": "0.85rem"}
BTN_OK = {"padding": "6px 12px", "borderRadius": "8px", "border": "none",
          "background": TEAL, "color": "#fff", "fontWeight": 600, "cursor": "pointer",
          "marginRight": "8px", "fontSize": "0.8rem"}
BTN_NO = {"padding": "6px 12px", "borderRadius": "8px", "border": "1px solid #fecaca",
          "background": "#fff", "color": RED, "cursor": "pointer", "fontSize": "0.8rem"}
FIELD = {"padding": "7px 9px", "borderRadius": "8px", "border": f"1px solid {LINE}",
         "fontSize": "0.85rem", "boxSizing": "border-box", "marginRight": "8px"}
FIELD_BAD = {**FIELD, "border": f"2px solid {RED}", "background": "#fef2f2"}
CARD = {"background": "#fff", "border": f"1px solid {LINE}", "borderRadius": "12px",
        "padding": "16px", "marginBottom": "16px"}
DD = {"display": "inline-block", "verticalAlign": "middle", "marginRight": "8px",
      "fontSize": "0.85rem"}
ROW = {"marginBottom": "8px", "display": "flex", "alignItems": "center",
       "flexWrap": "wrap", "rowGap": "8px"}

LIB_OPTS = [{"label": "Personnel", "value": "personnel"},
            {"label": "Equipment", "value": "equipment"},
            {"label": "Misc / consumables", "value": "misc"}]
DIV_OPTS = [{"label": n, "value": c} for c, n in
            (("CIV", "Civil"), ("OFF", "Offshore"), ("HYD", "Hydropower"))]
REG_OPTS = [{"label": r, "value": r} for r in ("EUR", "WAF", "UAE", "SEA")]
OWN_OPTS = [{"label": "Internal", "value": "internal"},
            {"label": "External", "value": "external"}]
UNIT_OPTS = [{"label": u, "value": u} for u in
             ("day", "night", "week", "hour", "ton", "m3", "ticket", "lump")]


# --------------------------------------------------------------------------- #
# browse
# --------------------------------------------------------------------------- #
def _rate_table(lib, division, rate_set_id, region):
    items = repo.list_items(lib, division, with_rates_for=(rate_set_id, region))
    if not items:
        return html.P("No items in this library for this division.",
                      style={"color": MUTED})
    if lib == "personnel":
        cols = ("Code", "ERP no", "Function", "Ownership", "Currency",
                "Office", "Yard", "Offshore")
        get = lambda i: (i["code"], i.get("erp_no") or "", i["function"],
                         i.get("ownership") or "internal", i.get("currency") or "",
                         i.get("office_rate"), i.get("yard_rate"), i.get("offshore_rate"))
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
        body.append(html.Tr(
            [html.Td(v if v is not None else html.Span("\u2014", style={"color": MUTED}),
                     style=td) for v in get(i)],
            style={"borderBottom": f"1px solid {LINE}"}))
    return html.Table([html.Thead(html.Tr([html.Th(c, style=th) for c in cols])),
                       html.Tbody(body)],
                      style={"borderCollapse": "collapse", "width": "100%"})


# --------------------------------------------------------------------------- #
# check-in form (dynamic per library)
# --------------------------------------------------------------------------- #
def _form_body(lib, division):
    """Rows 1+2 of the form, shaped for the chosen library. Row 1: what it is
    (description/function, category/ownership, region). Row 2: unit + rates.
    Hidden placeholders keep every State id present for the submit callback."""
    cats = repo.list_misc_categories()
    cat_opts = [{"label": f"{c['name']}  \u2192 {c['element']}", "value": c["name"]}
                for c in cats]
    counterparts = repo.counterpart_options(lib, division)
    cp_opts = [{"label": f"{c['code']} \u00b7 {c['label']} ({c['division']})",
                "value": c["uuid"]} for c in counterparts]

    row1 = [dcc.Input(id="cl-req-desc",
                      placeholder=("Function (e.g. Diver)" if lib == "personnel"
                                   else "Description"),
                      style={**FIELD, "width": "300px"})]
    if lib in ("personnel", "equipment"):
        row1.append(dcc.Dropdown(id="cl-req-own", options=OWN_OPTS, value="internal",
                                 clearable=False, style={**DD, "width": "150px"}))
        row1.append(html.Div(dcc.Dropdown(id="cl-req-cat"), style={"display": "none"}))
    else:
        row1.append(dcc.Dropdown(id="cl-req-cat", options=cat_opts,
                                 placeholder="Sub-category (decides the element)",
                                 style={**DD, "width": "280px"}))
        row1.append(html.Div(dcc.Dropdown(id="cl-req-own"), style={"display": "none"}))
    row1.append(dcc.Dropdown(id="cl-req-region", options=REG_OPTS, placeholder="Region",
                             style={**DD, "width": "120px"}))

    if lib == "personnel":
        row2 = [html.Div(dcc.Dropdown(id="cl-req-unit"), style={"display": "none"}),
                dcc.Input(id="cl-req-cur", placeholder="Currency", value="USD",
                          style={**FIELD, "width": "100px"}),
                dcc.Input(id="cl-req-off", type="number", placeholder="Office rate",
                          style={**FIELD, "width": "130px"}),
                dcc.Input(id="cl-req-yard", type="number", placeholder="Yard rate",
                          style={**FIELD, "width": "130px"}),
                dcc.Input(id="cl-req-osh", type="number", placeholder="Offshore rate",
                          style={**FIELD, "width": "140px"}),
                html.Div(dcc.Input(id="cl-req-rate", type="number"),
                         style={"display": "none"})]
    else:
        row2 = [dcc.Dropdown(id="cl-req-unit", options=UNIT_OPTS, value="day",
                             clearable=False, style={**DD, "width": "120px"}),
                dcc.Input(id="cl-req-cur", placeholder="Currency", value="USD",
                          style={**FIELD, "width": "100px"}),
                dcc.Input(id="cl-req-rate", type="number", placeholder="Rate",
                          style={**FIELD, "width": "140px"}),
                html.Div([dcc.Input(id="cl-req-off", type="number"),
                          dcc.Input(id="cl-req-yard", type="number"),
                          dcc.Input(id="cl-req-osh", type="number")],
                         style={"display": "none"})]

    row3 = [
        dcc.Dropdown(id="cl-req-cp", options=cp_opts,
                     placeholder="Counterpart in another division (reuses its number)\u2026",
                     style={**DD, "width": "380px"}),
        dcc.Input(id="cl-req-code", placeholder="Code",
                  value=repo.suggest_code(lib, division),
                  style={**FIELD, "width": "170px",
                         "fontFamily": "ui-monospace,monospace"}),
        dcc.Input(id="cl-req-erp", placeholder="ERP no (Business Central, optional)",
                  style={**FIELD, "width": "240px"}),
    ]
    return html.Div([
        html.Div(row1, style=ROW), html.Div(row2, style=ROW), html.Div(row3, style=ROW),
    ])


def _queue_body():
    reqs = repo.list_requests("submitted")
    if not reqs:
        return html.P("The queue is empty.", style={"color": MUTED})
    out = []
    for r in reqs:
        p = r["payload"]
        item = p.get("item") or {}
        desc = item.get("description") or item.get("function") or p.get("name") or ""
        dup = None
        if r["kind"].endswith("_item"):
            lib = r["kind"].split("_")[0]
            dup = repo.find_item_by_code(lib, code=item.get("code"),
                                         erp_no=item.get("erp_no"))
        rates = "; ".join(
            f"{x.get('region')}: "
            + (f"{x.get('office_rate')}/{x.get('yard_rate')}/{x.get('offshore_rate')}"
               if r["kind"] == "personnel_item" else f"{x.get('rate')}")
            + f" {x.get('currency', 'USD')}" for x in (p.get("rates") or []))
        warn = (html.Div(f"\u26a0 duplicate: {dup['code']} already exists - reject this "
                         "request, or ask for a rate-change request instead.",
                         style={"color": RED, "fontSize": "0.8rem",
                                "fontWeight": 600}) if dup else None)
        out.append(html.Div([
            html.Div([html.B(f"#{r['id']} \u00b7 {r['kind']} \u00b7 {r['division']} \u00b7 "
                             f"{item.get('code') or ''}"),
                      html.Span(f"  by {r['submitted_by']} \u00b7 {r['submitted_at']}",
                                style={"color": MUTED, "fontSize": "0.8rem"})]),
            html.Div(desc, style={"fontSize": "0.88rem", "margin": "3px 0"}),
            html.Div(rates, style={"fontSize": "0.8rem", "color": MUTED}),
            html.Div(r.get("note") or "", style={"fontSize": "0.8rem", "color": MUTED,
                                                 "fontStyle": "italic"}),
            warn,
            html.Div([
                html.Button("Approve", id={"type": "cl-req-ok", "id": r["id"]},
                            n_clicks=0,
                            style={**BTN_OK, "opacity": 0.4} if dup else BTN_OK,
                            disabled=bool(dup)),
                html.Button("Reject", id={"type": "cl-req-no", "id": r["id"]},
                            n_clicks=0, style=BTN_NO),
            ], style={"marginTop": "6px"}),
        ], style={"borderBottom": f"1px solid {LINE}", "padding": "10px 0"}))
    return html.Div(out)


def _queue_card(user):
    """Check-in queue for library admins (the /admin area is portal-admin only,
    so lib-admins review here)."""
    if not repo.is_lib_admin(user["email"], user.get("is_admin")):
        return None
    return html.Div([
        html.H4("Check-in queue (library admin)", style={"marginTop": 0}),
        html.Div(id="cl-queue", children=_queue_body()),
        html.Div(id="cl-queue-status", style={"fontSize": "0.85rem", "color": RED,
                                              "marginTop": "8px", "minHeight": "1.1em"}),
    ], style=CARD)


def layout(**_qs):
    user = auth.current_user()
    if not user:
        return html.Div()
    rs_opts = [{"label": f"{r['label']} \u00b7 {r['status']}", "value": r["id"]}
               for r in repo.list_rate_sets()]
    active = repo.active_rate_set()
    return html.Div([
        html.H3("Calculation libraries"),
        html.P("Rates per rate set and region; the ACTIVE set is what new calculations "
               "snapshot from. Additions and changes go through a check-in request - a "
               "library admin reviews before anything lands.",
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
            html.P("The form follows the library and division chosen above. The code is "
                   "suggested automatically; the 4-digit number identifies the concept "
                   "across divisions (pick a counterpart to reuse its number). Duplicate "
                   "codes and ERP numbers are flagged live and cannot be submitted.",
                   style={"color": MUTED, "fontSize": "0.83rem"}),
            html.Div(id="cl-form", children=_form_body("personnel", "OFF")),
            html.Div(id="cl-dup-msg", style={"fontSize": "0.83rem", "color": RED,
                                             "minHeight": "1.1em", "fontWeight": 600}),
            html.Div([
                dcc.Input(id="cl-req-note", placeholder="Note to the reviewer (optional)",
                          style={**FIELD, "width": "420px"}),
                html.Button("Submit for review", id="cl-req-btn", n_clicks=0, style=BTN),
            ], style={**ROW, "marginTop": "6px"}),
            html.Div(id="cl-req-status", style={"fontSize": "0.85rem", "marginTop": "8px",
                                                "minHeight": "1.1em"}),
        ], style=CARD),

        _queue_card(user),
    ])


# --------------------------------------------------------------------------- #
# callbacks
# --------------------------------------------------------------------------- #
@callback(Output("cl-table", "children"),
          Input("cl-lib", "value"), Input("cl-div", "value"),
          Input("cl-rs", "value"), Input("cl-region", "value"))
def _browse(lib, division, rs, region):
    if not (lib and division and rs and region):
        return no_update
    return _rate_table(lib, division, rs, region)


@callback(Output("cl-form", "children"),
          Input("cl-lib", "value"), Input("cl-div", "value"),
          prevent_initial_call=True)
def _reshape(lib, division):
    if not (lib and division):
        raise PreventUpdate
    return _form_body(lib, division)


@callback(Output("cl-req-code", "value"),
          Input("cl-req-cp", "value"),
          State("cl-lib", "value"), State("cl-div", "value"),
          prevent_initial_call=True)
def _cp_code(cp, lib, division):
    return repo.suggest_code(lib, division, counterpart_uuid=cp)


@callback(Output("cl-req-code", "style"), Output("cl-req-erp", "style"),
          Output("cl-dup-msg", "children"), Output("cl-req-btn", "disabled"),
          Output("cl-req-btn", "style"),
          Input("cl-req-code", "value"), Input("cl-req-erp", "value"),
          State("cl-lib", "value"))
def _live_dup(code, erp, lib):
    """Live duplicate check: red field + message + blocked submit button."""
    code_style = {**FIELD, "width": "170px", "fontFamily": "ui-monospace,monospace"}
    erp_style = {**FIELD, "width": "240px"}
    msg, blocked = "", False
    if lib and code:
        d = repo.find_item_by_code(lib, code=code.strip())
        if d:
            code_style = {**FIELD_BAD, "width": "170px",
                          "fontFamily": "ui-monospace,monospace"}
            dd = d.get("description") or d.get("function") or ""
            msg = (f"Code {d['code']} already exists ({dd}, {d['division']}). "
                   "Use a rate-change request for existing items.")
            blocked = True
    if lib and erp and not blocked:
        d = repo.find_item_by_code(lib, erp_no=erp.strip())
        if d:
            erp_style = {**FIELD_BAD, "width": "240px"}
            msg = f"ERP number already on {d['code']} ({d['division']})."
            blocked = True
    btn_style = {**BTN, "opacity": 0.4, "cursor": "not-allowed"} if blocked else BTN
    return code_style, erp_style, msg, blocked, btn_style


@callback(Output("cl-req-status", "children"),
          Input("cl-req-btn", "n_clicks"),
          State("cl-lib", "value"), State("cl-div", "value"),
          State("cl-req-desc", "value"), State("cl-req-cat", "value"),
          State("cl-req-own", "value"), State("cl-req-region", "value"),
          State("cl-req-unit", "value"), State("cl-req-cur", "value"),
          State("cl-req-rate", "value"), State("cl-req-off", "value"),
          State("cl-req-yard", "value"), State("cl-req-osh", "value"),
          State("cl-req-code", "value"), State("cl-req-erp", "value"),
          State("cl-req-note", "value"),
          prevent_initial_call=True)
def _submit(n, lib, division, desc, cat, own, region, unit, cur,
            rate, off, yard, osh, code, erp, note):
    user = auth.current_user()
    if not n or not user:
        return no_update
    if not (lib and division and (code or "").strip() and (desc or "").strip()):
        return "Description and code are required."
    dup = repo.find_item_by_code(lib, code=code.strip(),
                                 erp_no=(erp or "").strip() or None)
    if dup:
        return "Duplicate code or ERP number - see the message above."
    if lib == "misc" and not cat:
        return ("Choose a sub-category (it decides the element: materials or "
                "sub-contracting).")
    item = {"code": code.strip(), "erp_no": (erp or "").strip() or None}
    if lib == "personnel":
        item["function"] = desc.strip()
        item["ownership"] = own or "internal"
    else:
        item["description"] = desc.strip()
        item["unit"] = unit or "day"
        if lib == "equipment":
            item["ownership"] = own or "internal"
        else:
            item["category"] = cat
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
    return (f"Submitted for review: {code.strip()}. A library admin will approve or "
            "reject it.")


@callback(Output("cl-queue", "children"),
          Output("cl-queue-status", "children"),
          Input({"type": "cl-req-ok", "id": ALL}, "n_clicks"),
          Input({"type": "cl-req-no", "id": ALL}, "n_clicks"),
          prevent_initial_call=True)
def _review(_ok, _no):
    user = auth.current_user()
    if not user or not repo.is_lib_admin(user["email"], user.get("is_admin")):
        raise PreventUpdate
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    err = repo.review_request(trig["id"], trig["type"] == "cl-req-ok", user["email"])
    return _queue_body(), (err or "")
