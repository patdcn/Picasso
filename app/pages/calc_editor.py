"""
Calculation - Calculation editor (module v1, GRID format).

The agreed Excel/IBIS-style grid replaces the earlier panel editor. One
spreadsheet-like table over the full screen width:

  BOQ Code | Library Code | (ERP hidden) | Lvl | Description | Category |
  Remarks | Local/Foreign | Qty | Unit | O/Y/Offs | Unit Price | Item Price |
  Net Total | Markup

Two row kinds. LEVEL rows (chapters, level 1-5) carry the BOQ code, a level
qty multiplier and the Net Total; the harmonica arrow collapses their whole
subtree. ITEM rows live under a level: description with library type-ahead
(matching text links the line to the library and prefills code / category /
unit / price; anything else is free text with own category and price),
per-line Local/Foreign for the levies, O/Y/Offs for personnel, and a Markup
column prefilled from the element markups in the revision snapshot with a
per-line override. Building-block references render as item rows with
category "Building Block"; the blocks themselves are edited in their own
section below and every reference follows live.

Math (anchored against the agreed sheet): item price = unit price x qty;
level Net Total = (own item prices + child level Net Totals + refs) x level
qty - multipliers compound down the tree. All prices in USD via the
revision's embedded FX snapshot.

Everything stays journaled/undoable; locks, revisions, issue flow, exports
and the refresh-rates dialog carry over from the previous editor. "Apply
admin markups" mass-updates the element markups from the current active set
(explicit - the snapshot principle stays intact).
"""
import json

import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ALL, ctx
from dash.exceptions import PreventUpdate

from app import auth
from app.calcmod import repo, engine, qcalc_io, excel_export

dash.register_page(__name__, path="/calculation/editor", name="Calculation editor",
                   title="Calculation editor", category="Calculation", order=3)

MODULE = "/calculation/editor"

INK, MUTED, TEAL, LINE, RED = "#1f2937", "#6b7280", "#0f766e", "#e5e7eb", "#b91c1c"
LVL_BG = {1: "#fecdd3", 2: "#e5e7eb", 3: "#d1d5db", 4: "#e7e5e4", 5: "#f5f5f4"}
BTN = {"padding": "7px 12px", "borderRadius": "8px", "border": "none",
       "background": TEAL, "color": "#fff", "fontWeight": 600, "cursor": "pointer",
       "fontSize": "0.8rem", "marginRight": "6px"}
BTN_GHOST = {"padding": "6px 10px", "borderRadius": "8px",
             "border": f"1px solid {LINE}", "background": "#fff", "color": INK,
             "cursor": "pointer", "fontSize": "0.78rem", "marginRight": "6px"}
BTN_MINI = {"padding": "1px 7px", "borderRadius": "6px",
            "border": f"1px solid {LINE}", "background": "#fff", "cursor": "pointer",
            "fontSize": "0.72rem", "marginRight": "3px", "color": INK}
CARD = {"background": "#fff", "border": f"1px solid {LINE}", "borderRadius": "12px",
        "padding": "14px 16px", "marginBottom": "14px"}
CELL_IN = {"width": "100%", "border": "1px solid transparent", "borderRadius": "4px",
           "padding": "2px 4px", "fontSize": "0.8rem", "background": "transparent",
           "boxSizing": "border-box"}
NUM_IN = {**CELL_IN, "textAlign": "right"}
DDS = {"fontSize": "0.75rem"}

ELEMENT_LABEL = {"labor": "Labour", "equipment": "Equipment",
                 "materials": "Materials", "subcontracting": "Sub-contracting"}
BASIS_OPTS = [{"label": "O", "value": "office"}, {"label": "Y", "value": "yard"},
              {"label": "Offs", "value": "offshore"}]
ORIGIN_OPTS = [{"label": "Local", "value": "local"},
               {"label": "Foreign", "value": "expat"}]
UNIT_OPTS = ["day", "night", "week", "hour", "each", "lump", "ton", "m3",
             "liter", "ticket", "rolls"]
MAX_DEPTH = 5


def _user():
    return auth.current_user()


def _ctx(q, rev_no):
    user = _user()
    calc = repo.get_calc(q) if q else None
    if not (user and calc):
        return None
    rev = repo.get_revision(q, int(rev_no) if rev_no not in (None, "") else None)
    if not rev:
        return None
    g = repo.get_grant(user["email"], calc["division"])
    may_edit = bool(user.get("is_admin") or (g and g["level"] == "edit"))
    editable = may_edit and rev["status"] == "working"
    lock_ok = False
    if editable:
        lock_ok, _holder = repo.acquire_lock(q, user["email"])
    return {"user": user, "calc": calc, "rev": rev, "may_edit": may_edit,
            "editable": editable and lock_ok, "lock_ok": lock_ok}


def _fmt(v):
    return f"{v:,.2f}"


def _num(v, default=None):
    if v in (None, ""):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# library option map for the description type-ahead
# --------------------------------------------------------------------------- #
def _lib_options(calc):
    """[{label, lib, uuid, item}] for the calc's division+region; the label is
    what appears in the datalist and what an exact match links on."""
    out = []
    for lib in ("personnel", "equipment", "materials", "subcontracting"):
        for it in repo.list_items(lib, calc["division"], calc_region=calc["region"]):
            desc = it.get("description") or it.get("function") or ""
            out.append({"label": f"{it['code']} \u00b7 {desc}", "lib": lib,
                        "uuid": it["uuid"], "desc": desc, "item": it})
    return out


def _cat_options():
    opts = [{"label": "Labour", "value": "labor|"},
            {"label": "Equipment", "value": "equipment|"}]
    for c in repo.list_misc_categories():
        el = "Materials" if c["element"] == "materials" else "Sub-contracting"
        val = ("materials" if c["element"] == "materials" else "subcontracting")
        opts.append({"label": f"{el} / {c['name']}", "value": f"{val}|{c['name']}"})
    return opts


# --------------------------------------------------------------------------- #
# grid rendering
# --------------------------------------------------------------------------- #
HEADS = ["BOQ Code", "Library Code", "Lvl", "Description", "Category", "Remarks",
         "Local / Foreign", "Qty", "Unit", "O/Y/Offs", "Unit Price",
         "Item Price", "Net Total", "Markup %", ""]
COL_W = ["96px", "120px", "34px", "300px", "170px", "170px", "92px", "64px",
         "84px", "72px", "90px", "100px", "110px", "72px", "150px"]


def _th():
    return html.Tr([html.Th(h, style={"textAlign": "left", "padding": "6px 6px",
                                      "fontSize": "0.72rem", "color": MUTED,
                                      "borderBottom": f"2px solid {LINE}",
                                      "width": w, "position": "sticky", "top": 0,
                                      "background": "#fff", "zIndex": 2})
                    for h, w in zip(HEADS, COL_W)])


def _td(child, extra=None, right=False):
    st = {"padding": "2px 5px", "fontSize": "0.8rem", "verticalAlign": "middle",
          "borderBottom": f"1px solid {LINE}"}
    if right:
        st["textAlign"] = "right"
    if extra:
        st.update(extra)
    return html.Td(child, style=st)


def _line_row(ln, snap, g, ed, cat_opts):
    """One ITEM row."""
    lid = ln["id"]
    item = snap["items"].get(ln.get("snap_item_id")) if ln.get("snap_item_id") else None
    gl = g["lines"][lid]
    lib_code = item["code"] if item else ""
    is_per = bool(item and item["lib"] == "personnel")
    # category cell
    if item:
        cat_txt = ELEMENT_LABEL.get(ln["element"], ln["element"])
        sub = ln.get("subcat") or (item.get("category") if item else None)
        cat_cell = (cat_txt + (f" / {sub}" if sub else ""))
    elif ed:
        cur = f"{ln['element']}|{ln.get('subcat') or ''}"
        cat_cell = dcc.Dropdown(id={"t": "ge", "f": "cat", "id": lid},
                                options=cat_opts, value=cur, clearable=False,
                                style=DDS)
    else:
        sub = ln.get("subcat")
        cat_cell = ELEMENT_LABEL.get(ln["element"], "") + (f" / {sub}" if sub else "")
    # unit cell
    unit_val = (item.get("unit") if item else ln.get("unit")) or ""
    if item or not ed:
        unit_cell = unit_val
    else:
        uopts = [{"label": u, "value": u} for u in
                 dict.fromkeys(UNIT_OPTS + ([unit_val] if unit_val else []))]
        unit_cell = dcc.Dropdown(id={"t": "ge", "f": "unitf", "id": lid},
                                 options=uopts, value=unit_val or "day",
                                 clearable=False, style=DDS)
    # O/Y/Offs
    if is_per:
        basis_cell = dcc.Dropdown(id={"t": "ge", "f": "basis", "id": lid},
                                  options=BASIS_OPTS,
                                  value=ln.get("rate_basis") or "offshore",
                                  clearable=False, style=DDS) if ed else \
            {"office": "O", "yard": "Y", "offshore": "Offs"}.get(
                ln.get("rate_basis") or "offshore", "")
    else:
        basis_cell = ""
    # unit price
    if item and ln.get("unit_rate_override") is None:
        up_cell = html.Span(_fmt(gl["unit_price"]),
                            title=f"library rate ({gl['currency']})")
    elif ed:
        up_cell = dcc.Input(id={"t": "ge", "f": "uprice", "id": lid}, type="number",
                            value=ln.get("unit_rate_override"), debounce=True,
                            style=NUM_IN)
    else:
        up_cell = _fmt(gl["unit_price"])
    # markup: override or element default (placeholder)
    default_pct = engine.line_markup_pct({**ln, "markup_override": None}, snap) * 100
    mk_val = "" if ln.get("markup_override") is None \
        else round(float(ln["markup_override"]) * 100, 4)
    mk_cell = html.Span(dcc.Input(id={"t": "ge", "f": "markup", "id": lid},
                                  type="number", value=mk_val,
                                  placeholder=f"{default_pct:g}",
                                  debounce=True, style=NUM_IN),
                        title="Element default from admin; type to override, "
                              "clear to fall back") if ed else \
        f"{engine.line_markup_pct(ln, snap) * 100:g}"
    desc_val = ln.get("description") or (item.get("description") if item else "") or ""
    cells = [
        _td(""),                                                    # BOQ
        _td(html.Span(lib_code, title=repo.code_label(lib_code),
                      style={"fontFamily": "ui-monospace,monospace",
                             "fontSize": "0.74rem"})),
        _td(""),                                                    # Lvl
        _td(dcc.Input(id={"t": "ge", "f": "desc", "id": lid}, value=desc_val,
                      debounce=True, list="ce-datalist",
                      style={**CELL_IN, "border": f"1px solid {LINE}"})
            if ed else desc_val),
        _td(cat_cell),
        _td(dcc.Input(id={"t": "ge", "f": "remarks", "id": lid},
                      value=ln.get("remarks") or "", debounce=True, style=CELL_IN)
            if ed else (ln.get("remarks") or "")),
        _td(dcc.Dropdown(id={"t": "ge", "f": "origin", "id": lid},
                         options=ORIGIN_OPTS, value=ln.get("origin") or "local",
                         clearable=False, style=DDS) if ed else
            ("Local" if (ln.get("origin") or "local") == "local" else "Foreign")),
        _td(dcc.Input(id={"t": "ge", "f": "qty", "id": lid}, type="number",
                      value=ln.get("qty"), debounce=True, style=NUM_IN)
            if ed else f"{ln.get('qty'):g}", right=True),
        _td(unit_cell),
        _td(basis_cell),
        _td(up_cell, right=True),
        _td(_fmt(gl["item_price"]), right=True),
        _td(""),                                                    # Net
        _td(mk_cell, right=True),
        _td(html.Button("\u2715", id={"t": "ga", "a": "delline", "b": lid},
                        n_clicks=0, title="Delete line", style=BTN_MINI)
            if ed else ""),
    ]
    return html.Tr(cells)


def _ref_row(rf, blocks, g, ed):
    """A building-block reference rendered as an item row."""
    rid = rf["id"]
    refb = blocks[rf["ref_block_id"]]
    net = g["blocks"][rf["ref_block_id"]]["net"]
    cells = [
        _td(""),
        _td(html.Span("BB", style={"fontFamily": "ui-monospace,monospace",
                                   "fontSize": "0.74rem", "color": TEAL})),
        _td(""),
        _td(html.Span(refb["name"], style={"fontStyle": "italic"})),
        _td(html.Span("Building Block", style={"color": TEAL, "fontWeight": 600})),
        _td(""), _td(""),
        _td(dcc.Input(id={"t": "ge", "f": "refqty", "id": rid}, type="number",
                      value=rf["qty"], debounce=True, style=NUM_IN)
            if ed else f"{rf['qty']:g}", right=True),
        _td(refb.get("unit_label") or ""),
        _td(""),
        _td(_fmt(net), right=True),
        _td(_fmt(net * float(rf["qty"])), right=True),
        _td(""), _td(""),
        _td(html.Button("\u2715", id={"t": "ga", "a": "delref", "b": rid},
                        n_clicks=0, title="Remove reference", style=BTN_MINI)
            if ed else ""),
    ]
    return html.Tr(cells, style={"background": "#f0fdfa"})


def _level_row(b, depth, boq, g, ed, collapsed, armed, bb_opts, bb_mode=False):
    bid = b["id"]
    gb = g["blocks"][bid]
    bg = LVL_BG.get(depth, "#f5f5f4") if not bb_mode else "#ccfbf1"
    arrow = "\u25b8" if bid in collapsed else "\u25be"
    if armed == bid and ed:
        actions = [html.Span("Delete level + contents?",
                             style={"color": RED, "fontWeight": 700,
                                    "fontSize": "0.72rem", "marginRight": "4px"}),
                   html.Button("Yes", id={"t": "ga", "a": "delblk2", "b": bid},
                               n_clicks=0, style={**BTN_MINI, "background": RED,
                                                  "color": "#fff", "border": "none"}),
                   html.Button("No", id={"t": "ga", "a": "delcancel", "b": bid},
                               n_clicks=0, style=BTN_MINI)]
    elif ed:
        actions = [html.Button("+item", id={"t": "ga", "a": "item", "b": bid},
                               n_clicks=0, title="Add item line", style=BTN_MINI)]
        if depth < MAX_DEPTH:
            actions.append(html.Button("+lvl", id={"t": "ga", "a": "sub", "b": bid},
                                       n_clicks=0, title="Add sub-level",
                                       style=BTN_MINI))
        if bb_opts and not bb_mode:
            actions.append(html.Button("+BB", id={"t": "ga", "a": "refmenu", "b": bid},
                                       n_clicks=0, title="Insert building-block "
                                       "reference", style=BTN_MINI))
        actions.append(html.Button("\u2715", id={"t": "ga", "a": "delblk", "b": bid},
                                   n_clicks=0, title="Delete level", style=BTN_MINI))
    else:
        actions = []
    cells = [
        _td(html.Div([
            html.Button(arrow, id={"t": "gc", "b": bid}, n_clicks=0,
                        style={"border": "none", "background": "transparent",
                               "cursor": "pointer", "fontSize": "0.8rem",
                               "padding": "0 4px 0 0"}),
            html.B(boq, style={"fontFamily": "ui-monospace,monospace",
                               "fontSize": "0.76rem"}),
        ], style={"whiteSpace": "nowrap"})),
        _td(""),
        _td(html.B(depth if not bb_mode else "BB")),
        _td(dcc.Input(id={"t": "ge", "f": "bname", "id": bid}, value=b["name"],
                      debounce=True,
                      style={**CELL_IN, "fontWeight": 700,
                             "paddingLeft": f"{(depth - 1) * 14}px"})
            if ed else html.B(b["name"], style={"paddingLeft":
                                                f"{(depth - 1) * 14}px"})),
        _td(""),
        _td(dcc.Input(id={"t": "ge", "f": "bnotes", "id": bid},
                      value=b.get("notes") or "", debounce=True, style=CELL_IN)
            if ed else (b.get("notes") or "")),
        _td(""),
        _td(dcc.Input(id={"t": "ge", "f": "bqty", "id": bid}, type="number",
                      value=b.get("qty") or 1, debounce=True,
                      style={**NUM_IN, "fontWeight": 700})
            if ed else f"{b.get('qty') or 1:g}", right=True),
        _td(""), _td(""), _td(""),
        _td(_fmt(gb["items"]) if gb["items"] else "", right=True),
        _td(html.B(_fmt(gb["net"])), right=True),
        _td(""),
        _td(html.Div(actions, style={"whiteSpace": "nowrap"})),
    ]
    return html.Tr(cells, style={"background": bg})


def _grid(cx, collapsed=None, armed=None, refmenu=None):
    """Render the whole grid: master BOQ + building-blocks section."""
    collapsed = set(collapsed or [])
    tree = repo.get_tree(cx["rev"]["id"])
    snap = repo.load_snapshot(cx["rev"]["id"])
    g = engine.grid(tree, snap)
    ed = cx["editable"]
    blocks = {b["id"]: b for b in tree["blocks"]}
    lines_by_block, refs_by_host, children = {}, {}, {}
    for ln in tree["lines"]:
        lines_by_block.setdefault(ln["block_id"], []).append(ln)
    for r in tree["refs"]:
        refs_by_host.setdefault(r["host_block_id"], []).append(r)
    for b in tree["blocks"]:
        if b["parent_id"] and b["kind"] == "package":
            children.setdefault(b["parent_id"], []).append(b)
    for v in children.values():
        v.sort(key=lambda x: (x["sort_order"], x["id"]))
    master = next((b for b in tree["blocks"] if b["kind"] == "master"), None)
    bblocks = sorted([b for b in tree["blocks"] if b["kind"] == "block"],
                     key=lambda x: (x["sort_order"], x["id"]))
    bb_opts = [{"label": b["name"], "value": b["id"]} for b in bblocks]
    cat_opts = _cat_options()
    lib_opts = _lib_options(cx["calc"])

    rows = []

    def emit_block(b, depth, positions, bb_mode=False):
        boq = ".".join(str(p) for p in (positions + [0] * (MAX_DEPTH - len(positions)))) \
            if not bb_mode else f"BB-{positions[0]}"
        rows.append(_level_row(b, depth, boq, g, ed, collapsed, armed, bb_opts,
                               bb_mode))
        if refmenu == b["id"] and ed and bb_opts:
            rows.append(html.Tr([html.Td(html.Div([
                html.Span("Insert building block: ",
                          style={"fontSize": "0.78rem", "color": MUTED}),
                dcc.Dropdown(id={"t": "ge", "f": "addref", "id": b["id"]},
                             options=bb_opts, placeholder="choose block\u2026",
                             style={**DDS, "width": "320px",
                                    "display": "inline-block",
                                    "verticalAlign": "middle"}),
            ]), colSpan=len(HEADS),
                style={"padding": "4px 8px", "background": "#f0fdfa"})]))
        if b["id"] in collapsed:
            return
        for ln in sorted(lines_by_block.get(b["id"], []),
                         key=lambda x: (x["sort_order"], x["id"])):
            rows.append(_line_row(ln, snap, g, ed, cat_opts))
        for rf in sorted(refs_by_host.get(b["id"], []),
                         key=lambda x: (x["sort_order"], x["id"])):
            if rf["ref_block_id"] in blocks:
                rows.append(_ref_row(rf, blocks, g, ed))
        for i, kid in enumerate(children.get(b["id"], []), start=1):
            emit_block(kid, depth + 1, positions + [i], bb_mode)

    if master:
        for i, kid in enumerate(children.get(master["id"], []), start=1):
            emit_block(kid, 1, [i])
    add_bar = html.Div([
        html.Button("+ Level-1 chapter", id="ce-add-l1", n_clicks=0, style=BTN_GHOST),
    ], style={"margin": "8px 0"}) if ed else html.Div()

    # building blocks section
    bb_rows = []
    for i, bb in enumerate(bblocks, start=1):
        emit_target = len(rows)
        emit_block(bb, 1, [i], bb_mode=True)
        bb_rows.extend(rows[emit_target:])
        del rows[emit_target:]
    bb_bar = html.Div([
        dcc.Input(id="ce-bb-name", placeholder="New building block name",
                  value="", debounce=False,
                  style={"padding": "6px 9px", "borderRadius": "8px",
                         "border": f"1px solid {LINE}", "fontSize": "0.8rem",
                         "marginRight": "8px", "width": "280px"}),
        html.Button("+ Building block", id="ce-bb-add", n_clicks=0, style=BTN_GHOST),
    ], style={"margin": "8px 0"}) if ed else html.Div()

    master_g = g["blocks"].get(master["id"]) if master else None
    totals_bar = html.Div([
        html.Span("Net total: ", style={"color": MUTED}),
        html.B(_fmt(master_g["net"]) if master_g else "0.00",
               style={"marginRight": "18px"}),
        html.Span("Sell total (incl. markups): ", style={"color": MUTED}),
        html.B(_fmt(master_g["net_sell"]) if master_g else "0.00",
               style={"color": TEAL}),
        html.Span("  \u00b7 USD", style={"color": MUTED, "fontSize": "0.78rem"}),
    ], style={"fontSize": "0.95rem", "margin": "2px 0 10px"})

    datalist = html.Datalist(id="ce-datalist",
                             children=[html.Option(value=o["label"])
                                       for o in lib_opts])
    table = html.Table([html.Thead(_th()), html.Tbody(rows)],
                       style={"borderCollapse": "collapse", "width": "100%",
                              "tableLayout": "fixed"})
    bb_section = html.Div([
        html.H4("Building blocks", style={"margin": "18px 0 4px"}),
        html.P("Sub-calculations you can reference from the BOQ above (category "
               "'Building Block'). Edit a block here and every reference follows.",
               style={"color": MUTED, "fontSize": "0.8rem", "margin": "0 0 6px"}),
        (html.Table([html.Thead(_th()), html.Tbody(bb_rows)],
                    style={"borderCollapse": "collapse", "width": "100%",
                           "tableLayout": "fixed"})
         if bb_rows else html.P("No building blocks yet.",
                                style={"color": MUTED, "fontSize": "0.8rem"})),
        bb_bar,
    ])
    return html.Div([datalist, totals_bar, table, add_bar, bb_section], style=CARD)


# --------------------------------------------------------------------------- #
# header
# --------------------------------------------------------------------------- #
def _header(cx):
    calc, rev = cx["calc"], cx["rev"]
    revs = repo.get_revisions(calc["qnumber"])
    rev_opts = [{"label": f"Rev {r['rev_no']} \u00b7 {r['status']}", "value": r["rev_no"]}
                for r in revs]
    lock_badge = None
    if rev["status"] == "working" and cx["may_edit"] and not cx["lock_ok"]:
        st = repo.lock_status(calc["qnumber"])
        lock_badge = html.Span(f"\U0001f512 locked by {st['user']} \u2014 read-only, "
                               "live view",
                               style={"background": "#fee2e2", "borderRadius": "6px",
                                      "padding": "3px 10px", "fontSize": "0.78rem",
                                      "marginLeft": "10px"})
    status_badge = html.Span(rev["status"], style={
        "background": "#dcfce7" if rev["status"] == "issued" else "#fef9c3",
        "borderRadius": "6px", "padding": "3px 10px", "fontSize": "0.78rem",
        "marginLeft": "10px"})
    ed = cx["editable"]
    btns = [
        html.Button("Undo", id="ce-undo", n_clicks=0, style=BTN_GHOST, disabled=not ed),
        html.Button("Refresh rates\u2026", id="ce-refresh-open", n_clicks=0,
                    style=BTN_GHOST, disabled=not ed),
        html.Button("Apply admin markups", id="ce-apply-markups", n_clicks=0,
                    style=BTN_GHOST, disabled=not ed,
                    title="Copy the element markups of the current active rate set "
                          "into this revision (lines with an override keep it)"),
        html.Button("Issue this revision", id="ce-issue", n_clicks=0, style=BTN_GHOST,
                    disabled=not ed),
        html.Button("New revision", id="ce-newrev", n_clicks=0, style=BTN_GHOST,
                    disabled=not cx["may_edit"]),
        html.Button("Export .qcalc", id="ce-exp-qcalc", n_clicks=0, style=BTN_GHOST),
        html.Button("Export Excel", id="ce-exp-xlsx", n_clicks=0, style=BTN_GHOST),
    ]
    return html.Div([
        html.Div([
            html.H3(f"{calc['qnumber']} \u2014 {calc['title']}",
                    style={"display": "inline-block", "margin": 0}),
            status_badge, lock_badge,
        ]),
        html.Div([
            html.Span(f"{calc['division']} \u00b7 {calc['region']} \u00b7 rate set "
                      f"{rev.get('rate_set_label') or '-'}",
                      style={"color": MUTED, "fontSize": "0.82rem",
                             "marginRight": "16px"}),
            dcc.Dropdown(id="ce-rev-select", options=rev_opts, value=rev["rev_no"],
                         clearable=False, style={"width": "170px",
                                                 "display": "inline-block",
                                                 "verticalAlign": "middle",
                                                 "marginRight": "12px",
                                                 "fontSize": "0.8rem"}),
            *btns,
        ], style={"marginTop": "8px"}),
        html.Div(id="ce-header-status", style={"fontSize": "0.82rem",
                                               "marginTop": "6px",
                                               "minHeight": "1.1em"}),
    ], style=CARD)


# --------------------------------------------------------------------------- #
# layout
# --------------------------------------------------------------------------- #
def layout(q=None, rev=None, **_qs):
    user = _user()
    if not user:
        return html.Div()
    if not q or not repo.get_calc(q):
        return html.Div([
            html.H3("Calculation editor"),
            html.P(["No calculation selected. Open one from the ",
                    dcc.Link("DCN Calculations", href="/calculation/calcs",
                             style={"color": TEAL, "fontWeight": 600}), " overview."],
                   style={"color": MUTED}),
        ])
    cx = _ctx(q, rev)
    if not cx:
        return html.Div(html.P("Revision not found.", style={"color": MUTED}))
    return html.Div(className="wide-page", children=[
        dcc.Store(id="ce-q", data=q),
        dcc.Store(id="ce-rev", data=cx["rev"]["rev_no"]),
        dcc.Store(id="ce-collapsed", data=[]),
        dcc.Store(id="ce-delarm", data=None),
        dcc.Store(id="ce-refmenu", data=None),
        dcc.Store(id="ce-lastseq", data=repo.last_seq(cx["rev"]["id"])),
        dcc.Interval(id="ce-poll", interval=3000, disabled=cx["editable"]),
        dcc.Interval(id="ce-heartbeat", interval=60000, disabled=not cx["editable"]),
        dcc.Download(id="ce-download"),
        html.Div(id="ce-header", children=_header(cx)),
        html.Div(id="ce-grid", children=_grid(cx)),
        html.Div(id="ce-refresh-modal", style={"display": "none"}),
    ])


def _guard(q, rev_no):
    cx = _ctx(q, rev_no)
    if not cx or not cx["editable"]:
        raise PreventUpdate
    return cx


# --------------------------------------------------------------------------- #
# polling / heartbeat / revision switching
# --------------------------------------------------------------------------- #
@callback(Output("ce-lastseq", "data"),
          Output("ce-header", "children", allow_duplicate=True),
          Output("ce-grid", "children", allow_duplicate=True),
          Input("ce-poll", "n_intervals"),
          State("ce-q", "data"), State("ce-rev", "data"),
          State("ce-collapsed", "data"), State("ce-lastseq", "data"),
          prevent_initial_call=True)
def _poll(_n, q, rev_no, collapsed, seen):
    cx = _ctx(q, rev_no)
    if not cx:
        raise PreventUpdate
    seq = repo.last_seq(cx["rev"]["id"])
    if seq == seen:
        raise PreventUpdate
    return seq, _header(cx), _grid(cx, collapsed)


@callback(Output("ce-heartbeat", "disabled"),
          Input("ce-heartbeat", "n_intervals"),
          State("ce-q", "data"), prevent_initial_call=True)
def _beat(_n, q):
    user = _user()
    if user and q:
        repo.heartbeat_lock(q, user["email"])
    return False


@callback(Output("ce-rev", "data"),
          Output("ce-header", "children", allow_duplicate=True),
          Output("ce-grid", "children", allow_duplicate=True),
          Output("ce-poll", "disabled"),
          Input("ce-rev-select", "value"),
          State("ce-q", "data"), prevent_initial_call=True)
def _switch_rev(rev_no, q):
    cx = _ctx(q, rev_no)
    if not cx:
        raise PreventUpdate
    return rev_no, _header(cx), _grid(cx), cx["editable"]


# --------------------------------------------------------------------------- #
# header actions
# --------------------------------------------------------------------------- #
@callback(Output("ce-header", "children", allow_duplicate=True),
          Output("ce-grid", "children", allow_duplicate=True),
          Input("ce-undo", "n_clicks"),
          State("ce-q", "data"), State("ce-rev", "data"),
          State("ce-collapsed", "data"),
          prevent_initial_call=True)
def _undo(n, q, rev_no, collapsed):
    if not n:
        raise PreventUpdate
    cx = _guard(q, rev_no)
    repo.undo_last(cx["rev"]["id"], cx["user"]["email"])
    return _header(cx), _grid(cx, collapsed)


@callback(Output("ce-header-status", "children"),
          Output("ce-grid", "children", allow_duplicate=True),
          Input("ce-apply-markups", "n_clicks"),
          State("ce-q", "data"), State("ce-rev", "data"),
          State("ce-collapsed", "data"),
          prevent_initial_call=True)
def _apply_markups(n, q, rev_no, collapsed):
    if not n:
        raise PreventUpdate
    cx = _guard(q, rev_no)
    err = repo.apply_admin_markups(cx["rev"]["id"], q, cx["user"]["email"])
    msg = err or ("Element markups updated from the active rate set "
                  "(overridden lines kept their value). Undoable.")
    return msg, _grid(cx, collapsed)


@callback(Output("ce-header-status", "children", allow_duplicate=True),
          Output("ce-header", "children", allow_duplicate=True),
          Input("ce-issue", "n_clicks"),
          State("ce-q", "data"), State("ce-rev", "data"),
          prevent_initial_call=True)
def _issue(n, q, rev_no):
    if not n:
        raise PreventUpdate
    cx = _guard(q, rev_no)
    repo.issue_revision(q, cx["rev"]["rev_no"], cx["user"]["email"])
    repo.release_lock(q, cx["user"]["email"])
    cx = _ctx(q, rev_no)
    return (f"Rev {rev_no} issued - it is now immutable. Amend via a new revision.",
            _header(cx))


@callback(Output("ce-header-status", "children", allow_duplicate=True),
          Output("ce-header", "children", allow_duplicate=True),
          Input("ce-newrev", "n_clicks"),
          State("ce-q", "data"), prevent_initial_call=True)
def _newrev(n, q):
    if not n:
        raise PreventUpdate
    user = _user()
    calc = repo.get_calc(q)
    g = repo.get_grant(user["email"], calc["division"]) if (user and calc) else None
    if not (user and (user.get("is_admin") or (g and g["level"] == "edit"))):
        raise PreventUpdate
    latest = repo.get_revision(q)
    if latest["status"] == "working":
        return ("The latest revision is still working - issue it first, or continue "
                "editing it.", no_update)
    repo.new_revision(q, user["email"])
    new = repo.get_revision(q)
    cx = _ctx(q, new["rev_no"])
    return (f"Rev {new['rev_no']} created from rev {latest['rev_no']}. Select it in "
            "the revision dropdown.", _header(cx))


@callback(Output("ce-download", "data"),
          Input("ce-exp-qcalc", "n_clicks"), Input("ce-exp-xlsx", "n_clicks"),
          State("ce-q", "data"), State("ce-rev", "data"),
          prevent_initial_call=True)
def _export(n1, n2, q, rev_no):
    if not (n1 or n2):
        raise PreventUpdate
    trig = ctx.triggered_id
    if trig == "ce-exp-qcalc":
        data = qcalc_io.export_revision(q, int(rev_no))
        return dict(content=json.dumps(data, indent=1),
                    filename=qcalc_io.export_filename(q, rev_no))
    xb = excel_export.workbook_bytes(q, int(rev_no))
    return dcc.send_bytes(lambda f: f.write(xb), excel_export.excel_filename(q, rev_no))


# --------------------------------------------------------------------------- #
# refresh-rates modal
# --------------------------------------------------------------------------- #
@callback(Output("ce-refresh-modal", "children"),
          Output("ce-refresh-modal", "style"),
          Input("ce-refresh-open", "n_clicks"),
          State("ce-q", "data"), State("ce-rev", "data"),
          prevent_initial_call=True)
def _refresh_open(n, q, rev_no):
    if not n:
        raise PreventUpdate
    cx = _guard(q, rev_no)
    diffs = repo.diff_snapshot(cx["rev"]["id"])
    if not diffs:
        body = html.P("All embedded rates match the current active rate set.",
                      style={"color": MUTED})
        footer = html.Button("Close", id="ce-refresh-cancel", n_clicks=0,
                             style=BTN_GHOST)
    else:
        body = html.Div([
            html.P("These embedded rates differ from the current active rate set. "
                   "Tick what to update - unticked items keep their snapshot values. "
                   "This is undoable.", style={"color": MUTED, "fontSize": "0.85rem"}),
            dcc.Checklist(
                id="ce-refresh-picks",
                options=[{"label": f"  {d['code']} \u00b7 {d['description']} \u00b7 "
                                   f"{d['field']}: {d['old']} \u2192 {d['new']} "
                                   f"{d['currency']}",
                          "value": d["snap_id"]} for d in diffs],
                value=[d["snap_id"] for d in diffs],
                style={"fontSize": "0.85rem"},
                labelStyle={"display": "block", "marginBottom": "4px"})])
        footer = html.Div([
            html.Button("Update selected", id="ce-refresh-apply", n_clicks=0,
                        style=BTN),
            html.Button("Cancel", id="ce-refresh-cancel", n_clicks=0,
                        style=BTN_GHOST),
        ], style={"marginTop": "12px"})
    modal = html.Div(html.Div([
        html.H4("Refresh rates against the library", style={"marginTop": 0}),
        body, footer,
    ], style={"background": "#fff", "borderRadius": "12px", "padding": "20px",
              "maxWidth": "620px", "margin": "10vh auto", "maxHeight": "70vh",
              "overflowY": "auto"}),
        style={"position": "fixed", "inset": 0, "background": "rgba(15,23,42,0.45)",
               "zIndex": 1000})
    return modal, {"display": "block"}


@callback(Output("ce-refresh-modal", "style", allow_duplicate=True),
          Output("ce-grid", "children", allow_duplicate=True),
          Output("ce-header", "children", allow_duplicate=True),
          Input("ce-refresh-apply", "n_clicks"), Input("ce-refresh-cancel", "n_clicks"),
          State("ce-refresh-picks", "value"),
          State("ce-q", "data"), State("ce-rev", "data"),
          State("ce-collapsed", "data"),
          prevent_initial_call=True)
def _refresh_apply(n_apply, n_cancel, picks, q, rev_no, collapsed):
    trig = ctx.triggered_id
    hidden = {"display": "none"}
    if trig == "ce-refresh-cancel" or not picks:
        return hidden, no_update, no_update
    cx = _ctx(q, rev_no)
    if not cx or not cx["editable"]:
        return hidden, no_update, no_update
    repo.refresh_snapshot(cx["rev"]["id"], picks, cx["user"]["email"])
    return hidden, _grid(cx, collapsed), _header(cx)


# --------------------------------------------------------------------------- #
# collapse / expand
# --------------------------------------------------------------------------- #
@callback(Output("ce-collapsed", "data"),
          Output("ce-grid", "children", allow_duplicate=True),
          Input({"t": "gc", "b": ALL}, "n_clicks"),
          State("ce-q", "data"), State("ce-rev", "data"),
          State("ce-collapsed", "data"),
          prevent_initial_call=True)
def _collapse(_n, q, rev_no, collapsed):
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    cx = _ctx(q, rev_no)
    if not cx:
        raise PreventUpdate
    collapsed = set(collapsed or [])
    if trig["b"] in collapsed:
        collapsed.discard(trig["b"])
    else:
        collapsed.add(trig["b"])
    return list(collapsed), _grid(cx, collapsed)


# --------------------------------------------------------------------------- #
# structure actions (+item, +lvl, +BB menu, deletes, L1, new BB)
# --------------------------------------------------------------------------- #
@callback(Output("ce-grid", "children", allow_duplicate=True),
          Output("ce-delarm", "data"),
          Output("ce-refmenu", "data"),
          Input({"t": "ga", "a": ALL, "b": ALL}, "n_clicks"),
          Input("ce-add-l1", "n_clicks"), Input("ce-bb-add", "n_clicks"),
          State("ce-bb-name", "value"),
          State("ce-q", "data"), State("ce-rev", "data"),
          State("ce-collapsed", "data"), State("ce-delarm", "data"),
          prevent_initial_call=True)
def _structure(_n, _n1, _nb, bb_name, q, rev_no, collapsed, armed):
    trig = ctx.triggered_id
    if not ctx.triggered[0]["value"]:
        raise PreventUpdate
    cx = _guard(q, rev_no)
    rev_id, user = cx["rev"]["id"], cx["user"]["email"]
    tree = repo.get_tree(rev_id)
    master = next((b["id"] for b in tree["blocks"] if b["kind"] == "master"), None)
    new_arm, new_menu = None, None
    if trig == "ce-add-l1":
        repo.add_block(rev_id, master, "package", "New chapter", "day", user)
    elif trig == "ce-bb-add":
        repo.add_block(rev_id, None, "block", (bb_name or "").strip()
                       or "New building block", "day", user)
    elif isinstance(trig, dict):
        a, b = trig["a"], trig["b"]
        if a == "item":
            repo.add_line(rev_id, b, "labor", user, description="New line", qty=1)
        elif a == "sub":
            repo.add_block(rev_id, b, "package", "New sub-level", "day", user)
        elif a == "refmenu":
            new_menu = b
        elif a == "delline":
            repo.delete_line(rev_id, b, user)
        elif a == "delref":
            repo.delete_ref(rev_id, b, user)
        elif a == "delblk":
            new_arm = b                                     # arm two-step
        elif a == "delblk2":
            repo.delete_block(rev_id, b, user)
        elif a == "delcancel":
            new_arm = None
    return _grid(cx, collapsed, armed=new_arm, refmenu=new_menu), new_arm, new_menu


# --------------------------------------------------------------------------- #
# cell edits (one dispatcher for every {"t":"ge"} field)
# --------------------------------------------------------------------------- #
@callback(Output("ce-grid", "children", allow_duplicate=True),
          Output("ce-header-status", "children", allow_duplicate=True),
          Input({"t": "ge", "f": ALL, "id": ALL}, "value"),
          State("ce-q", "data"), State("ce-rev", "data"),
          State("ce-collapsed", "data"),
          prevent_initial_call=True)
def _edit(_vals, q, rev_no, collapsed):
    trig = ctx.triggered_id
    if not isinstance(trig, dict):
        raise PreventUpdate
    val = ctx.triggered[0]["value"]
    cx = _guard(q, rev_no)
    rev_id, user = cx["rev"]["id"], cx["user"]["email"]
    f, i = trig["f"], trig["id"]
    msg = ""
    if f == "bname":
        if not (val or "").strip():
            raise PreventUpdate
        repo.update_block(rev_id, i, {"name": val.strip()}, user)
    elif f == "bqty":
        repo.update_block(rev_id, i, {"qty": _num(val, 1)}, user)
    elif f == "bnotes":
        repo.update_block(rev_id, i, {"notes": (val or "").strip() or None}, user)
    elif f == "qty":
        repo.update_line(rev_id, i, {"qty": _num(val, 1)}, user)
    elif f == "remarks":
        repo.update_line(rev_id, i, {"remarks": (val or "").strip() or None}, user)
    elif f == "origin":
        repo.update_line(rev_id, i, {"origin": val or "local"}, user)
    elif f == "basis":
        repo.update_line(rev_id, i, {"rate_basis": val or "offshore"}, user)
    elif f == "unitf":
        repo.update_line(rev_id, i, {"unit": val}, user)
    elif f == "uprice":
        repo.update_line(rev_id, i, {"unit_rate_override": _num(val)}, user)
    elif f == "markup":
        v = _num(val)
        repo.update_line(rev_id, i,
                         {"markup_override": None if v is None else v / 100.0}, user)
    elif f == "cat":
        el, _, sub = (val or "labor|").partition("|")
        repo.update_line(rev_id, i, {"element": el, "subcat": sub or None}, user)
    elif f == "refqty":
        repo.update_ref(rev_id, i, _num(val, 1), user)
    elif f == "addref":
        if val is None:
            raise PreventUpdate
        if repo.would_create_cycle(rev_id, i, val):
            msg = "That reference would create a cycle - refused."
        else:
            repo.add_ref(rev_id, i, val, 1, user)
    elif f == "desc":
        txt = (val or "").strip()
        match = next((o for o in _lib_options(cx["calc"])
                      if o["label"] == txt or o["item"]["code"] == txt), None)
        if match:
            sid = repo.snapshot_item(rev_id, match["lib"], match["uuid"], user)
            it = match["item"]
            element = {"personnel": "labor", "equipment": "equipment"}.get(
                match["lib"]) or repo.base_lib(match["lib"])[1] or "materials"
            fields = {"snap_item_id": sid, "description": match["desc"],
                      "element": element,
                      "subcat": it.get("category"),
                      "unit": it.get("unit"),
                      "unit_rate_override": None}
            if match["lib"] == "personnel":
                fields["rate_basis"] = "offshore"
            repo.update_line(rev_id, i, fields, user)
            msg = (f"Linked to library item {it['code']} "
                   f"({repo.code_label(it['code'])}).")
        else:
            repo.update_line(rev_id, i, {"description": txt or None}, user)
    else:
        raise PreventUpdate
    return _grid(cx, collapsed), msg
