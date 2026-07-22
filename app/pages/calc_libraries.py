"""
Calculation - Calculation libraries (module v1, form iteration 3).

Browse the three libraries with their rates per rate set x region, submit
check-in requests, and (library admins) review the queue and edit items
directly.

Codes: P-O-I-0001 = library (P/E/M) - division (C/O/H) - ownership (I/E) -
concept number; misc has no ownership segment (M-O-0001). Region is NOT in
the code: one item carries rates per region, with 'ALL' as fallback - a rate
entered under ALL applies wherever no region-specific rate exists (browse
marks such rates with an asterisk).

Mandatory on check-in: description/function, region, currency and at least
one rate; misc additionally needs a sub-category. Duplicate codes and ERP
numbers are flagged live (red field) and block submission; the DB UNIQUE
constraints remain the hard backstop.

The check-in queue lives here for library admins (the /admin area is
portal-admin only) and refreshes immediately after a submission.
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
BTN_GHOST = {"padding": "5px 10px", "borderRadius": "7px", "border": f"1px solid {LINE}",
             "background": "#fff", "color": INK, "cursor": "pointer",
             "fontSize": "0.75rem"}
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
            {"label": "Materials & sub-contracting", "value": "misc"}]
DIV_OPTS = [{"label": n, "value": c} for c, n in
            (("CIV", "Civil"), ("OFF", "Offshore"), ("HYD", "Hydropower"))]
RATE_REG_OPTS = [{"label": "ALL (fallback)", "value": "ALL"}] + \
                [{"label": r, "value": r} for r in ("EUR", "WAF", "UAE", "SEA")]
OWN_OPTS = [{"label": "Internal", "value": "internal"},
            {"label": "External", "value": "external"}]
UNIT_OPTS = [{"label": u, "value": u} for u in
             ("day", "night", "week", "hour", "ton", "m3", "ticket", "lump")]


def _is_lib_admin():
    user = auth.current_user()
    return bool(user and repo.is_lib_admin(user["email"], user.get("is_admin")))


# --------------------------------------------------------------------------- #
# browse
# --------------------------------------------------------------------------- #
def _fmt_rate(item, field):
    v = item.get(field)
    if v is None:
        return html.Span("\u2014", style={"color": MUTED})
    if item.get("rate_region") == "ALL":
        return html.Span(f"{v} *", title="ALL-region fallback rate")
    return v


def _rate_table(lib, division, rate_set_id, region, editable):
    items = repo.list_items(lib, division, with_rates_for=(rate_set_id, region))
    if not items:
        return html.P("No items in this library for this division.",
                      style={"color": MUTED})
    if lib == "personnel":
        cols = ("Code", "ERP no", "Function", "Ownership", "Currency",
                "Office", "Yard", "Offshore")
        get = lambda i: (i["code"], i.get("erp_no") or "", i["function"],
                         i.get("ownership") or "internal", i.get("currency") or "",
                         _fmt_rate(i, "office_rate"), _fmt_rate(i, "yard_rate"),
                         _fmt_rate(i, "offshore_rate"))
    elif lib == "equipment":
        cols = ("Code", "ERP no", "Description", "Unit", "Ownership", "Currency", "Rate")
        get = lambda i: (i["code"], i.get("erp_no") or "", i["description"], i["unit"],
                         i["ownership"], i.get("currency") or "", _fmt_rate(i, "rate"))
    else:
        cols = ("Code", "ERP no", "Category", "Description", "Unit", "Currency", "Rate")
        get = lambda i: (i["code"], i.get("erp_no") or "", i["category"],
                         i["description"], i["unit"], i.get("currency") or "",
                         _fmt_rate(i, "rate"))
    th = {"textAlign": "left", "padding": "5px 9px", "fontSize": "0.75rem",
          "color": MUTED, "borderBottom": f"2px solid {LINE}"}
    td = {"padding": "5px 9px", "fontSize": "0.84rem"}
    body = []
    for i in items:
        cells = [html.Td(v, style=td) for v in get(i)]
        if editable:
            cells.append(html.Td(html.Button(
                "Edit", id={"type": "cl-edit", "uuid": i["uuid"]}, n_clicks=0,
                style=BTN_GHOST), style=td))
        body.append(html.Tr(cells, style={"borderBottom": f"1px solid {LINE}"}))
    heads = [html.Th(c, style=th) for c in cols] + \
            ([html.Th("", style=th)] if editable else [])
    note = html.P("* = ALL-region fallback rate (no region-specific rate for this "
                  "region).", style={"color": MUTED, "fontSize": "0.75rem",
                                     "marginBottom": 0}) \
        if any(i.get("rate_region") == "ALL" for i in items) else None
    return html.Div([html.Table([html.Thead(html.Tr(heads)), html.Tbody(body)],
                                style={"borderCollapse": "collapse", "width": "100%"}),
                     note])


# --------------------------------------------------------------------------- #
# check-in form (dynamic per library)
# --------------------------------------------------------------------------- #
def _form_body(lib, division):
    cats = repo.list_misc_categories()
    cat_opts = [{"label": f"{c['name']}  \u2192 {c['element']}", "value": c["name"]}
                for c in cats]
    counterparts = repo.counterpart_options(lib, division)
    cp_opts = [{"label": f"{c['code']} \u00b7 {c['label']} ({c['division']})",
                "value": c["uuid"]} for c in counterparts]

    row1 = [dcc.Input(id="cl-req-desc",
                      placeholder=("Function (e.g. Diver) *" if lib == "personnel"
                                   else "Description *"),
                      style={**FIELD, "width": "300px"})]
    if lib in ("personnel", "equipment"):
        row1.append(dcc.Dropdown(id="cl-req-own", options=OWN_OPTS, value="internal",
                                 clearable=False, style={**DD, "width": "150px"}))
        row1.append(html.Div(dcc.Dropdown(id="cl-req-cat"), style={"display": "none"}))
    else:
        row1.append(dcc.Dropdown(id="cl-req-cat", options=cat_opts,
                                 placeholder="Sub-category * (decides the element)",
                                 style={**DD, "width": "280px"}))
        row1.append(html.Div(dcc.Dropdown(id="cl-req-own"), style={"display": "none"}))
    row1.append(dcc.Dropdown(id="cl-req-region", options=RATE_REG_OPTS,
                             placeholder="Region *", style={**DD, "width": "160px"}))

    if lib == "personnel":
        row2 = [html.Div(dcc.Dropdown(id="cl-req-unit"), style={"display": "none"}),
                dcc.Input(id="cl-req-cur", placeholder="Currency *", value="USD",
                          style={**FIELD, "width": "110px"}),
                dcc.Input(id="cl-req-off", type="number", placeholder="Office rate",
                          style={**FIELD, "width": "130px"}),
                dcc.Input(id="cl-req-yard", type="number", placeholder="Yard rate",
                          style={**FIELD, "width": "130px"}),
                dcc.Input(id="cl-req-osh", type="number", placeholder="Offshore rate",
                          style={**FIELD, "width": "140px"}),
                html.Span("at least one rate *", style={"color": MUTED,
                                                        "fontSize": "0.75rem"}),
                html.Div(dcc.Input(id="cl-req-rate", type="number"),
                         style={"display": "none"})]
    else:
        row2 = [dcc.Dropdown(id="cl-req-unit", options=UNIT_OPTS, value="day",
                             clearable=False, style={**DD, "width": "120px"}),
                dcc.Input(id="cl-req-cur", placeholder="Currency *", value="USD",
                          style={**FIELD, "width": "110px"}),
                dcc.Input(id="cl-req-rate", type="number", placeholder="Rate *",
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
                  style={**FIELD, "width": "150px",
                         "fontFamily": "ui-monospace,monospace"}),
        dcc.Input(id="cl-req-erp", placeholder="ERP no (Business Central, optional)",
                  style={**FIELD, "width": "240px"}),
    ]
    return html.Div([
        html.Div(row1, style=ROW), html.Div(row2, style=ROW), html.Div(row3, style=ROW),
        html.P("* required", style={"color": MUTED, "fontSize": "0.72rem",
                                    "margin": "0"}),
    ])


# --------------------------------------------------------------------------- #
# queue (library admins)
# --------------------------------------------------------------------------- #
def _queue_body():
    if not _is_lib_admin():
        return html.Div()
    reqs = repo.list_requests("submitted")
    head = html.H4("Check-in queue (library admin)", style={"marginTop": 0})
    if not reqs:
        return html.Div([head, html.P("The queue is empty.", style={"color": MUTED})],
                        style=CARD)
    out = [head]
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
    out.append(html.Div(id="cl-queue-status",
                        style={"fontSize": "0.85rem", "color": RED,
                               "marginTop": "8px", "minHeight": "1.1em"}))
    return html.Div(out, style=CARD)


# --------------------------------------------------------------------------- #
# layout
# --------------------------------------------------------------------------- #
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
               "snapshot from. A rate under region ALL applies wherever no "
               "region-specific rate exists. Additions and changes go through a "
               "check-in request - a library admin reviews before anything lands.",
               style={"color": MUTED, "maxWidth": "780px"}),

        html.Div([
            dcc.Dropdown(id="cl-lib", options=LIB_OPTS, value="personnel",
                         clearable=False, style={**DD, "width": "230px"}),
            dcc.Dropdown(id="cl-div", options=DIV_OPTS, value="OFF",
                         clearable=False, style={**DD, "width": "160px"}),
            dcc.Dropdown(id="cl-rs", options=rs_opts,
                         value=active["id"] if active else None,
                         clearable=False, style={**DD, "width": "200px"}),
            dcc.Dropdown(id="cl-region", options=RATE_REG_OPTS, value="EUR",
                         clearable=False, style={**DD, "width": "160px"}),
        ], style={"marginBottom": "10px"}),
        html.Div(id="cl-table", style=CARD),
        html.Div(id="cl-editcard"),          # admin edit panel (filled on Edit click)
        dcc.Store(id="cl-edit-uuid"),

        html.Div([
            html.H4("Check-in request \u2014 new item", style={"marginTop": 0}),
            html.P("The form follows the library and division chosen above. The code is "
                   "suggested automatically (library-division-ownership-number); the "
                   "number identifies the concept across divisions - pick a counterpart "
                   "to reuse it. Duplicates are flagged live and cannot be submitted.",
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

        html.Div(id="cl-queue", children=_queue_body()),
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
    return _rate_table(lib, division, rs, region, editable=_is_lib_admin())


@callback(Output("cl-form", "children"),
          Input("cl-lib", "value"), Input("cl-div", "value"),
          prevent_initial_call=True)
def _reshape(lib, division):
    if not (lib and division):
        raise PreventUpdate
    return _form_body(lib, division)


@callback(Output("cl-req-code", "value"),
          Input("cl-req-cp", "value"), Input("cl-req-own", "value"),
          State("cl-lib", "value"), State("cl-div", "value"),
          prevent_initial_call=True)
def _re_suggest(cp, own, lib, division):
    return repo.suggest_code(lib, division, ownership=own or "internal",
                             counterpart_uuid=cp)


@callback(Output("cl-req-code", "style"), Output("cl-req-erp", "style"),
          Output("cl-dup-msg", "children"), Output("cl-req-btn", "disabled"),
          Output("cl-req-btn", "style"),
          Input("cl-req-code", "value"), Input("cl-req-erp", "value"),
          State("cl-lib", "value"))
def _live_dup(code, erp, lib):
    code_style = {**FIELD, "width": "150px", "fontFamily": "ui-monospace,monospace"}
    erp_style = {**FIELD, "width": "240px"}
    msg, blocked = "", False
    if lib and code:
        d = repo.find_item_by_code(lib, code=code.strip())
        if d:
            code_style = {**FIELD_BAD, "width": "150px",
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
          Output("cl-queue", "children", allow_duplicate=True),
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
        return no_update, no_update
    missing = []
    if not (desc or "").strip():
        missing.append("description/function")
    if not (code or "").strip():
        missing.append("code")
    if not region:
        missing.append("region")
    if not (cur or "").strip():
        missing.append("currency")
    if lib == "misc" and not cat:
        missing.append("sub-category")
    if lib == "personnel":
        if not any(v is not None for v in (off, yard, osh)):
            missing.append("at least one rate (office/yard/offshore)")
    elif rate is None:
        missing.append("rate")
    if missing:
        return "Required: " + ", ".join(missing) + ".", no_update
    dup = repo.find_item_by_code(lib, code=code.strip(),
                                 erp_no=(erp or "").strip() or None)
    if dup:
        return "Duplicate code or ERP number - see the message above.", no_update
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
    rr = {"region": region, "currency": cur.strip().upper()}
    if lib == "personnel":
        rr.update(office_rate=off, yard_rate=yard, offshore_rate=osh)
    else:
        rr.update(rate=rate)
    repo.submit_request(f"{lib}_item", division, {"item": item, "rates": [rr]},
                        user["email"], note=(note or "").strip() or None)
    return (f"Submitted for review: {code.strip()}.", _queue_body())


@callback(Output("cl-queue", "children", allow_duplicate=True),
          Input({"type": "cl-req-ok", "id": ALL}, "n_clicks"),
          Input({"type": "cl-req-no", "id": ALL}, "n_clicks"),
          prevent_initial_call=True)
def _review(_ok, _no):
    if not _is_lib_admin():
        raise PreventUpdate
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    user = auth.current_user()
    repo.review_request(trig["id"], trig["type"] == "cl-req-ok", user["email"])
    return _queue_body()


# --------------------------------------------------------------------------- #
# direct edit (library admins)
# --------------------------------------------------------------------------- #
def _edit_card(lib, uuid, rs, region):
    items = {i["uuid"]: i for i in repo.list_items(lib, active_only=False,
                                                   with_rates_for=(rs, region))}
    i = items.get(uuid)
    if not i:
        return html.Div()
    cats = repo.list_misc_categories()
    cat_opts = [{"label": f"{c['name']}  \u2192 {c['element']}", "value": c["name"]}
                for c in cats]
    is_per, is_msc = lib == "personnel", lib == "misc"
    fields = [
        html.Span(i["code"], style={"fontFamily": "ui-monospace,monospace",
                                    "fontWeight": 700, "marginRight": "12px"}),
        dcc.Input(id="cl-ed-desc", value=i.get("description") or i.get("function"),
                  style={**FIELD, "width": "280px"}),
        dcc.Input(id="cl-ed-erp", value=i.get("erp_no"), placeholder="ERP no",
                  style={**FIELD, "width": "170px"}),
    ]
    if is_msc:
        fields.append(dcc.Dropdown(id="cl-ed-cat", options=cat_opts,
                                   value=i.get("category"),
                                   style={**DD, "width": "240px"}))
        fields.append(html.Div(dcc.Dropdown(id="cl-ed-own"), style={"display": "none"}))
    else:
        fields.append(dcc.Dropdown(id="cl-ed-own", options=OWN_OPTS,
                                   value=i.get("ownership") or "internal",
                                   clearable=False, style={**DD, "width": "140px"}))
        fields.append(html.Div(dcc.Dropdown(id="cl-ed-cat"), style={"display": "none"}))
    if is_per:
        fields.append(html.Div(dcc.Dropdown(id="cl-ed-unit"), style={"display": "none"}))
    else:
        fields.append(dcc.Dropdown(id="cl-ed-unit", options=UNIT_OPTS,
                                   value=i.get("unit") or "day", clearable=False,
                                   style={**DD, "width": "110px"}))
    rate_row = [
        html.Span(f"Rates for this rate set \u00b7 region "
                  f"{region}: ", style={"color": MUTED, "fontSize": "0.8rem",
                                        "marginRight": "8px"}),
        dcc.Input(id="cl-ed-cur", value=i.get("currency") or "USD",
                  placeholder="Currency", style={**FIELD, "width": "100px"}),
    ]
    if is_per:
        rate_row += [dcc.Input(id="cl-ed-off", type="number", value=i.get("office_rate"),
                               placeholder="Office", style={**FIELD, "width": "110px"}),
                     dcc.Input(id="cl-ed-yard", type="number", value=i.get("yard_rate"),
                               placeholder="Yard", style={**FIELD, "width": "110px"}),
                     dcc.Input(id="cl-ed-osh", type="number",
                               value=i.get("offshore_rate"), placeholder="Offshore",
                               style={**FIELD, "width": "110px"}),
                     html.Div(dcc.Input(id="cl-ed-rate", type="number"),
                              style={"display": "none"})]
    else:
        rate_row += [dcc.Input(id="cl-ed-rate", type="number", value=i.get("rate"),
                               placeholder="Rate", style={**FIELD, "width": "130px"}),
                     html.Div([dcc.Input(id="cl-ed-off", type="number"),
                               dcc.Input(id="cl-ed-yard", type="number"),
                               dcc.Input(id="cl-ed-osh", type="number")],
                              style={"display": "none"})]
    if i.get("rate_region") == "ALL" and region != "ALL":
        rate_row.append(html.Span("(shown: ALL fallback - saving writes a "
                                  f"{region}-specific rate)",
                                  style={"color": MUTED, "fontSize": "0.75rem"}))
    return html.Div([
        html.H4(f"Edit item (direct, library admin)", style={"marginTop": 0}),
        html.Div(fields, style=ROW),
        html.Div(rate_row, style=ROW),
        html.Div([html.Button("Save", id="cl-ed-save", n_clicks=0, style=BTN),
                  html.Button("Close", id="cl-ed-close", n_clicks=0,
                              style={**BTN_GHOST, "marginLeft": "8px"})]),
        html.Div(id="cl-ed-status", style={"fontSize": "0.85rem", "marginTop": "8px",
                                           "minHeight": "1.1em", "color": RED}),
    ], style={**CARD, "border": f"2px solid {TEAL}"})


@callback(Output("cl-editcard", "children"),
          Output("cl-edit-uuid", "data"),
          Input({"type": "cl-edit", "uuid": ALL}, "n_clicks"),
          Input("cl-ed-close", "n_clicks"),
          State("cl-lib", "value"), State("cl-rs", "value"),
          State("cl-region", "value"),
          prevent_initial_call=True)
def _open_edit(_clicks, _close, lib, rs, region):
    trig = ctx.triggered_id
    if trig == "cl-ed-close":
        return html.Div(), None
    if not isinstance(trig, dict) or not ctx.triggered[0]["value"] or not _is_lib_admin():
        raise PreventUpdate
    return _edit_card(lib, trig["uuid"], rs, region), trig["uuid"]


@callback(Output("cl-ed-status", "children"),
          Output("cl-table", "children", allow_duplicate=True),
          Input("cl-ed-save", "n_clicks"),
          State("cl-edit-uuid", "data"), State("cl-lib", "value"),
          State("cl-div", "value"), State("cl-rs", "value"),
          State("cl-region", "value"),
          State("cl-ed-desc", "value"), State("cl-ed-erp", "value"),
          State("cl-ed-cat", "value"), State("cl-ed-own", "value"),
          State("cl-ed-unit", "value"), State("cl-ed-cur", "value"),
          State("cl-ed-rate", "value"), State("cl-ed-off", "value"),
          State("cl-ed-yard", "value"), State("cl-ed-osh", "value"),
          prevent_initial_call=True)
def _save_edit(n, uuid, lib, division, rs, region, desc, erp, cat, own, unit,
               cur, rate, off, yard, osh):
    if not n or not uuid or not _is_lib_admin():
        raise PreventUpdate
    items = {i["uuid"]: i for i in repo.list_items(lib, active_only=False)}
    i = items.get(uuid)
    if not i:
        return "Item no longer exists.", no_update
    if not (desc or "").strip():
        return "Description/function is required.", no_update
    data = {"uuid": uuid, "code": i["code"], "erp_no": (erp or "").strip() or None,
            "division": i["division"]}
    if lib == "personnel":
        data["function"] = desc.strip()
        data["ownership"] = own or "internal"
    else:
        data["description"] = desc.strip()
        data["unit"] = unit or "day"
        if lib == "equipment":
            data["ownership"] = own or "internal"
        else:
            data["category"] = cat
    # ownership letter is part of the code: regenerate the segment on change
    if lib != "misc" and (own or "internal") != (i.get("ownership") or "internal"):
        parts = i["code"].split("-")
        if len(parts) == 4:
            parts[2] = repo.OWN_LETTER[own or "internal"]
            new_code = "-".join(parts)
            clash = repo.find_item_by_code(lib, code=new_code)
            if clash and clash["uuid"] != uuid:
                return (f"Changing ownership would collide with existing {new_code} - "
                        "adjust that item first.", no_update)
            data["code"] = new_code
    # ERP duplicate check against other items
    if data["erp_no"]:
        clash = repo.find_item_by_code(lib, erp_no=data["erp_no"])
        if clash and clash["uuid"] != uuid:
            return f"ERP number already on {clash['code']}.", no_update
    repo.upsert_item(lib, data)
    kw = ({"office_rate": off, "yard_rate": yard, "offshore_rate": osh}
          if lib == "personnel" else {"rate": rate})
    if any(v is not None for v in kw.values()):
        repo.set_item_rate(lib, uuid, rs, region, (cur or "USD").strip().upper(), **kw)
    return ("Saved.",
            _rate_table(lib, division, rs, region, editable=True))
