"""
Calculation - Calculation editor (module v1).

One page, query-string addressed: /calculation/editor?q=Q0XXXX[&rev=N].

Left: the structure - master with nested packages, plus a separate
"Building blocks" list (kind=block roots; they price through references
only, so parking them anywhere can never double-count). Right: the selected
node - its own lines (element, library item or free text, qty x duration x
rate with basis/origin), its references to building blocks (qty multiplies
ALL element subtotals of the block), and its unit totals. The footer shows
the master rollup: seven-element subtotals, levies, the markup waterfall
and the sell price - recomputed live on every edit.

Editing follows the module's concurrency model: one estimator per Q number
(soft lock, 10-min stale timeout, heartbeat every minute). Everyone else -
and every issued revision - gets the read-only view, which polls the edit
journal and re-renders when the estimator changes something (the LIVE view).
Every mutation is journaled, which is also what powers Undo.

Issued revisions are immutable - the only way to amend is a new revision.
"""
import json

import dash
from dash import (html, dcc, Input, Output, State, callback, no_update, ALL, ctx)
from dash.exceptions import PreventUpdate

from app import auth
from app.calcmod import repo, engine, qcalc_io, excel_export
from app.calcmod.db import ELEMENTS, ELEMENT_LABELS

dash.register_page(__name__, path="/calculation/editor", name="Calculation editor",
                   title="Calculation editor", category="Calculation", order=3)

MODULE = "/calculation/editor"

INK, MUTED, TEAL, LINE = "#1f2937", "#6b7280", "#0f766e", "#e5e7eb"
PANEL, PANEL2, RED = "#f8fafc", "#f1f5f9", "#b91c1c"
BTN = {"padding": "7px 12px", "borderRadius": "8px", "border": "none", "background": TEAL,
       "color": "#fff", "fontWeight": 600, "cursor": "pointer", "fontSize": "0.82rem",
       "marginRight": "6px"}
BTN_GHOST = {"padding": "6px 10px", "borderRadius": "8px", "border": f"1px solid {LINE}",
             "background": "#fff", "color": INK, "cursor": "pointer", "fontSize": "0.78rem",
             "marginRight": "6px"}
BTN_DANGER = {**BTN_GHOST, "color": RED, "border": "1px solid #fecaca"}
FIELD = {"padding": "6px 8px", "borderRadius": "7px", "border": f"1px solid {LINE}",
         "fontSize": "0.82rem", "boxSizing": "border-box"}
NUM = {**FIELD, "width": "70px", "textAlign": "right",
       "fontFamily": "ui-monospace,monospace"}
CARD = {"background": "#fff", "border": f"1px solid {LINE}", "borderRadius": "12px",
        "padding": "14px", "marginBottom": "14px"}

BASIS_OPTS = [{"label": b, "value": b} for b in ("offshore", "yard", "office", "unit")]
ORIGIN_OPTS = [{"label": o, "value": o} for o in ("local", "expat")]
OWN_OPTS = [{"label": "int.", "value": "internal"}, {"label": "ext.", "value": "external"}]
ELEMENT_OPTS = [{"label": ELEMENT_LABELS[e], "value": e} for e in ELEMENTS]


# --------------------------------------------------------------------------- #
# context helpers
# --------------------------------------------------------------------------- #
def _user():
    return auth.current_user()


def _ctx(q, rev_no):
    """Everything the render helpers need: calc, revision, edit-vs-readonly."""
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


# --------------------------------------------------------------------------- #
# render helpers
# --------------------------------------------------------------------------- #
def _tree_panel(cx, selected_id):
    tree = repo.get_tree(cx["rev"]["id"])
    blocks = {b["id"]: b for b in tree["blocks"]}
    kids = {}
    for b in tree["blocks"]:
        kids.setdefault(b["parent_id"], []).append(b)

    def node(b, depth):
        sel = b["id"] == selected_id
        style = {"padding": "5px 8px", "paddingLeft": f"{8 + depth * 16}px",
                 "borderRadius": "7px", "cursor": "pointer", "fontSize": "0.85rem",
                 "background": PANEL2 if sel else "transparent",
                 "fontWeight": 700 if b["kind"] == "master" else (600 if sel else 400)}
        label = b["name"] if b["kind"] != "block" else f"{b['name']}  ({b['unit_label']})"
        items = [html.Div(label, id={"type": "ce-node", "id": b["id"]},
                          n_clicks=0, style=style)]
        for k in sorted([x for x in kids.get(b["id"], []) if x["kind"] == "package"],
                        key=lambda x: (x["sort_order"], x["id"])):
            items += node(k, depth + 1)
        return items

    master = next((b for b in tree["blocks"] if b["kind"] == "master"), None)
    struct = node(master, 0) if master else []
    bblocks = [b for b in tree["blocks"] if b["kind"] == "block"]
    bb_items = []
    for b in sorted(bblocks, key=lambda x: x["name"].lower()):
        sel = b["id"] == selected_id
        bb_items.append(html.Div(f"{b['name']}  ({b['unit_label']})",
                                 id={"type": "ce-node", "id": b["id"]}, n_clicks=0,
                                 style={"padding": "5px 8px", "borderRadius": "7px",
                                        "cursor": "pointer", "fontSize": "0.85rem",
                                        "background": PANEL2 if sel else "transparent",
                                        "fontWeight": 600 if sel else 400}))
    return html.Div([
        html.Div("Structure", style={"fontWeight": 700, "fontSize": "0.8rem",
                                     "color": MUTED, "marginBottom": "4px"}),
        *struct,
        html.Div("Building blocks", style={"fontWeight": 700, "fontSize": "0.8rem",
                                           "color": MUTED, "margin": "12px 0 4px"}),
        *(bb_items or [html.Div("none yet", style={"color": MUTED, "fontSize": "0.8rem",
                                                   "paddingLeft": "8px"})]),
    ])


def _lines_table(cx, block_id, snap, res):
    tree = repo.get_tree(cx["rev"]["id"])
    lines = [ln for ln in tree["lines"] if ln["block_id"] == block_id]
    refs = [r for r in tree["refs"] if r["host_block_id"] == block_id]
    blocks = {b["id"]: b for b in tree["blocks"]}
    ed = cx["editable"]

    th = {"textAlign": "left", "padding": "4px 6px", "fontSize": "0.72rem",
          "color": MUTED, "borderBottom": f"2px solid {LINE}"}
    td = {"padding": "3px 6px", "verticalAlign": "middle"}
    rows = []
    for ln in lines:
        item = snap["items"].get(ln["snap_item_id"]) if ln["snap_item_id"] else None
        desc = (item["description"] if item else (ln.get("description") or "")) or ""
        code = item["code"] if item else "\u2014"
        is_per = bool(item and item["lib"] == "personnel")
        cost, levy = engine.line_cost_usd(ln, snap)
        rows.append(html.Tr([
            html.Td(html.Span(code, title=desc, style={"fontFamily": "ui-monospace,monospace",
                                                       "fontSize": "0.75rem"}), style=td),
            html.Td(desc, style={**td, "maxWidth": "220px", "overflow": "hidden",
                                 "textOverflow": "ellipsis", "whiteSpace": "nowrap",
                                 "fontSize": "0.82rem"}),
            html.Td(dcc.Dropdown(id={"type": "ce-ln-el", "id": ln["id"]}, options=ELEMENT_OPTS,
                                 value=ln["element"], clearable=False, disabled=not ed,
                                 style={"width": "170px", "fontSize": "0.78rem"}), style=td),
            html.Td(dcc.Input(id={"type": "ce-ln-qty", "id": ln["id"]}, type="number",
                              value=ln["qty"], debounce=True, disabled=not ed, style=NUM),
                    style=td),
            html.Td(dcc.Input(id={"type": "ce-ln-dur", "id": ln["id"]}, type="number",
                              value=ln["duration"], debounce=True, disabled=not ed, style=NUM),
                    style=td),
            html.Td(dcc.Dropdown(id={"type": "ce-ln-basis", "id": ln["id"]}, options=BASIS_OPTS,
                                 value=ln["rate_basis"], clearable=False,
                                 disabled=(not ed) or (not is_per),
                                 style={"width": "100px", "fontSize": "0.78rem"}), style=td),
            html.Td(dcc.Dropdown(id={"type": "ce-ln-own", "id": ln["id"]}, options=OWN_OPTS,
                                 value=ln.get("ownership") or "internal", clearable=False,
                                 disabled=(not ed) or ln["element"] not in
                                 ("labor", "equipment"),
                                 style={"width": "80px", "fontSize": "0.78rem"}), style=td),
            html.Td(dcc.Dropdown(id={"type": "ce-ln-origin", "id": ln["id"]}, options=ORIGIN_OPTS,
                                 value=ln["origin"], clearable=False,
                                 disabled=(not ed) or ln["element"] != "labor",
                                 style={"width": "90px", "fontSize": "0.78rem"}), style=td),
            html.Td(dcc.Input(id={"type": "ce-ln-ovr", "id": ln["id"]}, type="number",
                              value=ln["unit_rate_override"], placeholder="snapshot",
                              debounce=True, disabled=not ed,
                              style={**NUM, "width": "90px"}), style=td),
            html.Td(_fmt(cost + levy), style={**td, "textAlign": "right",
                                              "fontFamily": "ui-monospace,monospace",
                                              "fontSize": "0.8rem"}),
            html.Td(html.Button("\u2715", id={"type": "ce-ln-del", "id": ln["id"]},
                                n_clicks=0, style=BTN_DANGER, disabled=not ed), style=td),
        ]))
    ref_rows = []
    for r in refs:
        rb = blocks.get(r["ref_block_id"])
        unit_sell = res["blocks"][r["ref_block_id"]]
        unit_cost = unit_sell["cost"] + unit_sell["levies"]
        ref_rows.append(html.Tr([
            html.Td(html.Span("\u21b3 ref", style={"color": TEAL, "fontSize": "0.75rem",
                                                   "fontWeight": 700}), style=td),
            html.Td(f"{rb['name']} (per {rb['unit_label']}: {_fmt(unit_cost)} USD)",
                    style={**td, "fontSize": "0.82rem"}),
            html.Td("all elements \u00d7 qty", style={**td, "color": MUTED,
                                                      "fontSize": "0.75rem"}, colSpan=2),
            html.Td(dcc.Input(id={"type": "ce-ref-qty", "id": r["id"]}, type="number",
                              value=r["qty"], debounce=True, disabled=not ed, style=NUM),
                    style=td, colSpan=4),
            html.Td(""),
            html.Td(_fmt(unit_cost * r["qty"]), style={**td, "textAlign": "right",
                                                       "fontFamily": "ui-monospace,monospace",
                                                       "fontSize": "0.8rem"}),
            html.Td(html.Button("\u2715", id={"type": "ce-ref-del", "id": r["id"]},
                                n_clicks=0, style=BTN_DANGER, disabled=not ed), style=td),
        ], style={"background": PANEL}))
    return html.Table([
        html.Thead(html.Tr([html.Th(h, style=th) for h in
                            ("Code", "Description", "Element", "Qty", "Dur",
                             "Basis", "Own", "Origin", "Rate ovr", "Cost+levy USD",
                             "")])),
        html.Tbody(rows + ref_rows),
    ], style={"borderCollapse": "collapse", "width": "100%"})


def _block_panel(cx, block_id):
    tree = repo.get_tree(cx["rev"]["id"])
    blocks = {b["id"]: b for b in tree["blocks"]}
    b = blocks.get(block_id)
    if not b:
        return html.P("Select a node on the left.", style={"color": MUTED})
    snap = repo.load_snapshot(cx["rev"]["id"])
    res = engine.compute(tree, snap)
    ed = cx["editable"]
    r = res["blocks"][b["id"]]

    # add-line: library item picker options (already-embedded first, then library)
    calc = cx["calc"]
    lib_opts = []
    for sid, s in sorted(snap["items"].items(), key=lambda kv: kv[1]["code"]):
        lib_opts.append({"label": f"\u2713 {s['code']} \u00b7 {s['description']}",
                         "value": f"snap:{sid}"})
    rs = repo.active_rate_set()
    for lib in ("personnel", "equipment", "misc"):
        for it in repo.list_items(lib, calc["division"]):
            if any(s["item_uuid"] == it["uuid"] for s in snap["items"].values()):
                continue
            lbl = it.get("description") or it.get("function")
            lib_opts.append({"label": f"{it['code']} \u00b7 {lbl}",
                             "value": f"lib:{lib}:{it['uuid']}"})

    ref_candidates = [{"label": f"{x['name']} ({x['unit_label']})", "value": x["id"]}
                      for x in tree["blocks"]
                      if x["kind"] == "block" and x["id"] != b["id"]]

    unit_line = html.Div([
        html.Span(f"Unit totals (per {b['unit_label']}):  ", style={"color": MUTED}),
        html.B(f"cost {_fmt(r['cost'])}  +  levies {_fmt(r['levies'])}  =  "
               f"{_fmt(r['cost'] + r['levies'])} USD"),
    ], style={"fontSize": "0.85rem", "marginTop": "10px"})

    header = html.Div([
        dcc.Input(id="ce-blk-name", value=b["name"], debounce=True, disabled=not ed,
                  style={**FIELD, "width": "340px", "fontWeight": 600, "marginRight": "8px"}),
        html.Span("unit:", style={"color": MUTED, "fontSize": "0.8rem",
                                  "marginRight": "4px"}),
        dcc.Input(id="ce-blk-unit", value=b["unit_label"], debounce=True, disabled=not ed,
                  style={**FIELD, "width": "110px", "marginRight": "12px"}),
        (html.Button("Delete block", id="ce-blk-del", n_clicks=0, style=BTN_DANGER)
         if ed and b["kind"] != "master" else None),
    ])

    add_row = html.Div([
        dcc.Dropdown(id="ce-add-item", options=lib_opts, placeholder="Library item "
                     "(\u2713 = already in this calc's snapshot) \u2014 or leave empty for free text",
                     style={"width": "420px", "display": "inline-block",
                            "verticalAlign": "middle", "marginRight": "8px",
                            "fontSize": "0.8rem"}),
        dcc.Input(id="ce-add-desc", placeholder="Free-text description",
                  style={**FIELD, "width": "200px", "marginRight": "8px"}),
        dcc.Dropdown(id="ce-add-el", options=ELEMENT_OPTS,
                     placeholder="Element (auto from library item)",
                     style={"width": "210px", "display": "inline-block",
                            "verticalAlign": "middle", "marginRight": "8px",
                            "fontSize": "0.8rem"}),
        html.Button("Add line", id="ce-add-line", n_clicks=0, style=BTN),
    ], style={"marginTop": "10px"}) if ed else None

    add_child = html.Div([
        dcc.Input(id="ce-add-child-name", placeholder="New package / block name",
                  style={**FIELD, "width": "240px", "marginRight": "8px"}),
        html.Button("+ package (in tree)", id="ce-add-pkg", n_clicks=0, style=BTN_GHOST),
        html.Button("+ building block", id="ce-add-blk", n_clicks=0, style=BTN_GHOST),
        html.Span(" | ", style={"color": LINE}),
        dcc.Dropdown(id="ce-add-ref-block", options=ref_candidates,
                     placeholder="Reference a building block\u2026",
                     style={"width": "260px", "display": "inline-block",
                            "verticalAlign": "middle", "margin": "0 8px",
                            "fontSize": "0.8rem"}),
        dcc.Input(id="ce-add-ref-qty", type="number", value=1, style=NUM),
        html.Button("Add ref", id="ce-add-ref", n_clicks=0,
                    style={**BTN, "marginLeft": "8px"}),
    ], style={"marginTop": "10px"}) if ed else None

    return html.Div([
        header,
        html.Div(_lines_table(cx, b["id"], snap, res), style={"marginTop": "10px",
                                                              "overflowX": "auto"}),
        add_row, add_child, unit_line,
        html.Div(id="ce-blk-status", style={"fontSize": "0.82rem", "color": RED,
                                            "marginTop": "6px", "minHeight": "1.1em"}),
    ])


def _totals_panel(cx):
    tree = repo.get_tree(cx["rev"]["id"])
    snap = repo.load_snapshot(cx["rev"]["id"])
    res = engine.compute(tree, snap)
    if res["master_id"] is None:
        return html.Div()
    m = res["blocks"][res["master_id"]]
    def _cell(e):
        sub = None
        if e in ("labor", "equipment"):
            sp = m["splits"][e]
            sub = html.Div(f"int {_fmt(sp['internal'])} · ext {_fmt(sp['external'])}",
                           style={"fontSize": "0.66rem", "color": MUTED})
        return html.Div([
            html.Div(ELEMENT_LABELS[e], style={"fontSize": "0.7rem", "color": MUTED}),
            html.Div(_fmt(m["elements"][e]), style={"fontFamily": "ui-monospace,monospace",
                                                    "fontSize": "0.85rem"}),
            sub,
        ], style={"padding": "4px 16px 4px 0"})

    cells = [_cell(e) for e in ELEMENTS]
    wf = [html.Span(f"{lbl} {_fmt(amt)}", style={"marginRight": "16px",
                                                 "fontSize": "0.8rem", "color": MUTED})
          for lbl, amt in m["waterfall"]]
    return html.Div([
        html.Div(cells, style={"display": "flex", "flexWrap": "wrap"}),
        html.Div([html.Span("Cost ", style={"color": MUTED}),
                  html.B(_fmt(m["cost"]) + " USD", style={"marginRight": "24px"}), *wf,
                  html.Span("Sell ", style={"color": MUTED, "marginLeft": "8px"}),
                  html.B(_fmt(m["sell"]) + " USD",
                         style={"color": TEAL, "fontSize": "1.05rem"})],
                 style={"marginTop": "6px"}),
    ], style=CARD)


def _header(cx):
    calc, rev = cx["calc"], cx["rev"]
    revs = repo.get_revisions(calc["qnumber"])
    rev_opts = [{"label": f"Rev {r['rev_no']} \u00b7 {r['status']}", "value": r["rev_no"]}
                for r in revs]
    lock_badge = None
    if rev["status"] == "working" and cx["may_edit"] and not cx["lock_ok"]:
        st = repo.lock_status(calc["qnumber"])
        lock_badge = html.Span(f"\U0001f512 locked by {st['user']} \u2014 read-only, live view",
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
                      style={"color": MUTED, "fontSize": "0.82rem", "marginRight": "16px"}),
            dcc.Dropdown(id="ce-rev-select", options=rev_opts, value=rev["rev_no"],
                         clearable=False, style={"width": "170px",
                                                 "display": "inline-block",
                                                 "verticalAlign": "middle",
                                                 "marginRight": "12px",
                                                 "fontSize": "0.8rem"}),
            *btns,
        ], style={"marginTop": "8px"}),
        html.Div(id="ce-header-status", style={"fontSize": "0.82rem", "marginTop": "6px",
                                               "minHeight": "1.1em"}),
    ], style=CARD)


def _render_all(cx, selected_id):
    return (_header(cx),
            _tree_panel(cx, selected_id),
            _block_panel(cx, selected_id),
            _totals_panel(cx))


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
    tree = repo.get_tree(cx["rev"]["id"])
    master = next((b["id"] for b in tree["blocks"] if b["kind"] == "master"), None)
    hdr, tp, bp, tot = _render_all(cx, master)
    return html.Div([
        dcc.Store(id="ce-q", data=q),
        dcc.Store(id="ce-rev", data=cx["rev"]["rev_no"]),
        dcc.Store(id="ce-selected", data=master),
        dcc.Store(id="ce-lastseq", data=repo.last_seq(cx["rev"]["id"])),
        dcc.Interval(id="ce-poll", interval=3000, disabled=cx["editable"]),
        dcc.Interval(id="ce-heartbeat", interval=60000, disabled=not cx["editable"]),
        dcc.Download(id="ce-download"),
        html.Div(id="ce-header", children=hdr),
        html.Div([
            html.Div(id="ce-tree", children=tp,
                     style={**CARD, "width": "300px", "flexShrink": 0,
                            "maxHeight": "70vh", "overflowY": "auto"}),
            html.Div(id="ce-block", children=bp, style={**CARD, "flexGrow": 1}),
        ], style={"display": "flex", "gap": "14px", "alignItems": "flex-start"}),
        html.Div(id="ce-totals", children=tot),
        # refresh-rates modal
        html.Div(id="ce-refresh-modal", style={"display": "none"}),
    ])


# --------------------------------------------------------------------------- #
# selection, polling, heartbeat
# --------------------------------------------------------------------------- #
@callback(Output("ce-selected", "data"),
          Output("ce-tree", "children", allow_duplicate=True),
          Output("ce-block", "children", allow_duplicate=True),
          Input({"type": "ce-node", "id": ALL}, "n_clicks"),
          State("ce-q", "data"), State("ce-rev", "data"),
          prevent_initial_call=True)
def _select(_clicks, q, rev_no):
    if not ctx.triggered_id or not any(_clicks):
        raise PreventUpdate
    bid = ctx.triggered_id["id"]
    cx = _ctx(q, rev_no)
    if not cx:
        raise PreventUpdate
    return bid, _tree_panel(cx, bid), _block_panel(cx, bid)


@callback(Output("ce-lastseq", "data"),
          Output("ce-header", "children", allow_duplicate=True),
          Output("ce-tree", "children", allow_duplicate=True),
          Output("ce-block", "children", allow_duplicate=True),
          Output("ce-totals", "children", allow_duplicate=True),
          Input("ce-poll", "n_intervals"),
          State("ce-q", "data"), State("ce-rev", "data"),
          State("ce-selected", "data"), State("ce-lastseq", "data"),
          prevent_initial_call=True)
def _poll(_n, q, rev_no, selected, seen):
    cx = _ctx(q, rev_no)
    if not cx:
        raise PreventUpdate
    seq = repo.last_seq(cx["rev"]["id"])
    if seq == seen:
        raise PreventUpdate
    hdr, tp, bp, tot = _render_all(cx, selected)
    return seq, hdr, tp, bp, tot


@callback(Output("ce-heartbeat", "disabled"),
          Input("ce-heartbeat", "n_intervals"),
          State("ce-q", "data"), prevent_initial_call=True)
def _beat(_n, q):
    user = _user()
    if user and q:
        repo.heartbeat_lock(q, user["email"])
    return False


# --------------------------------------------------------------------------- #
# revision switching + header actions
# --------------------------------------------------------------------------- #
@callback(Output("ce-rev", "data"),
          Output("ce-header", "children", allow_duplicate=True),
          Output("ce-tree", "children", allow_duplicate=True),
          Output("ce-block", "children", allow_duplicate=True),
          Output("ce-totals", "children", allow_duplicate=True),
          Output("ce-poll", "disabled"),
          Input("ce-rev-select", "value"),
          State("ce-q", "data"), prevent_initial_call=True)
def _switch_rev(rev_no, q):
    cx = _ctx(q, rev_no)
    if not cx:
        raise PreventUpdate
    tree = repo.get_tree(cx["rev"]["id"])
    master = next((b["id"] for b in tree["blocks"] if b["kind"] == "master"), None)
    hdr, tp, bp, tot = _render_all(cx, master)
    return rev_no, hdr, tp, bp, tot, cx["editable"]


@callback(Output("ce-header", "children", allow_duplicate=True),
          Output("ce-tree", "children", allow_duplicate=True),
          Output("ce-block", "children", allow_duplicate=True),
          Output("ce-totals", "children", allow_duplicate=True),
          Input("ce-undo", "n_clicks"),
          State("ce-q", "data"), State("ce-rev", "data"), State("ce-selected", "data"),
          prevent_initial_call=True)
def _undo(n, q, rev_no, selected):
    if not n:
        raise PreventUpdate
    cx = _ctx(q, rev_no)
    if not cx or not cx["editable"]:
        raise PreventUpdate
    repo.undo_last(cx["rev"]["id"], cx["user"]["email"])
    return _render_all(cx, selected)


@callback(Output("ce-header-status", "children"),
          Output("ce-header", "children", allow_duplicate=True),
          Input("ce-issue", "n_clicks"),
          State("ce-q", "data"), State("ce-rev", "data"),
          prevent_initial_call=True)
def _issue(n, q, rev_no):
    if not n:
        raise PreventUpdate
    cx = _ctx(q, rev_no)
    if not cx or not cx["editable"]:
        raise PreventUpdate
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
    return (f"Rev {new['rev_no']} created from rev {latest['rev_no']}. Select it in the "
            "revision dropdown.", _header(cx))


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
# refresh-rates diff modal
# --------------------------------------------------------------------------- #
@callback(Output("ce-refresh-modal", "children"),
          Output("ce-refresh-modal", "style"),
          Input("ce-refresh-open", "n_clicks"),
          State("ce-q", "data"), State("ce-rev", "data"),
          prevent_initial_call=True)
def _refresh_open(n, q, rev_no):
    if not n:
        raise PreventUpdate
    cx = _ctx(q, rev_no)
    if not cx or not cx["editable"]:
        raise PreventUpdate
    diffs = repo.diff_snapshot(cx["rev"]["id"], cx["calc"]["region"])
    if not diffs:
        body = html.P("All embedded rates match the current active rate set.",
                      style={"color": MUTED})
        opts, footer = None, html.Button("Close", id="ce-refresh-cancel", n_clicks=0,
                                         style=BTN_GHOST)
    else:
        opts = dcc.Checklist(
            id="ce-refresh-picks",
            options=[{"label": f"  {d['code']} \u00b7 {d['description']} \u00b7 {d['field']}: "
                               f"{d['old']} \u2192 {d['new']} {d['currency']}",
                      "value": d["snap_id"]} for d in diffs],
            value=[d["snap_id"] for d in diffs],
            style={"fontSize": "0.85rem"}, labelStyle={"display": "block",
                                                       "marginBottom": "4px"})
        body = html.Div([
            html.P("These embedded rates differ from the current active rate set. "
                   "Tick what to update - unticked items keep their snapshot values. "
                   "This is undoable.", style={"color": MUTED, "fontSize": "0.85rem"}),
            opts])
        footer = html.Div([
            html.Button("Update selected", id="ce-refresh-apply", n_clicks=0, style=BTN),
            html.Button("Cancel", id="ce-refresh-cancel", n_clicks=0, style=BTN_GHOST),
        ], style={"marginTop": "12px"})
    modal = html.Div(html.Div([
        html.H4("Refresh rates against the library", style={"marginTop": 0}),
        body, footer,
    ], style={"background": "#fff", "borderRadius": "12px", "padding": "20px",
              "maxWidth": "620px", "margin": "10vh auto", "maxHeight": "70vh",
              "overflowY": "auto"}),
        style={"position": "fixed", "inset": 0, "background": "rgba(15,23,42,0.45)",
               "zIndex": 1000})
    if not diffs:
        # still show the modal so the user gets the confirmation
        return modal, {"display": "block"}
    return modal, {"display": "block"}


@callback(Output("ce-refresh-modal", "style", allow_duplicate=True),
          Output("ce-block", "children", allow_duplicate=True),
          Output("ce-totals", "children", allow_duplicate=True),
          Output("ce-header", "children", allow_duplicate=True),
          Input("ce-refresh-apply", "n_clicks"), Input("ce-refresh-cancel", "n_clicks"),
          State("ce-refresh-picks", "value"),
          State("ce-q", "data"), State("ce-rev", "data"), State("ce-selected", "data"),
          prevent_initial_call=True)
def _refresh_apply(n_apply, n_cancel, picks, q, rev_no, selected):
    trig = ctx.triggered_id
    hidden = {"display": "none"}
    if trig == "ce-refresh-cancel" or not picks:
        if trig == "ce-refresh-apply" and not picks:
            return hidden, no_update, no_update, no_update
        return hidden, no_update, no_update, no_update
    cx = _ctx(q, rev_no)
    if not cx or not cx["editable"]:
        return hidden, no_update, no_update, no_update
    repo.refresh_snapshot(cx["rev"]["id"], cx["calc"]["region"], picks, cx["user"]["email"])
    return hidden, _block_panel(cx, selected), _totals_panel(cx), _header(cx)


# --------------------------------------------------------------------------- #
# block panel mutations
# --------------------------------------------------------------------------- #
def _mutate_guard(q, rev_no):
    cx = _ctx(q, rev_no)
    if not cx or not cx["editable"]:
        raise PreventUpdate
    return cx


@callback(Output("ce-block", "children", allow_duplicate=True),
          Output("ce-totals", "children", allow_duplicate=True),
          Output("ce-tree", "children", allow_duplicate=True),
          Input("ce-blk-name", "value"), Input("ce-blk-unit", "value"),
          State("ce-q", "data"), State("ce-rev", "data"), State("ce-selected", "data"),
          prevent_initial_call=True)
def _blk_meta(name, unit, q, rev_no, selected):
    cx = _mutate_guard(q, rev_no)
    fields = {}
    if name:
        fields["name"] = name
    if unit:
        fields["unit_label"] = unit
    if fields:
        repo.update_block(cx["rev"]["id"], selected, fields, cx["user"]["email"])
    return _block_panel(cx, selected), _totals_panel(cx), _tree_panel(cx, selected)


@callback(Output("ce-selected", "data", allow_duplicate=True),
          Output("ce-block", "children", allow_duplicate=True),
          Output("ce-totals", "children", allow_duplicate=True),
          Output("ce-tree", "children", allow_duplicate=True),
          Input("ce-blk-del", "n_clicks"),
          State("ce-q", "data"), State("ce-rev", "data"), State("ce-selected", "data"),
          prevent_initial_call=True)
def _blk_delete(n, q, rev_no, selected):
    if not n:
        raise PreventUpdate
    cx = _mutate_guard(q, rev_no)
    repo.delete_block(cx["rev"]["id"], selected, cx["user"]["email"])
    tree = repo.get_tree(cx["rev"]["id"])
    master = next((b["id"] for b in tree["blocks"] if b["kind"] == "master"), None)
    return master, _block_panel(cx, master), _totals_panel(cx), _tree_panel(cx, master)


@callback(Output("ce-block", "children", allow_duplicate=True),
          Output("ce-totals", "children", allow_duplicate=True),
          Output("ce-tree", "children", allow_duplicate=True),
          Output("ce-blk-status", "children"),
          Input("ce-add-line", "n_clicks"), Input("ce-add-pkg", "n_clicks"),
          Input("ce-add-blk", "n_clicks"), Input("ce-add-ref", "n_clicks"),
          State("ce-add-item", "value"), State("ce-add-desc", "value"),
          State("ce-add-el", "value"), State("ce-add-child-name", "value"),
          State("ce-add-ref-block", "value"), State("ce-add-ref-qty", "value"),
          State("ce-q", "data"), State("ce-rev", "data"), State("ce-selected", "data"),
          prevent_initial_call=True)
def _adds(n_line, n_pkg, n_blk, n_ref, item_val, desc, element, child_name,
          ref_block, ref_qty, q, rev_no, selected):
    trig = ctx.triggered_id
    cx = _mutate_guard(q, rev_no)
    rev_id, user = cx["rev"]["id"], cx["user"]["email"]
    err = ""
    if trig == "ce-add-line" and n_line:
        snap_id = None
        if item_val and item_val.startswith("snap:"):
            snap_id = int(item_val.split(":")[1])
        elif item_val and item_val.startswith("lib:"):
            _, lib, uid = item_val.split(":", 2)
            snap_id = repo.snapshot_item(rev_id, lib, uid, cx["calc"]["region"], user)
        snap = repo.load_snapshot(rev_id)
        item = snap["items"].get(snap_id) if snap_id else None
        ownership = None
        if item:
            # element + ownership prefill from the library (still editable per line)
            def_el, def_own = repo.item_default_element(item["lib"], item)
            element = element or def_el
            ownership = def_own
        if not element:
            err = "Choose an element (or pick a library item, which sets it)."
        else:
            is_per = bool(item and item["lib"] == "personnel")
            repo.add_line(rev_id, selected, element, user, snap_item_id=snap_id,
                          description=(desc or None),
                          rate_basis=("offshore" if is_per else "unit"),
                          ownership=ownership)
    elif trig == "ce-add-pkg" and n_pkg:
        if not child_name:
            err = "Give the new package a name."
        else:
            repo.add_block(rev_id, selected, "package", child_name, "lump", user)
    elif trig == "ce-add-blk" and n_blk:
        if not child_name:
            err = "Give the new building block a name."
        else:
            repo.add_block(rev_id, None, "block", child_name, "day", user)
    elif trig == "ce-add-ref" and n_ref:
        if not ref_block:
            err = "Choose a building block to reference."
        else:
            _, e = repo.add_ref(rev_id, selected, int(ref_block),
                                float(ref_qty or 1), user)
            err = e or ""
    return (_block_panel(cx, selected), _totals_panel(cx), _tree_panel(cx, selected), err)


@callback(Output("ce-block", "children", allow_duplicate=True),
          Output("ce-totals", "children", allow_duplicate=True),
          Input({"type": "ce-ln-qty", "id": ALL}, "value"),
          Input({"type": "ce-ln-dur", "id": ALL}, "value"),
          Input({"type": "ce-ln-el", "id": ALL}, "value"),
          Input({"type": "ce-ln-basis", "id": ALL}, "value"),
          Input({"type": "ce-ln-origin", "id": ALL}, "value"),
          Input({"type": "ce-ln-own", "id": ALL}, "value"),
          Input({"type": "ce-ln-ovr", "id": ALL}, "value"),
          Input({"type": "ce-ref-qty", "id": ALL}, "value"),
          State("ce-q", "data"), State("ce-rev", "data"), State("ce-selected", "data"),
          prevent_initial_call=True)
def _edit_values(_q1, _q2, _q3, _q4, _q5, _q6, _q7, _q8, q, rev_no, selected):
    trig = ctx.triggered_id
    if not isinstance(trig, dict):
        raise PreventUpdate
    cx = _mutate_guard(q, rev_no)
    rev_id, user = cx["rev"]["id"], cx["user"]["email"]
    val = ctx.triggered[0]["value"]
    t, oid = trig["type"], trig["id"]
    field = {"ce-ln-qty": "qty", "ce-ln-dur": "duration", "ce-ln-el": "element",
             "ce-ln-basis": "rate_basis", "ce-ln-origin": "origin",
             "ce-ln-own": "ownership", "ce-ln-ovr": "unit_rate_override"}.get(t)
    if field:
        if field in ("qty", "duration") and val in (None, ""):
            raise PreventUpdate
        repo.update_line(rev_id, oid, {field: val}, user)
    elif t == "ce-ref-qty":
        if val in (None, ""):
            raise PreventUpdate
        repo.update_ref(rev_id, oid, float(val), user)
    return _block_panel(cx, selected), _totals_panel(cx)


@callback(Output("ce-block", "children", allow_duplicate=True),
          Output("ce-totals", "children", allow_duplicate=True),
          Input({"type": "ce-ln-del", "id": ALL}, "n_clicks"),
          Input({"type": "ce-ref-del", "id": ALL}, "n_clicks"),
          State("ce-q", "data"), State("ce-rev", "data"), State("ce-selected", "data"),
          prevent_initial_call=True)
def _deletes(n_lines, n_refs, q, rev_no, selected):
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    cx = _mutate_guard(q, rev_no)
    rev_id, user = cx["rev"]["id"], cx["user"]["email"]
    if trig["type"] == "ce-ln-del":
        repo.delete_line(rev_id, trig["id"], user)
    else:
        repo.delete_ref(rev_id, trig["id"], user)
    return _block_panel(cx, selected), _totals_panel(cx)
