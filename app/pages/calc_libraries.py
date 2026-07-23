"""
Calculation - Calculation libraries (module v1, iteration 4).

Four user-facing libraries - Personnel (P), Equipment (E), Materials (M),
Sub-contracting (S); the last two are views on one table split by their
sub-category's element. Codes: P-O-I-A-0001 = library - division (C/O/H) -
ownership (I/E, personnel & equipment) - region (E/W/U/S, A = all) - concept
number. Region is an ITEM attribute: a Diver with different regional rates is
separate items sharing the concept number.

Page order: (1) selectors that FEED THE CHECK-IN FORM (they no longer filter
the overview), (2) the check-in form, (3) the review queue (library admins),
(4) one unified overview of ALL items with the columns Code / Description /
Category / Sub-category / Int-Ext / Region / Unit / Currency / Rate. Click
any Category / Sub-category / Int-Ext / Region / Unit value in a row to
filter on it (chips above the table; click a chip to clear). Rates shown are
the ACTIVE set. ERP numbers stay stored but are hidden for now.

Library admins: Edit turns the row into inline fields (pattern IDs, so the
callbacks are valid before any row is in edit mode - the fix for the earlier
dead Edit button); Duplicate copies a row into the check-in form for
amendment and submission.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ALL, ctx
from dash.exceptions import PreventUpdate

from app import auth
from app.calcmod import repo, excel_export

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
             "fontSize": "0.75rem", "marginRight": "4px"}
FIELD = {"padding": "7px 9px", "borderRadius": "8px", "border": f"1px solid {LINE}",
         "fontSize": "0.85rem", "boxSizing": "border-box", "marginRight": "8px"}
FIELD_BAD = {**FIELD, "border": f"2px solid {RED}", "background": "#fef2f2"}
SMALL = {"padding": "4px 6px", "borderRadius": "6px", "border": f"1px solid {LINE}",
         "fontSize": "0.8rem", "boxSizing": "border-box"}
CARD = {"background": "#fff", "border": f"1px solid {LINE}", "borderRadius": "12px",
        "padding": "16px", "marginBottom": "16px"}
DD = {"display": "inline-block", "verticalAlign": "middle", "marginRight": "8px",
      "fontSize": "0.85rem"}
ROW = {"marginBottom": "8px", "display": "flex", "alignItems": "center",
       "flexWrap": "wrap", "rowGap": "8px"}
CHIP = {"display": "inline-block", "background": "#ccfbf1", "color": "#0f766e",
        "borderRadius": "999px", "padding": "3px 12px", "fontSize": "0.78rem",
        "marginRight": "6px", "cursor": "pointer", "fontWeight": 600}
CLICKABLE = {"cursor": "pointer", "textDecoration": "underline",
             "textDecorationStyle": "dotted", "textDecorationColor": "#94a3b8"}

LIBS = ["personnel", "equipment", "materials", "subcontracting"]
LIB_LABEL = {"personnel": "Personnel", "equipment": "Equipment",
             "materials": "Materials", "subcontracting": "Sub-contracting"}
LIB_OPTS = [{"label": LIB_LABEL[k], "value": k} for k in LIBS]
DIV_OPTS = [{"label": n, "value": c} for c, n in
            (("CIV", "Civil"), ("OFF", "Offshore"), ("HYD", "Hydropower"))]
REG_OPTS = [{"label": "ALL regions", "value": "ALL"}] + \
           [{"label": r, "value": r} for r in ("EUR", "WAF", "UAE", "SEA")]
OWN_OPTS = [{"label": "Internal", "value": "internal"},
            {"label": "External", "value": "external"}]
UNIT_OPTS = [{"label": u, "value": u} for u in
             ("day", "night", "week", "hour", "ton", "m3", "ticket", "lump")]
FILTER_FIELDS = ("category", "subcat", "ownership", "region", "unit")


def _cur_opts():
    return [{"label": c["code"], "value": c["code"]} for c in repo.list_currencies()]


def _is_lib_admin():
    user = auth.current_user()
    return bool(user and repo.is_lib_admin(user["email"], user.get("is_admin")))


def _all_items(rate_set_id):
    """All items of all four libraries, unified rows for the overview."""
    rows = []
    for lib in LIBS:
        for i in repo.list_items(lib, with_rates_for=rate_set_id):
            rows.append({
                "lib": lib, "uuid": i["uuid"], "code": i["code"],
                "description": i.get("description") or i.get("function") or "",
                "category": LIB_LABEL[lib],
                "subcat": i.get("category") or "",
                "ownership": i.get("ownership") or "internal",
                "region": i.get("region") or "ALL",
                "unit": i.get("unit") or "",
                "currency": i.get("currency") or "",
                "rate": i.get("rate"),
                "office_rate": i.get("office_rate"), "yard_rate": i.get("yard_rate"),
                "offshore_rate": i.get("offshore_rate"),
            })
    return sorted(rows, key=lambda r: r["code"])


def _numf(v):
    """Display-safe numeric: tolerates legacy ''/str values in the DB."""
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _rate_text(r):
    if r["lib"] == "personnel":
        vals = [_numf(r.get("office_rate")), _numf(r.get("yard_rate")),
                _numf(r.get("offshore_rate"))]
        if all(v is None for v in vals):
            return "\u2014"
        return " / ".join("\u2014" if v is None else f"{v:g}" for v in vals)
    v = _numf(r.get("rate"))
    return "\u2014" if v is None else f"{v:g}"


# --------------------------------------------------------------------------- #
# (4) unified overview with click-to-filter and inline edit
# --------------------------------------------------------------------------- #
def _flt_cell(field, value, row_uuid, shown=None):
    if not value:
        return ""
    return html.Span(shown or value,
                     id={"type": "cl-flt", "field": field, "value": str(value),
                         "u": row_uuid},                     # uuid keeps ids unique
                     n_clicks=0, style=CLICKABLE,
                     title=f"Click to filter on {shown or value}")


def _edit_row(r, cats_by_lib, td):
    """The selected row rendered as inline inputs (pattern IDs)."""
    u = r["uuid"]
    per = r["lib"] == "personnel"
    msc = r["lib"] in ("materials", "subcontracting")
    cells = [
        html.Td(html.Span(r["code"], style={"fontFamily": "ui-monospace,monospace",
                                            "fontWeight": 700}), style=td),
        html.Td(dcc.Input(id={"type": "cl-ed-desc", "u": u}, value=r["description"],
                          style={**SMALL, "width": "180px"}), style=td),
        html.Td(r["category"], style=td),
        html.Td(dcc.Dropdown(id={"type": "cl-ed-cat", "u": u},
                             options=cats_by_lib.get(r["lib"], []),
                             value=r["subcat"] or None, clearable=False,
                             style={"fontSize": "0.78rem", "width": "150px"})
                if msc else "", style=td),
        html.Td(dcc.Dropdown(id={"type": "cl-ed-own", "u": u}, options=OWN_OPTS,
                             value=r["ownership"] or "internal", clearable=False,
                             style={"fontSize": "0.78rem", "width": "110px"}),
                style=td),
        html.Td(dcc.Dropdown(id={"type": "cl-ed-reg", "u": u}, options=REG_OPTS,
                             value=r["region"], clearable=False,
                             style={"fontSize": "0.78rem", "width": "120px"}),
                style=td),
        html.Td(dcc.Dropdown(id={"type": "cl-ed-unit", "u": u}, options=UNIT_OPTS,
                             value=r["unit"] or "day", clearable=False,
                             style={"fontSize": "0.78rem", "width": "100px"}),
                style=td),
        html.Td(dcc.Dropdown(id={"type": "cl-ed-cur", "u": u}, options=_cur_opts(),
                             value=r["currency"] or "USD", clearable=False,
                             style={"fontSize": "0.78rem", "width": "85px"}),
                style=td),
    ]
    if per:
        cells.append(html.Td(html.Div([
            dcc.Input(id={"type": "cl-ed-off", "u": u}, type="number",
                      value=r["office_rate"], placeholder="Office",
                      style={**SMALL, "width": "72px", "marginRight": "3px"}),
            dcc.Input(id={"type": "cl-ed-yard", "u": u}, type="number",
                      value=r["yard_rate"], placeholder="Yard",
                      style={**SMALL, "width": "72px", "marginRight": "3px"}),
            dcc.Input(id={"type": "cl-ed-osh", "u": u}, type="number",
                      value=r["offshore_rate"], placeholder="Offsh.",
                      style={**SMALL, "width": "72px"}),
            html.Div(dcc.Input(id={"type": "cl-ed-rate", "u": u}, type="number"),
                     style={"display": "none"}),
        ], style={"whiteSpace": "nowrap"}), style=td))
    else:
        cells.append(html.Td(html.Div([
            dcc.Input(id={"type": "cl-ed-rate", "u": u}, type="number",
                      value=r["rate"], style={**SMALL, "width": "90px"}),
            html.Div([dcc.Input(id={"type": "cl-ed-off", "u": u}, type="number"),
                      dcc.Input(id={"type": "cl-ed-yard", "u": u}, type="number"),
                      dcc.Input(id={"type": "cl-ed-osh", "u": u}, type="number")],
                     style={"display": "none"}),
        ]), style=td))
    cells.append(html.Td(html.Div([
        html.Button("Save", id={"type": "cl-ed-save", "u": u}, n_clicks=0,
                    style={**BTN_OK, "padding": "5px 10px"}),
        html.Button("Cancel", id={"type": "cl-ed-cancel", "u": u}, n_clicks=0,
                    style=BTN_GHOST),
    ], style={"whiteSpace": "nowrap"}), style=td))
    return html.Tr(cells, style={"background": "#f0fdfa"})


def _overview(rate_set_id, filters, edit_uuid=None, status="",
              pending_delete=None):
    filters = filters or {}
    rows = _all_items(rate_set_id)
    for f, v in filters.items():
        rows = [r for r in rows if str(r.get(f) or "") == v]
    editable = _is_lib_admin()
    cats_by_lib = {
        "materials": [{"label": c["name"], "value": c["name"]}
                      for c in repo.list_misc_categories() if c["element"] == "materials"],
        "subcontracting": [{"label": c["name"], "value": c["name"]}
                           for c in repo.list_misc_categories()
                           if c["element"] == "subcontracting"],
    }
    th = {"textAlign": "left", "padding": "5px 8px", "fontSize": "0.75rem",
          "color": MUTED, "borderBottom": f"2px solid {LINE}"}
    td = {"padding": "5px 8px", "fontSize": "0.84rem", "verticalAlign": "middle"}
    chips = [html.Span(f"{f}: {v} \u2715", id={"type": "cl-chip", "field": f},
                       n_clicks=0, style=CHIP) for f, v in filters.items()]
    chip_bar = html.Div(chips or html.Span(
        "Tip: click a Category / Sub-category / Int-Ext / Region / Unit value to "
        "filter.", style={"color": MUTED, "fontSize": "0.78rem"}),
        style={"marginBottom": "8px"})
    body = []
    for r in rows:
        if editable and edit_uuid == r["uuid"]:
            body.append(_edit_row(r, cats_by_lib, td))
            continue
        cells = [
            html.Td(html.Span(r["code"], title=repo.code_label(r["code"]),
                              style={"fontFamily": "ui-monospace,monospace"}),
                    style=td),
            html.Td(r["description"], style=td),
            html.Td(_flt_cell("category", r["category"], r["uuid"]), style=td),
            html.Td(_flt_cell("subcat", r["subcat"], r["uuid"]), style=td),
            html.Td(_flt_cell("ownership", r["ownership"], r["uuid"]), style=td),
            html.Td(_flt_cell("region", r["region"], r["uuid"]), style=td),
            html.Td(_flt_cell("unit", r["unit"], r["uuid"]), style=td),
            html.Td(r["currency"], style=td),
            html.Td(_rate_text(r), style={**td, "whiteSpace": "nowrap"}),
        ]
        if editable:
            if pending_delete == r["uuid"]:
                actions = [
                    html.Span("Delete?", style={"color": RED, "fontWeight": 700,
                                                "fontSize": "0.78rem",
                                                "marginRight": "6px"}),
                    html.Button("Yes, delete", id={"type": "cl-delc", "u": r["uuid"],
                                                   "lib": r["lib"]}, n_clicks=0,
                                style={**BTN_GHOST, "background": RED,
                                       "color": "#fff", "border": "none",
                                       "fontWeight": 700}),
                    html.Button("Cancel", id={"type": "cl-delx", "u": r["uuid"]},
                                n_clicks=0, style=BTN_GHOST),
                ]
            else:
                actions = [
                    html.Button("Edit", id={"type": "cl-edit", "u": r["uuid"],
                                            "lib": r["lib"]}, n_clicks=0,
                                style=BTN_GHOST),
                    html.Button("Duplicate", id={"type": "cl-dup", "u": r["uuid"],
                                                 "lib": r["lib"]}, n_clicks=0,
                                style=BTN_GHOST),
                    html.Button("Delete", id={"type": "cl-del", "u": r["uuid"],
                                              "lib": r["lib"]}, n_clicks=0,
                                style={**BTN_GHOST, "color": RED,
                                       "border": "1px solid #fecaca"}),
                ]
            cells.append(html.Td(
                html.Div(actions, style={"display": "flex", "flexWrap": "nowrap",
                                         "alignItems": "center"}),
                style={**td, "whiteSpace": "nowrap", "minWidth": "215px"}))
        body.append(html.Tr(cells, style={"borderBottom": f"1px solid {LINE}"}))
    heads = ["Code", "Description", "Category", "Sub-category", "Int / Ext",
             "Region", "Unit", "Currency", "Rate (O/Y/Offsh for personnel)"]
    if editable:
        heads.append("")
    if not rows:
        table = html.P("No items match the current filters.", style={"color": MUTED})
    else:
        table = html.Table(
            [html.Thead(html.Tr([html.Th(h, style=th) for h in heads])),
             html.Tbody(body)],
            style={"borderCollapse": "collapse", "width": "100%"})
    return html.Div([
        html.Div([
            html.H4("Library overview", style={"marginTop": 0,
                                               "display": "inline-block",
                                               "marginRight": "16px"}),
            html.Button("Export Excel", id="cl-xlsx", n_clicks=0, style=BTN_GHOST),
        ]),
        chip_bar, table,
        html.Div(status, style={"fontSize": "0.83rem", "color": RED,
                                "marginTop": "6px", "minHeight": "1.1em"}),
    ])


# --------------------------------------------------------------------------- #
# (2) check-in form
# --------------------------------------------------------------------------- #
def _form_body(lib, division, prefill=None):
    """Form rows for a library+division. prefill (from Duplicate) pre-loads
    values; the ctx store carries lib/div so the top selectors are only a
    feeding mechanism, never a hidden dependency."""
    pf = prefill or {}
    cats = [c for c in repo.list_misc_categories()
            if repo.base_lib(lib)[1] in (None, c["element"])]
    cat_opts = [{"label": c["name"], "value": c["name"]} for c in cats]
    cp_opts = [{"label": f"{c['code']} \u00b7 {c['label']} ({c['division']}/{c['region']})",
                "value": c["uuid"]}
               for c in repo.counterpart_options(lib, division,
                                                 pf.get("region") or "ALL")]
    is_per = lib == "personnel"
    is_msc = lib in ("materials", "subcontracting")

    row1 = [dcc.Input(id="cl-req-desc", value=pf.get("description") or "",
                      placeholder=("Function (e.g. Diver) *" if is_per
                                   else "Description *"),
                      style={**FIELD, "width": "280px"})]
    if is_msc:
        row1.append(dcc.Dropdown(id="cl-req-cat", options=cat_opts,
                                 value=pf.get("subcat") or None,
                                 placeholder="Sub-category *",
                                 style={**DD, "width": "220px"}))
    else:
        row1.append(html.Div(dcc.Dropdown(id="cl-req-cat"), style={"display": "none"}))
    row1.append(dcc.Dropdown(id="cl-req-own", options=OWN_OPTS,
                             value=pf.get("ownership") or "internal",
                             clearable=False, style={**DD, "width": "140px"}))
    row1.append(dcc.Dropdown(id="cl-req-region", options=REG_OPTS,
                             value=pf.get("region") or None, placeholder="Region *",
                             style={**DD, "width": "150px"}))

    row2 = [dcc.Dropdown(id="cl-req-unit", options=UNIT_OPTS,
                         value=pf.get("unit") or "day", clearable=False,
                         style={**DD, "width": "110px"}),
            dcc.Dropdown(id="cl-req-cur", options=_cur_opts(),
                         value=pf.get("currency") or "USD", clearable=False,
                         style={**DD, "width": "110px"})]
    if is_per:
        row2 += [dcc.Input(id="cl-req-off", type="number", value=pf.get("office_rate", ""),
                           placeholder="Office rate", style={**FIELD, "width": "120px"}),
                 dcc.Input(id="cl-req-yard", type="number", value=pf.get("yard_rate", ""),
                           placeholder="Yard rate", style={**FIELD, "width": "120px"}),
                 dcc.Input(id="cl-req-osh", type="number",
                           value=pf.get("offshore_rate", ""),
                           placeholder="Offshore rate",
                           style={**FIELD, "width": "130px"}),
                 html.Span("at least one rate *",
                           style={"color": MUTED, "fontSize": "0.75rem"}),
                 html.Div(dcc.Input(id="cl-req-rate", type="number"),
                          style={"display": "none"})]
    else:
        row2 += [dcc.Input(id="cl-req-rate", type="number", value=pf.get("rate", ""),
                           placeholder="Rate *", style={**FIELD, "width": "130px"}),
                 html.Div([dcc.Input(id="cl-req-off", type="number"),
                           dcc.Input(id="cl-req-yard", type="number"),
                           dcc.Input(id="cl-req-osh", type="number")],
                          style={"display": "none"})]

    code = repo.suggest_code(lib, division,
                             ownership=pf.get("ownership") or "internal",
                             region=pf.get("region") or "ALL")
    row3 = [
        dcc.Dropdown(id="cl-req-cp", options=cp_opts,
                     placeholder="Counterpart elsewhere (reuses its number)\u2026",
                     style={**DD, "width": "380px"}),
        dcc.Input(id="cl-req-code", value=code, placeholder="Code",
                  style={**FIELD, "width": "160px",
                         "fontFamily": "ui-monospace,monospace"}),
        html.Span(repo.code_label(code), id="cl-code-label",
                  style={"color": TEAL, "fontSize": "0.8rem", "fontWeight": 600}),
    ]
    ctx_note = html.Span(f"\u2192 goes to: {LIB_LABEL[lib]} \u00b7 {division}"
                         + (" (duplicated item)" if prefill else ""),
                         style={"color": TEAL, "fontSize": "0.78rem",
                                "fontWeight": 600})
    return html.Div([
        dcc.Store(id="cl-form-ctx", data={"lib": lib, "division": division}),
        html.Div(row1 + [ctx_note], style=ROW),
        html.Div(row2, style=ROW), html.Div(row3, style=ROW),
        html.P("* required", style={"color": MUTED, "fontSize": "0.72rem",
                                    "margin": 0}),
    ])


# --------------------------------------------------------------------------- #
# (3) queue
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
            dup = repo.find_item_by_code(r["kind"][:-5], code=item.get("code"),
                                         erp_no=item.get("erp_no"))
        rates = "; ".join(
            (f"{x.get('office_rate')}/{x.get('yard_rate')}/{x.get('offshore_rate')}"
             if r["kind"] == "personnel_item" else f"{x.get('rate')}")
            + f" {x.get('currency', 'USD')}" for x in (p.get("rates") or []))
        warn = (html.Div(f"\u26a0 duplicate: {dup['code']} already exists - reject "
                         "this request.", style={"color": RED, "fontSize": "0.8rem",
                                                 "fontWeight": 600}) if dup else None)
        out.append(html.Div([
            html.Div([html.B(f"#{r['id']} \u00b7 {r['kind']} \u00b7 {r['division']} \u00b7 "
                             f"{item.get('code') or ''}"),
                      html.Span(f"  ({repo.code_label(item.get('code'))})" if
                                repo.code_label(item.get("code")) else "",
                                style={"color": TEAL, "fontSize": "0.8rem",
                                       "fontWeight": 600}),
                      html.Span(f"  by {r['submitted_by']} \u00b7 {r['submitted_at']}",
                                style={"color": MUTED, "fontSize": "0.8rem"})]),
            html.Div(f"{desc}  \u00b7  {item.get('region') or ''}",
                     style={"fontSize": "0.88rem", "margin": "3px 0"}),
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
    return html.Div(out, style=CARD)


# --------------------------------------------------------------------------- #
# layout - order: (1) selectors, (2) form, (3) queue, (4) overview
# --------------------------------------------------------------------------- #
def _safe(label, fn, *args, **kwargs):
    """Render one page section; on failure show an error card and log the
    traceback instead of letting the exception abort the whole page swap."""
    import traceback
    try:
        return fn(*args, **kwargs)
    except Exception:
        print(f"[calc_libraries] section '{label}' failed:", flush=True)
        traceback.print_exc()
        return html.Div([
            html.B(f"Section '{label}' could not be rendered."),
            html.Div("The error is logged in the container output "
                     "(Dokploy -> Logs). The rest of the page keeps working.",
                     style={"fontSize": "0.83rem"}),
        ], style={**CARD, "border": f"2px solid {RED}", "color": RED})


def layout(**_qs):
    user = auth.current_user()
    if not user:
        return html.Div()
    active = repo.active_rate_set()
    rs_id = active["id"] if active else None
    return html.Div(className="wide-page", children=[
        html.H3("Calculation libraries"),
        html.P("New items go through a check-in request; a library admin reviews "
               "before anything lands. The selectors below feed the request form. "
               "The overview at the bottom always shows the FULL library with the "
               "active rate set - click values in it to filter.",
               style={"color": MUTED, "maxWidth": "780px"}),

        # (1) selectors feeding the form
        html.Div([
            dcc.Dropdown(id="cl-lib", options=LIB_OPTS, value="personnel",
                         clearable=False, style={**DD, "width": "200px"}),
            dcc.Dropdown(id="cl-div", options=DIV_OPTS, value="OFF",
                         clearable=False, style={**DD, "width": "160px"}),
        ], style={"marginBottom": "10px"}),

        # (2) check-in form
        html.Div([
            html.H4("Check-in request \u2014 new item", style={"marginTop": 0}),
            html.Div(id="cl-form",
                     children=_safe("check-in form", _form_body, "personnel", "OFF")),
            html.Div(id="cl-dup-msg", style={"fontSize": "0.83rem", "color": RED,
                                             "minHeight": "1.1em", "fontWeight": 600}),
            html.Div([
                dcc.Input(id="cl-req-note", placeholder="Note to the reviewer (optional)",
                          style={**FIELD, "width": "420px"}),
                html.Button("Submit for review", id="cl-req-btn", n_clicks=0, style=BTN),
            ], style={**ROW, "marginTop": "6px"}),
            html.Div(id="cl-req-status", style={"fontSize": "0.85rem",
                                                "marginTop": "8px",
                                                "minHeight": "1.1em"}),
        ], style=CARD),

        # (3) queue (library admins)
        html.Div(id="cl-queue", children=_safe("check-in queue", _queue_body)),

        # (3b) currencies & FX (library admins)
        html.Div(id="cl-fx-wrap",
                 children=_safe("currencies & FX", _fx_card, rs_id)),

        # (4) unified overview
        dcc.Store(id="cl-filters", data={}),
        dcc.Download(id="cl-xlsx-dl"),
        dcc.Store(id="cl-edit-uuid", data=None),
        dcc.Store(id="cl-rsid", data=rs_id),
        html.Div(id="cl-table",
                 children=_safe("library overview", _overview, rs_id, {}),
                 style=CARD),
    ])


@callback(Output("cl-xlsx-dl", "data"),
          Input("cl-xlsx", "n_clicks"),
          State("cl-filters", "data"), State("cl-rsid", "data"),
          prevent_initial_call=True)
def _export_xlsx(n, filters, rs_id):
    if not n or not rs_id:
        raise PreventUpdate
    rs = repo.active_rate_set() or {}
    xb = excel_export.library_workbook_bytes(rs_id, rs.get("label", ""),
                                             filters or {})
    import datetime as _dt
    name = f"calc_library_{_dt.date.today().isoformat()}.xlsx"
    return dcc.send_bytes(lambda f: f.write(xb), name)


# --------------------------------------------------------------------------- #
# form callbacks
# --------------------------------------------------------------------------- #
@callback(Output("cl-form", "children"),
          Input("cl-lib", "value"), Input("cl-div", "value"),
          prevent_initial_call=True)
def _reshape(lib, division):
    if not (lib and division):
        raise PreventUpdate
    return _form_body(lib, division)


@callback(Output("cl-form", "children", allow_duplicate=True),
          Input({"type": "cl-dup", "u": ALL, "lib": ALL}, "n_clicks"),
          State("cl-rsid", "data"),
          prevent_initial_call=True)
def _duplicate(_clicks, rs_id):
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    if not _is_lib_admin():
        raise PreventUpdate
    r = next((x for x in _all_items(rs_id) if x["uuid"] == trig["u"]), None)
    if not r:
        raise PreventUpdate
    items = {i["uuid"]: i for i in repo.list_items(trig["lib"], active_only=False)}
    division = items[trig["u"]]["division"] if trig["u"] in items else "OFF"
    return _form_body(trig["lib"], division, prefill=r)


@callback(Output("cl-req-code", "value"),
          Input("cl-req-cp", "value"), Input("cl-req-own", "value"),
          Input("cl-req-region", "value"),
          State("cl-form-ctx", "data"),
          prevent_initial_call=True)
def _re_suggest(cp, own, region, fctx):
    fctx = fctx or {}
    return repo.suggest_code(fctx.get("lib", "personnel"), fctx.get("division", "OFF"),
                             ownership=own or "internal", region=region or "ALL",
                             counterpart_uuid=cp)


@callback(Output("cl-req-code", "style"),
          Output("cl-dup-msg", "children"), Output("cl-req-btn", "disabled"),
          Output("cl-req-btn", "style"), Output("cl-code-label", "children"),
          Input("cl-req-code", "value"),
          State("cl-form-ctx", "data"))
def _live_dup(code, fctx):
    code_style = {**FIELD, "width": "160px", "fontFamily": "ui-monospace,monospace"}
    msg, blocked = "", False
    lib = (fctx or {}).get("lib")
    if lib and code:
        d = repo.find_item_by_code(lib, code=code.strip())
        if d:
            code_style = {**FIELD_BAD, "width": "160px",
                          "fontFamily": "ui-monospace,monospace"}
            dd = d.get("description") or d.get("function") or ""
            msg = f"Code {d['code']} already exists ({dd})."
            blocked = True
    btn_style = {**BTN, "opacity": 0.4, "cursor": "not-allowed"} if blocked else BTN
    return code_style, msg, blocked, btn_style, repo.code_label((code or "").strip())


@callback(Output("cl-req-status", "children"),
          Output("cl-queue", "children", allow_duplicate=True),
          Output("cl-form", "children", allow_duplicate=True),
          Output("cl-req-note", "value"),
          Input("cl-req-btn", "n_clicks"),
          State("cl-form-ctx", "data"),
          State("cl-req-desc", "value"), State("cl-req-cat", "value"),
          State("cl-req-own", "value"), State("cl-req-region", "value"),
          State("cl-req-unit", "value"), State("cl-req-cur", "value"),
          State("cl-req-rate", "value"), State("cl-req-off", "value"),
          State("cl-req-yard", "value"), State("cl-req-osh", "value"),
          State("cl-req-code", "value"), State("cl-req-note", "value"),
          prevent_initial_call=True)
def _submit(n, fctx, desc, cat, own, region, unit, cur, rate, off, yard, osh,
            code, note):
    user = auth.current_user()
    if not n or not user or not fctx:
        return no_update, no_update, no_update, no_update
    lib, division = fctx["lib"], fctx["division"]
    is_per, is_msc = lib == "personnel", lib in ("materials", "subcontracting")
    rate, off, yard, osh = (_numf(v) for v in (rate, off, yard, osh))
    missing = []
    if not (desc or "").strip():
        missing.append("description/function")
    if not (code or "").strip():
        missing.append("code")
    if not region:
        missing.append("region")
    if not (cur or "").strip():
        missing.append("currency")
    if is_msc and not cat:
        missing.append("sub-category")
    if is_per:
        if not any(v is not None for v in (off, yard, osh)):
            missing.append("at least one rate (office/yard/offshore)")
    elif rate is None:
        missing.append("rate")
    if missing:
        return ("Required: " + ", ".join(missing) + ".",
                no_update, no_update, no_update)
    if repo.find_item_by_code(lib, code=code.strip()):
        return ("Duplicate code - see the message above.",
                no_update, no_update, no_update)
    item = {"code": code.strip(), "region": region, "unit": unit or "day",
            "ownership": own or "internal"}
    if is_per:
        item["function"] = desc.strip()
    else:
        item["description"] = desc.strip()
        if is_msc:
            item["category"] = cat
    rr = {"currency": cur.strip().upper()}
    if is_per:
        rr.update(office_rate=off, yard_rate=yard, offshore_rate=osh)
    else:
        rr.update(rate=rate)
    repo.submit_request(f"{lib}_item", division, {"item": item, "rates": [rr]},
                        user["email"], note=(note or "").strip() or None)
    # fresh, emptied form for the next entry (same lib/div)
    return (f"Submitted for review: {code.strip()}.", _queue_body(),
            _form_body(lib, division), "")


# --------------------------------------------------------------------------- #
# queue review -> refresh queue AND overview (the reported gap)
# --------------------------------------------------------------------------- #
@callback(Output("cl-queue", "children", allow_duplicate=True),
          Output("cl-table", "children", allow_duplicate=True),
          Input({"type": "cl-req-ok", "id": ALL}, "n_clicks"),
          Input({"type": "cl-req-no", "id": ALL}, "n_clicks"),
          State("cl-filters", "data"), State("cl-rsid", "data"),
          prevent_initial_call=True)
def _review(_ok, _no, filters, rs_id):
    if not _is_lib_admin():
        raise PreventUpdate
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    user = auth.current_user()
    repo.review_request(trig["id"], trig["type"] == "cl-req-ok", user["email"])
    return _queue_body(), _overview(rs_id, filters)


@callback(Output("cl-table", "children", allow_duplicate=True),
          Input({"type": "cl-del", "u": ALL, "lib": ALL}, "n_clicks"),
          Input({"type": "cl-delc", "u": ALL, "lib": ALL}, "n_clicks"),
          Input({"type": "cl-delx", "u": ALL}, "n_clicks"),
          State("cl-filters", "data"), State("cl-rsid", "data"),
          prevent_initial_call=True)
def _delete(_arm, _confirm, _cancel, filters, rs_id):
    """Two-step delete: first click arms the row ('Delete? Yes/Cancel'),
    the second actually deactivates. Any other rerender disarms."""
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    if not _is_lib_admin():
        raise PreventUpdate
    if trig["type"] == "cl-del":
        return _overview(rs_id, filters, pending_delete=trig["u"])
    if trig["type"] == "cl-delc":
        repo.deactivate_item(trig["lib"], trig["u"])
    return _overview(rs_id, filters)


# --------------------------------------------------------------------------- #
# currencies & FX (library admins; interim: live rates from the internet)
# --------------------------------------------------------------------------- #
def _fx_card(rs_id, status=""):
    if not _is_lib_admin():
        return html.Div()
    fx = repo.get_fx(rs_id) if rs_id else {}
    rows = []
    for c in repo.list_currencies():
        if c["code"] == "USD":
            cell = html.Td("1.000000", style={"padding": "4px 8px",
                                              "textAlign": "right",
                                              "fontFamily":
                                              "ui-monospace,monospace"})
        else:
            cell = html.Td(dcc.Input(
                id={"type": "cl-fxr", "cur": c["code"]}, type="number",
                value=fx.get(c["code"]),
                placeholder="\u2014", debounce=True,
                style={**SMALL, "width": "110px", "textAlign": "right"}),
                style={"padding": "4px 8px"})
        rows.append(html.Tr([
            html.Td(c["code"], style={"padding": "4px 8px",
                                      "fontFamily": "ui-monospace,monospace"}),
            html.Td(c["name"], style={"padding": "4px 8px"}),
            cell,
        ], style={"borderBottom": f"1px solid {LINE}"}))
    return html.Div([
        html.H4("Currencies & exchange rates (library admin)",
                style={"marginTop": 0}),
        html.P("Rate = 1 unit in USD, stored in the ACTIVE rate set and embedded in "
               "each calc at creation. Type directly in the table to set a rate "
               "manually (e.g. with a currency-risk margin); 'Fetch live rates' "
               "pulls current conversions from the internet.",
               style={"color": MUTED, "fontSize": "0.83rem"}),
        html.Table([html.Thead(html.Tr([html.Th(h, style={
            "textAlign": "left", "padding": "4px 8px", "fontSize": "0.75rem",
            "color": MUTED, "borderBottom": f"2px solid {LINE}"})
            for h in ("Code", "Name", "\u2192 USD")])), html.Tbody(rows)],
            style={"borderCollapse": "collapse", "minWidth": "380px"}),
        html.Div([
            dcc.Input(id="cl-fx-code", placeholder="New currency code (e.g. AED)",
                      style={**FIELD, "width": "220px"}),
            dcc.Input(id="cl-fx-name", placeholder="Name",
                      style={**FIELD, "width": "200px"}),
            html.Button("Add currency", id="cl-fx-add", n_clicks=0, style=BTN_GHOST),
            html.Span(" | ", style={"color": LINE}),
            dcc.Input(id="cl-fx-manual-cur", placeholder="Code",
                      style={**FIELD, "width": "90px", "marginLeft": "8px"}),
            dcc.Input(id="cl-fx-manual-rate", type="number",
                      placeholder="\u2192 USD", style={**FIELD, "width": "120px"}),
            html.Button("Set manually", id="cl-fx-set", n_clicks=0, style=BTN_GHOST),
            html.Button("Fetch live rates", id="cl-fx-live", n_clicks=0, style=BTN),
        ], style={**ROW, "marginTop": "10px"}),
        html.Div(status, style={"fontSize": "0.83rem", "marginTop": "6px",
                                "minHeight": "1.1em", "color": TEAL,
                                "fontWeight": 600}),
    ], style=CARD)


@callback(Output("cl-fx-wrap", "children"),
          Output("cl-form", "children", allow_duplicate=True),
          Input("cl-fx-add", "n_clicks"), Input("cl-fx-set", "n_clicks"),
          Input("cl-fx-live", "n_clicks"),
          State("cl-fx-code", "value"), State("cl-fx-name", "value"),
          State("cl-fx-manual-cur", "value"), State("cl-fx-manual-rate", "value"),
          State("cl-rsid", "data"), State("cl-form-ctx", "data"),
          prevent_initial_call=True)
def _fx(n_add, n_set, n_live, code, name, mcur, mrate, rs_id, fctx):
    if not _is_lib_admin() or not rs_id:
        raise PreventUpdate
    trig = ctx.triggered_id
    msg = ""
    if trig == "cl-fx-add" and n_add:
        if not code:
            msg = "Give the new currency a code."
        else:
            repo.add_currency(code.strip().upper(), (name or code).strip())
            msg = (f"{code.strip().upper()} added - set its rate manually or via "
                   "Fetch live rates. It is now in the currency dropdowns.")
    elif trig == "cl-fx-set" and n_set:
        if not (mcur and mrate):
            msg = "Currency code and rate are required."
        else:
            repo.add_currency(mcur.strip().upper(), mcur.strip().upper())
            repo.set_fx(rs_id, mcur.strip().upper(), float(mrate))
            msg = f"FX {mcur.strip().upper()} \u2192 USD = {mrate} saved."
    elif trig == "cl-fx-live" and n_live:
        updated, errors = repo.fetch_live_fx(rs_id)
        parts = []
        if updated:
            parts.append("Updated: " + ", ".join(
                f"{k}={v}" for k, v in sorted(updated.items())))
        parts += errors
        msg = "; ".join(parts) or "Nothing to update."
    fctx = fctx or {"lib": "personnel", "division": "OFF"}
    return (_fx_card(rs_id, status=msg),
            _form_body(fctx["lib"], fctx["division"]))


@callback(Output("cl-fx-wrap", "children", allow_duplicate=True),
          Input({"type": "cl-fxr", "cur": ALL}, "value"),
          State("cl-rsid", "data"),
          prevent_initial_call=True)
def _fx_manual(_vals, rs_id):
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or not _is_lib_admin() or not rs_id:
        raise PreventUpdate
    val = ctx.triggered[0]["value"]
    if val in (None, ""):
        raise PreventUpdate
    val = _numf(val)
    if val is None:
        raise PreventUpdate
    current = (repo.get_fx(rs_id) or {}).get(trig["cur"])
    if current is not None and abs(float(current) - float(val)) < 1e-12:
        raise PreventUpdate                     # no-op: don't rerender (loop guard)
    repo.set_fx(rs_id, trig["cur"], float(val))
    return _fx_card(rs_id, status=f"{trig['cur']} \u2192 USD = {val} saved (manual).")


# --------------------------------------------------------------------------- #
# overview: filters, edit, save
# --------------------------------------------------------------------------- #
@callback(Output("cl-filters", "data"),
          Output("cl-table", "children", allow_duplicate=True),
          Input({"type": "cl-flt", "field": ALL, "value": ALL, "u": ALL}, "n_clicks"),
          Input({"type": "cl-chip", "field": ALL}, "n_clicks"),
          State("cl-filters", "data"), State("cl-rsid", "data"),
          State("cl-edit-uuid", "data"),
          prevent_initial_call=True)
def _filter(_f, _c, filters, rs_id, edit_uuid):
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    filters = dict(filters or {})
    if trig["type"] == "cl-chip":
        filters.pop(trig["field"], None)
    else:
        filters[trig["field"]] = trig["value"]
    return filters, _overview(rs_id, filters, edit_uuid)


@callback(Output("cl-edit-uuid", "data"),
          Output("cl-table", "children", allow_duplicate=True),
          Input({"type": "cl-edit", "u": ALL, "lib": ALL}, "n_clicks"),
          Input({"type": "cl-ed-cancel", "u": ALL}, "n_clicks"),
          State("cl-filters", "data"), State("cl-rsid", "data"),
          prevent_initial_call=True)
def _edit_toggle(_e, _c, filters, rs_id):
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    if not _is_lib_admin():
        raise PreventUpdate
    if trig["type"] == "cl-ed-cancel":
        return None, _overview(rs_id, filters)
    return trig["u"], _overview(rs_id, filters, edit_uuid=trig["u"])


@callback(Output("cl-edit-uuid", "data", allow_duplicate=True),
          Output("cl-table", "children", allow_duplicate=True),
          Input({"type": "cl-ed-save", "u": ALL}, "n_clicks"),
          State({"type": "cl-ed-desc", "u": ALL}, "value"),
          State({"type": "cl-ed-cat", "u": ALL}, "value"),
          State({"type": "cl-ed-own", "u": ALL}, "value"),
          State({"type": "cl-ed-reg", "u": ALL}, "value"),
          State({"type": "cl-ed-unit", "u": ALL}, "value"),
          State({"type": "cl-ed-cur", "u": ALL}, "value"),
          State({"type": "cl-ed-rate", "u": ALL}, "value"),
          State({"type": "cl-ed-off", "u": ALL}, "value"),
          State({"type": "cl-ed-yard", "u": ALL}, "value"),
          State({"type": "cl-ed-osh", "u": ALL}, "value"),
          State("cl-filters", "data"), State("cl-rsid", "data"),
          prevent_initial_call=True)
def _edit_save(_s, descs, cats, owns, regs, units, curs, rates, offs, yards, oshs,
               filters, rs_id):
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    if not _is_lib_admin():
        raise PreventUpdate
    u = trig["u"]
    first = lambda lst: (lst or [None])[0]
    desc, cat, own = first(descs), first(cats), first(owns)
    region, unit, cur = first(regs), first(units), first(curs)
    rate, off, yard, osh = (_numf(first(x))
                            for x in (rates, offs, yards, oshs))

    lib = item = None
    for lb in LIBS:
        for i in repo.list_items(lb, active_only=False):
            if i["uuid"] == u:
                lib, item = lb, i
                break
        if item:
            break
    if not item:
        raise PreventUpdate
    if not (desc or "").strip():
        return no_update, _overview(rs_id, filters, edit_uuid=u,
                                    status="Description is required.")
    tbl = repo.base_lib(lib)[0]
    data = {"uuid": u, "division": item["division"], "erp_no": item.get("erp_no"),
            "region": region or "ALL", "unit": unit or "day"}
    data["ownership"] = own or "internal"
    if tbl == "personnel":
        data["function"] = desc.strip()
    else:
        data["description"] = desc.strip()
        if tbl == "misc":
            data["category"] = cat or item.get("category")
    # code letters follow ownership/region edits (collision-checked)
    parts = item["code"].split("-")
    if len(parts) == 5:
        parts[2] = repo.OWN_LETTER[own or "internal"]
        parts[3] = repo.REGION_LETTER.get(region or "ALL", "A")
        new_code = "-".join(parts)
        clash = repo.find_item_by_code(lib, code=new_code)
        if clash and clash["uuid"] != u:
            return no_update, _overview(
                rs_id, filters, edit_uuid=u,
                status=f"Change collides with existing {new_code}.")
        data["code"] = new_code
    else:
        data["code"] = item["code"]
    repo.upsert_item(lib, data)
    kw = ({"office_rate": off, "yard_rate": yard, "offshore_rate": osh}
          if tbl == "personnel" else {"rate": rate})
    if any(v is not None for v in kw.values()):
        repo.set_item_rate(lib, u, rs_id, (cur or "USD").strip().upper(), **kw)
    return None, _overview(rs_id, filters)
