"""
Calculation - IBIS review.

Native Dash port of the former self-contained HTML tool. It opens an IBIS
``.xtb`` (a SQLite budget), rolls costs up the chapter/line tree, applies the
compounded staart, builds a location/asset-scoped levy + VAT quote, and exports
either an Excel quote or an amended ``.xtb``. All calculation lives in
``app.engines.ibis``; this file is layout + callback wiring only.

The uploaded file is held in a *memory* store for the session and parsed per
interaction - it is never written to disk on the server and does not persist
past a page refresh. That keeps a confidential cost/margin file transient.

Editing: on the Calculation tab, Aantal / Unit price / Markup are editable
(Personnel unit price is derived from wage x norm, so it is read-only and moves
with the Hourly-rates tab). Cost Price = Unit x Aantal; Net Price = Cost x
(1 + Markup). Edits recompute the roll-ups, header and staart live, and can be
written back to a NEW .xtb (Versie bumped; the original is untouched).
"""
import base64

import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ALL, ctx

from app import auth
from app.engines import ibis

dash.register_page(__name__, path="/calculation/ibis-review", name="IBIS review",
                   title="IBIS calculation review", category="Calculation", order=1)

MODULE = "/calculation/ibis-review"

# --- palette (portal light theme) ------------------------------------------ #
INK, MUTED, TEAL, LINE = "#1f2937", "#6b7280", "#0f766e", "#e5e7eb"
PANEL, PANEL2, ACCENT = "#f8fafc", "#f1f5f9", "#0f766e"
COST_FG, NET_FG = "#334155", "#0f766e"
CAT_COLOR = {"Personnel": "#2563eb", "Equipment": "#b45309",
             "Material": "#047857", "Subcontract": "#7c3aed"}
TYPES = ["Personnel", "Equipment", "Material", "Subcontract"]

BTN = {"padding": "8px 14px", "borderRadius": "8px", "border": "none", "background": TEAL,
       "color": "#fff", "fontWeight": 600, "cursor": "pointer", "fontSize": "0.85rem"}
BTN_GHOST = {"padding": "6px 11px", "borderRadius": "8px", "border": f"1px solid {LINE}",
             "background": "#fff", "color": INK, "cursor": "pointer", "fontSize": "0.8rem"}
CELL = {"width": "72px", "padding": "3px 6px", "borderRadius": "6px",
        "border": f"1px solid {LINE}", "textAlign": "right",
        "fontFamily": "ui-monospace,monospace", "fontSize": "0.8rem"}


# --------------------------------------------------------------------------- #
# formatting helpers
# --------------------------------------------------------------------------- #
def _money(v, ccy, valutas, calc):
    if v is None or v == "":
        return ""
    try:
        f = v * (valutas[ccy]["koers"] / valutas[calc]["koers"])
    except Exception:
        f = v
    dec = 0 if abs(f) >= 1000 else 2
    sym = valutas.get(ccy, {}).get("teken", "")
    return f"{sym} {f:,.{dec}f}"


def _num(v, dec=2):
    if v is None or v == "":
        return ""
    return f"{float(v):,.{dec}f}".rstrip("0").rstrip(".") if dec else f"{float(v):,.0f}"


def _decode(b64):
    return base64.b64decode(b64)


def _model(store):
    if not store or not store.get("b64"):
        return None, None
    raw = _decode(store["b64"])
    return raw, ibis.load(raw)


def _badge(text, color):
    return html.Span(text, style={
        "fontSize": "0.66rem", "fontWeight": 700, "padding": "1px 6px", "borderRadius": "6px",
        "background": color + "1a", "color": color, "marginLeft": "6px", "whiteSpace": "nowrap"})


# --------------------------------------------------------------------------- #
# layout
# --------------------------------------------------------------------------- #
def _stores():
    return html.Div([
        dcc.Store(id="ib-file", storage_type="memory"),
        dcc.Store(id="ib-edits", storage_type="memory", data={}),
        dcc.Store(id="ib-wages", storage_type="memory", data={}),
        dcc.Store(id="ib-levies", storage_type="memory", data=[]),
        dcc.Store(id="ib-staart", storage_type="memory", data=None),
        dcc.Store(id="ib-view", storage_type="memory", data="calc"),
        dcc.Store(id="ib-expanded", storage_type="memory", data=[]),
        dcc.Store(id="ib-linefilter", storage_type="memory", data=None),
        dcc.Store(id="ib-typesel", storage_type="memory", data=[]),
        dcc.Store(id="ib-classedits", storage_type="memory", data={}),
        dcc.Store(id="ib-report", storage_type="memory", data={"mode": "cat", "cat": None, "res": None, "path": []}),
        dcc.Download(id="ib-dl-xlsx"),
        dcc.Download(id="ib-dl-xtb"),
    ])


def _card(label, cid, accent=False):
    return html.Div([
        html.Div(label, style={"fontSize": "0.66rem", "letterSpacing": ".06em",
                               "color": MUTED, "fontWeight": 700}),
        html.Div("—", id=cid, style={"fontSize": "1.15rem", "fontWeight": 700,
                                     "color": NET_FG if accent else INK, "marginTop": "3px",
                                     "fontFamily": "ui-monospace,monospace"}),
    ], style={"flex": "1 1 120px", "background": "#fff", "border": f"1px solid {LINE}",
              "borderRadius": "10px", "padding": "10px 12px", "minWidth": "110px"})


def layout(**_):
    user = auth.current_user()
    if not auth.can_access(user, MODULE):
        return html.Div([
            html.H3("IBIS review"),
            html.P("You don't have access to this tool. Request it from the Home page.",
                   style={"color": MUTED}),
        ], style={"padding": "24px", "maxWidth": "720px"})

    return html.Div([
        _stores(),
        # header row: title + currency + cards
        html.Div([
            html.Div([
                html.Div("Drop an IBIS .xtb here to begin", id="ib-name",
                         style={"fontSize": "1.15rem", "fontWeight": 700, "color": INK}),
                html.Div("", id="ib-sub", style={"fontSize": "0.78rem", "color": MUTED}),
            ], style={"flex": "1 1 auto"}),
            html.Div([
                html.Span("Currency ", style={"fontSize": "0.78rem", "color": MUTED}),
                dcc.RadioItems(id="ib-ccy-sel", options=[], value=None, inline=True,
                               inputStyle={"marginRight": "4px", "marginLeft": "10px"},
                               style={"display": "inline-block", "fontSize": "0.82rem"}),
            ], style={"display": "flex", "alignItems": "center"}),
        ], style={"display": "flex", "gap": "16px", "alignItems": "center",
                  "flexWrap": "wrap", "marginBottom": "12px"}),

        html.Div([
            _card("COST", "ib-c-cost"), _card("MARKUP", "ib-c-markup"),
            _card("STAART", "ib-c-staart"), _card("LEVY + VAT", "ib-c-levy"),
            _card("NET TOTAL (QUOTE)", "ib-c-net", accent=True),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "12px"}),

        # upload + actions
        html.Div([
            dcc.Upload(id="ib-upload", children=html.Div([
                html.Span("Drop an IBIS .xtb file here or ", style={"color": MUTED}),
                html.Span("browse", style={"color": TEAL, "fontWeight": 600, "cursor": "pointer"}),
            ]), style={"flex": "1 1 auto", "border": f"1px dashed {LINE}", "borderRadius": "10px",
                       "padding": "12px 14px", "background": "#fff", "cursor": "pointer"},
                multiple=False, accept=".xtb"),
            html.Button("Export quote to Excel", id="ib-btn-xlsx", n_clicks=0, style=BTN),
            html.Button("Download modified .xtb", id="ib-btn-xtb", n_clicks=0,
                        style={**BTN, "background": "#334155"}),
            html.Button("Reset edits", id="ib-btn-reset", n_clicks=0, style=BTN_GHOST),
        ], style={"display": "flex", "gap": "10px", "alignItems": "center",
                  "flexWrap": "wrap", "marginBottom": "6px"}),
        html.Div("", id="ib-msg", style={"fontSize": "0.78rem", "color": MUTED,
                                         "minHeight": "18px", "marginBottom": "10px"}),

        # tabs
        html.Div([
            html.Button(t.title(), id={"type": "ib-tab", "v": v}, n_clicks=0,
                        style=BTN_GHOST)
            for t, v in [("Calculation", "calc"), ("Hourly rates", "wage"),
                         ("Staart", "staart"), ("Quote & levies", "quote"), ("Report", "report")]
        ], style={"display": "flex", "gap": "6px", "marginBottom": "12px", "flexWrap": "wrap"}),

        html.Div(id="ib-content"),
    ], style={"padding": "18px 22px", "maxWidth": "1280px"})


# --------------------------------------------------------------------------- #
# tab renderers  (all take the parsed model + compute result R + ccy context)
# --------------------------------------------------------------------------- #
def _th(txt, right=False):
    return html.Th(txt, style={"textAlign": "right" if right else "left", "padding": "6px 8px",
                               "fontSize": "0.7rem", "color": MUTED, "borderBottom": f"2px solid {LINE}",
                               "position": "sticky", "top": 0, "background": "#fff"})


def _td(child, right=False, **extra):
    st = {"padding": "5px 8px", "fontSize": "0.8rem", "textAlign": "right" if right else "left",
          "borderBottom": f"1px solid {LINE}"}
    st.update(extra)
    return html.Td(child, style=st)


def _mfmt(v, cc):
    return _money(v, cc["ccy"], cc["valutas"], cc["calc"])


def _path_of(m, n):
    out, x = [], m.parent.get(n.id)
    while x is not None:
        out.append(m.nodes[x].desc)
        x = m.parent.get(x)
    return list(reversed(out))


def _calc_tab(m, R, cc, expanded, typesel, linefilter, descriptions):
    expanded = set(expanded or [])
    chips = [html.Button(t, id={"type": "ib-chip", "t": t}, n_clicks=0,
                         style={**BTN_GHOST, "borderColor": CAT_COLOR[t],
                                "color": "#fff" if t in typesel else CAT_COLOR[t],
                                "background": CAT_COLOR[t] if t in typesel else "#fff"})
             for t in TYPES]
    controls = html.Div([
        dcc.Dropdown(id="ib-linefilter-dd",
                     options=[{"label": d, "value": d} for d in descriptions],
                     value=linefilter, clearable=True,
                     placeholder="filter: pick a line to see it in every position…",
                     style={"flex": "1 1 340px", "minWidth": "260px", "fontSize": "0.8rem"}),
        html.Div(chips, style={"display": "flex", "gap": "6px", "flexWrap": "wrap"}),
    ], style={"display": "flex", "gap": "12px", "alignItems": "center",
              "justifyContent": "space-between", "flexWrap": "wrap", "marginBottom": "8px"})

    head = html.Thead(html.Tr([
        _th("LINE"), _th("DESCRIPTION"), _th("LOCATION"), _th("VESSEL"),
        _th("AANTAL", True), _th("UREN", True), _th("UNIT PRICE", True),
        _th("COST PRICE", True), _th("MARKUP", True), _th("NET PRICE", True)]))

    rows = []
    if linefilter:
        occ = [n for n in m.nodes.values()
               if not n.group and n.desc == linefilter and n.costlines]
        for n in occ:
            rows.extend(_leaf_rows(m, n, cc, indent=0, path=_path_of(m, n)))
        foottotal = sum((n.net or 0) * m.eff_mult(n.id) for n in occ)
        footlabel = (f"Filtered net total — {len(occ)} occurrence"
                     f"{'' if len(occ) == 1 else 's'} of “{linefilter}”, multiplicity-adjusted")
    else:
        def walk(nid):
            n = m.nodes[nid]
            if typesel and not _node_has_type(m, n, typesel):
                return
            if n.group:
                is_exp = nid in expanded
                mult = (_badge(f"× {n.mult:g}", "#7c3aed")
                        if (n.mult is not None and abs(n.mult - 1) > 1e-6) else "")
                caret = "▾ " if is_exp else "▸ "
                rows.append(html.Tr([
                    _td(html.Span(n.num, style={"color": MUTED, "fontFamily": "ui-monospace,monospace"})),
                    _td([html.Span(caret, style={"color": TEAL, "fontWeight": 700}),
                         html.B(n.desc), mult], paddingLeft=f"{12 + n.level * 16}px"),
                    _td(""), _td(""), _td("", right=True), _td("", right=True), _td("", right=True),
                    _td(html.B(_mfmt(n.cost, cc)), right=True, color=COST_FG),
                    _td("", right=True),
                    _td(html.B(_mfmt(n.net, cc)), right=True, color=NET_FG),
                ], id={"type": "ib-drill", "id": nid}, n_clicks=0, className="ib-grouprow",
                    style={"background": PANEL2, "cursor": "pointer"}))
                if is_exp:
                    for c in n.children:
                        walk(c)
            else:
                rows.extend(_leaf_rows(m, n, cc, indent=n.level))
        for t in m.top:
            walk(t)
        foottotal = sum((m.nodes[t].net or 0) for t in m.top)
        footlabel = "Net total (all chapters, before Staart)"

    if not rows:
        rows = [html.Tr([_td("No lines match the current filter.", color=MUTED)])]

    hint = ("Showing every position of the selected line. Clear the filter to return to the tree."
            if linefilter else
            "Click a chapter to collapse/expand it in place; click a line's description to see that "
            "line in every position. Location and Vessel are click-to-toggle (Local↔Foreign, "
            "vessel on/off) and are written back to the .xtb on save. Aantal / Unit Price / Markup "
            "are editable — Personnel unit price is wage-derived (read-only).")

    return html.Div([
        controls,
        html.Div(html.Table([head, html.Tbody(rows)],
                            style={"width": "100%", "borderCollapse": "collapse", "background": "#fff"}),
                 style={"maxHeight": "56vh", "overflow": "auto", "border": f"1px solid {LINE}",
                        "borderRadius": "10px"}),
        html.Div([html.Span(footlabel + ": ", style={"color": MUTED}),
                  html.B(_mfmt(foottotal, cc), style={"color": NET_FG})],
                 style={"marginTop": "8px", "fontSize": "0.85rem"}),
        html.Div(hint, style={"fontSize": "0.72rem", "color": MUTED, "marginTop": "4px"}),
    ])


def _node_has_type(m, n, typesel):
    if not n.group:
        return any(cl["type"] in typesel for cl in n.costlines)
    stack = list(n.children)
    while stack:
        c = m.nodes[stack.pop()]
        if c.group:
            stack.extend(c.children)
        elif any(cl["type"] in typesel for cl in c.costlines):
            return True
    return False


def _leaf_rows(m, n, cc, indent=0, path=None):
    """One row per cost line. Location (LocatieCode) and Vessel (ALT code) plus
    the numeric editors sit on the first row; extra cost types add rows beneath.
    The description is clickable to filter on that line across the calculation."""
    out = []
    cls = ibis.node_class(n)
    loc_txt = cls["origin"]
    ves_txt = "✓" if cls["vessel"] else ""
    first = True
    for cl in n.costlines:
        num_cell = aantal_cell = uren_cell = loc_cell = ves_cell = ""
        if first:
            num_cell = html.Span(n.num, style={"color": MUTED, "fontFamily": "ui-monospace,monospace"})
            aantal_cell = dcc.Input(id={"type": "ib-ed", "id": n.id, "f": "aantal", "cat": "_"},
                                    value=n.aantal, type="number", debounce=True, style=CELL)
            uren_cell = _num(n.hours) if n.hours else ""
            loc_cell = html.Span(loc_txt, id={"type": "ib-loc", "id": n.id}, title="click to toggle",
                                 style={"color": "#b45309" if loc_txt == "Foreign" else "#334155",
                                        "fontSize": "0.72rem", "fontWeight": 600, "cursor": "pointer",
                                        "borderBottom": "1px dotted #cbd5e1"})
            ves_cell = html.Span(ves_txt or "—", id={"type": "ib-ves", "id": n.id},
                                 title="click to toggle",
                                 style={"color": TEAL if ves_txt else "#cbd5e1", "fontWeight": 700,
                                        "cursor": "pointer"})
        if cl["type"] == "Personnel":
            unit_cell = html.Span(_mfmt(cl["unit"], cc), style={"color": MUTED})
        else:
            unit_cell = dcc.Input(id={"type": "ib-ed", "id": n.id, "f": "unit", "cat": cl["cat"]},
                                  value=round(cl["unit"], 5) if cl["unit"] is not None else None,
                                  type="number", debounce=True, style=CELL)
        mk_cell = dcc.Input(id={"type": "ib-ed", "id": n.id, "f": "markup", "cat": cl["cat"]},
                            value=cl["markup"], type="number", debounce=True,
                            style={**CELL, "width": "58px"})
        if first:
            desc_children = []
            if path:
                desc_children.append(html.Span(" › ".join(path) + "  ",
                                               style={"color": MUTED, "fontSize": "0.68rem"}))
            desc_children.append(html.A(n.desc, id={"type": "ib-linepick", "id": n.id},
                                        style={"cursor": "pointer", "color": INK}))
            desc_children.append(_badge(cl["type"], CAT_COLOR[cl["type"]]))
        else:
            desc_children = [_badge(cl["type"], CAT_COLOR[cl["type"]])]
        out.append(html.Tr([
            _td(num_cell),
            _td(desc_children, paddingLeft=f"{12 + indent * 16}px"),
            _td(loc_cell), _td(ves_cell),
            _td(aantal_cell, right=True),
            _td(uren_cell, right=True, color=MUTED),
            _td(unit_cell, right=True),
            _td(_mfmt(cl["cost"], cc), right=True, color=COST_FG),
            _td(mk_cell, right=True),
            _td(_mfmt(cl["net"], cc), right=True, color=NET_FG),
        ]))
        first = False
    return out


def _wage_tab(m, wages_override, cc):
    rows = []
    for w in sorted(m.wages, key=lambda a: (a["desc"] or "")):
        rate = wages_override.get(w["code"], w["rate"])
        rows.append(html.Tr([
            _td(html.Code(w["code"])),
            _td(w["desc"] or ""),
            _td(_num(w["hours"]), right=True, color=MUTED),
            _td(dcc.Input(id={"type": "ib-wage", "code": w["code"]}, value=round(rate, 5) if rate else rate,
                          type="number", debounce=True, style=CELL), right=True),
            _td(_mfmt((rate or 0) * 12, cc), right=True, color=MUTED),
            _td(_mfmt((rate or 0) * (w["hours"] or 0), cc), right=True, color=NET_FG),
        ]))
    return html.Div([
        html.P("Editing a rate updates every Personnel line built from that wage code, "
               "live. Written into the .xtb on export.", style={"fontSize": "0.78rem", "color": MUTED}),
        html.Div(html.Table([
            html.Thead(html.Tr([_th("Code"), _th("Description"), _th("Hours", True),
                                _th("Hourly rate", True), _th("Day rate (12h)", True),
                                _th("Labour cost", True)])),
            html.Tbody(rows),
        ], style={"width": "100%", "borderCollapse": "collapse", "background": "#fff"}),
            style={"maxHeight": "60vh", "overflow": "auto", "border": f"1px solid {LINE}",
                   "borderRadius": "10px"}),
    ])


def _staart_tab(m, R, cc):
    top = R["top"]
    rows = []
    running = R["sells_base"]
    for i, s in enumerate(top):
        amt = running * (s["pct"] or 0)
        running += amt
        rows.append(html.Tr([
            _td(s["name"] or ""),
            _td(dcc.Input(id={"type": "ib-st", "i": i}, value=round((s["pct"] or 0) * 100, 4),
                          type="number", debounce=True, style={**CELL, "width": "64px"}), right=True),
            _td(_mfmt(amt, cc), right=True, color=NET_FG),
        ]))
    return html.Div([
        html.P(["Staart compounds on the sell price. Effective rate ",
                html.B(f"{R['sr'] * 100:.4f}%"),
                ". Edit a percentage to recompute; written into the .xtb only if changed."],
               style={"fontSize": "0.78rem", "color": MUTED}),
        html.Div([html.Span("Net of line items (sales): ", style={"color": MUTED}),
                  html.B(_mfmt(R["sells_base"], cc))], style={"marginBottom": "8px", "fontSize": "0.85rem"}),
        html.Table([
            html.Thead(html.Tr([_th("Component"), _th("Rate %", True), _th("Amount", True)])),
            html.Tbody(rows + [
                html.Tr([_td(html.B("Staart total")), _td(""),
                         _td(html.B(_mfmt(R["staart_amt"], cc)), right=True, color=NET_FG)],
                        style={"background": PANEL2}),
                html.Tr([_td(html.B("Gross total (excl. BTW)")), _td(""),
                         _td(html.B(_mfmt(R["gross"], cc)), right=True, color=NET_FG)],
                        style={"background": PANEL2}),
            ]),
        ], style={"width": "100%", "borderCollapse": "collapse", "background": "#fff",
                  "border": f"1px solid {LINE}", "borderRadius": "10px"}),
    ])


def _quote_tab(m, R, cc, levies):
    presets = ibis.bid_presets()
    preset_bar = [html.Span("Bid presets: ", style={"color": MUTED, "fontSize": "0.78rem"})]
    for key, p in presets.items():
        preset_bar.append(html.Button(p["name"], id={"type": "ib-preset", "k": key}, n_clicks=0,
                                       style={**BTN_GHOST, "fontSize": "0.75rem"}))
    preset_bar.append(html.Button("Clear", id={"type": "ib-preset", "k": "_clear"}, n_clicks=0,
                                   style={**BTN_GHOST, "fontSize": "0.75rem", "color": "#b91c1c"}))
    preset_bar.append(html.Span("Levies are quote/Excel-only — the staart (overhead / profit / CAR) "
                                "stays in the .xtb and is shown on its own tab.",
                                style={"color": MUTED, "fontSize": "0.72rem", "flexBasis": "100%",
                                       "marginTop": "2px"}))

    lrows = []
    for i, lv in enumerate(levies):
        is_vat = lv.get("vat")
        scope = html.Span("whole total (VAT)", style={"color": MUTED, "fontSize": "0.75rem"}) if is_vat else html.Span([
            dcc.Dropdown(id={"type": "ib-lv", "i": i, "f": "origin"}, value=lv.get("origin", "any"),
                         options=[{"label": o, "value": o} for o in ("any", "foreign", "local")],
                         clearable=False, style={"width": "96px", "display": "inline-block",
                                                 "fontSize": "0.75rem"}),
            dcc.Dropdown(id={"type": "ib-lv", "i": i, "f": "asset"}, value=lv.get("asset", "any"),
                         options=[{"label": o, "value": o} for o in ("any", "vessel", "nonvessel")],
                         clearable=False, style={"width": "110px", "display": "inline-block",
                                                 "fontSize": "0.75rem", "marginLeft": "4px"}),
        ], style={"display": "flex"})
        per_cells = []
        for cat in ibis.CATKEYS:
            if is_vat:
                per_cells.append(_td("", right=True))
            else:
                per_cells.append(_td(dcc.Input(
                    id={"type": "ib-lvper", "i": i, "cat": cat},
                    value=(lv.get("per") or {}).get(cat), type="number", debounce=True,
                    placeholder="–", style={**CELL, "width": "48px"}), right=True))
        lrows.append(html.Tr([
            _td(dcc.Input(id={"type": "ib-lv", "i": i, "f": "name"}, value=lv.get("name", ""),
                          debounce=True, style={**CELL, "width": "140px", "textAlign": "left"})),
            _td(scope),
            _td(dcc.Input(id={"type": "ib-lv", "i": i, "f": "rate"}, value=lv.get("rate", 0),
                          type="number", debounce=True, style={**CELL, "width": "56px"}), right=True),
            *per_cells,
            _td(_mfmt(R["amt_by_idx"].get(i, 0), cc), right=True, color=NET_FG),
            _td(html.Span("✕", id={"type": "ib-lvdel", "i": i},
                          style={"color": "#b91c1c", "cursor": "pointer", "fontWeight": 700})),
        ]))
    if not lrows:
        lrows = [html.Tr([_td("No levies. Apply a bid preset or add one.", color=MUTED)])]

    # build-up
    build = [("Cost base (sales)", None, R["sells_base"]),
             ("Staart (overhead / profit / CAR)", R["staart_amt"], R["gross"])]
    for s in R["steps"]:
        build.append((s["lv"]["name"], s["amt"], s["running"]))
    build.append(("Totaal excl BTW", None, R["excl"]))
    build.append(("Totaal incl BTW (quote)", None, R["incl"]))
    brows = []
    for label, amt, run in build:
        strong = label.startswith("Totaal")
        brows.append(html.Tr([
            _td(html.B(label) if strong else label),
            _td(_mfmt(amt, cc) if amt is not None else "", right=True, color=NET_FG),
            _td(html.B(_mfmt(run, cc)) if strong else _mfmt(run, cc), right=True),
        ]))

    return html.Div([
        html.Div(preset_bar, style={"display": "flex", "gap": "6px", "flexWrap": "wrap",
                                    "alignItems": "center", "marginBottom": "10px"}),
        html.Table([
            html.Thead(html.Tr([_th("Levy"), _th("Scope"), _th("Rate %", True),
                                *[_th(c[:4], True) for c in ("Pers", "Equip", "Matl", "Subc")],
                                _th("Amount", True), _th("")])),
            html.Tbody(lrows),
        ], style={"width": "100%", "borderCollapse": "collapse", "background": "#fff",
                  "border": f"1px solid {LINE}", "borderRadius": "10px", "marginBottom": "6px"}),
        html.Button("+ Add levy", id="ib-lvadd", n_clicks=0, style={**BTN_GHOST, "marginBottom": "14px"}),
        html.H4("Quote build-up", style={"color": INK, "fontSize": "0.9rem"}),
        html.Table([
            html.Thead(html.Tr([_th("Component"), _th("Amount", True), _th("Running", True)])),
            html.Tbody(brows),
        ], style={"width": "100%", "borderCollapse": "collapse", "background": "#fff",
                  "border": f"1px solid {LINE}", "borderRadius": "10px"}),
    ])


def _report_tab(m, cc, rep):
    items = ibis.report_items(m)
    mode = rep.get("mode", "cat")
    head = [html.Button("By cost type", id={"type": "ib-rmode", "m": "cat"}, n_clicks=0,
                        style={**BTN_GHOST, "background": TEAL if mode == "cat" else "#fff",
                               "color": "#fff" if mode == "cat" else INK}),
            html.Button("By group", id={"type": "ib-rmode", "m": "group"}, n_clicks=0,
                        style={**BTN_GHOST, "background": TEAL if mode == "group" else "#fff",
                               "color": "#fff" if mode == "group" else INK})]
    body = None
    if mode == "cat":
        cat, res = rep.get("cat"), rep.get("res")
        if not cat:
            agg = {}
            for it in items:
                a = agg.setdefault(it["cat"], {"n": 0, "cost": 0, "net": 0})
                a["n"] += 1
                a["cost"] += it["cost"]
                a["net"] += it["net"]
            rows = []
            tc = tn = 0
            for c in ibis.CATKEYS:
                if c not in agg:
                    continue
                a = agg[c]
                tc += a["cost"]
                tn += a["net"]
                rows.append(html.Tr([
                    _td(html.A(["▸ ", ibis.QLBL[c]], id={"type": "ib-rcat", "c": c},
                               style={"color": INK, "cursor": "pointer"})),
                    _td(a["n"], right=True, color=MUTED),
                    _td(_mfmt(a["cost"], cc), right=True, color=COST_FG),
                    _td(_mfmt(a["net"], cc), right=True, color=NET_FG),
                ], style={"background": PANEL2}))
            rows.append(html.Tr([_td(html.B("Total")), _td(""),
                                 _td(_mfmt(tc, cc), right=True), _td(html.B(_mfmt(tn, cc)), right=True)]))
            body = html.Table([html.Thead(html.Tr([_th("Cost type"), _th("Lines", True),
                                                   _th("Cost", True), _th("Sales", True)])),
                               html.Tbody(rows)], style=_TBL)
        elif not res:
            agg = {}
            for it in [x for x in items if x["cat"] == cat]:
                a = agg.setdefault(it["res"], {"n": 0, "qty": 0, "cost": 0, "net": 0})
                a["n"] += 1
                a["qty"] += it["qty"] or 0
                a["cost"] += it["cost"]
                a["net"] += it["net"]
            rows = [html.Tr([
                _td(html.A(res_, id={"type": "ib-rres", "r": res_}, style={"color": TEAL, "cursor": "pointer"})),
                _td(a["n"], right=True, color=MUTED), _td(_num(a["qty"]), right=True, color=MUTED),
                _td(_mfmt(a["cost"], cc), right=True, color=COST_FG),
                _td(_mfmt(a["net"], cc), right=True, color=NET_FG),
            ]) for res_, a in sorted(agg.items(), key=lambda e: -e[1]["net"])]
            body = html.Div([
                html.Div([html.A(ibis.QLBL[cat], id={"type": "ib-rcat", "c": "_back"},
                                 style={"color": TEAL, "cursor": "pointer"})],
                         style={"fontSize": "0.8rem", "marginBottom": "6px"}),
                html.Table([html.Thead(html.Tr([_th("Resource"), _th("Occurrences", True),
                                                _th("Qty", True), _th("Cost", True), _th("Sales", True)])),
                            html.Tbody(rows)], style=_TBL)])
        else:
            rows = [html.Tr([
                _td(" › ".join(it["path"])),
                _td(_num(it["qty"]), right=True),
                _td((f"{it['markup']:.1f}%" if it["markup"] is not None else ""), right=True),
                _td(_mfmt(it["cost"], cc), right=True, color=COST_FG),
                _td(_mfmt(it["net"], cc), right=True, color=NET_FG),
            ]) for it in items if it["cat"] == cat and it["res"] == res]
            body = html.Div([
                html.Div([html.A(ibis.QLBL[cat], id={"type": "ib-rcat", "c": cat},
                                 style={"color": TEAL, "cursor": "pointer"}),
                          html.Span(" › " + res, style={"color": MUTED})],
                         style={"fontSize": "0.8rem", "marginBottom": "6px"}),
                html.Table([html.Thead(html.Tr([_th("Location (path)"), _th("Qty", True),
                                                _th("Markup", True), _th("Cost", True), _th("Sales", True)])),
                            html.Tbody(rows)], style=_TBL)])
    else:
        rpath = rep.get("path", [])
        scope = rpath[-1] if rpath else None
        kids = m.nodes[scope].children if scope else m.top
        crumbs = [html.A("Calculation", id={"type": "ib-rgrp", "i": -1},
                         style={"color": TEAL, "cursor": "pointer"})]
        for i, nid in enumerate(rpath):
            crumbs += [html.Span(" › ", style={"color": MUTED}),
                       html.A(f"{m.nodes[nid].num} {m.nodes[nid].desc}", id={"type": "ib-rgrp", "i": i},
                              style={"color": TEAL, "cursor": "pointer"})]
        rows = []
        for nid in kids:
            n = m.nodes[nid]
            if n.group:
                rows.append(html.Tr([
                    _td(html.A(["▸ ", (n.num + " " if n.num else ""), n.desc],
                               id={"type": "ib-rdrill", "id": nid}, style={"color": INK, "cursor": "pointer"})),
                    _td(_mfmt(n.cost, cc), right=True, color=COST_FG),
                    _td(_mfmt(n.net, cc), right=True, color=NET_FG),
                ], style={"background": PANEL2}))
            else:
                rows.append(html.Tr([_td(n.desc), _td(_mfmt(n.cost, cc), right=True, color=COST_FG),
                                     _td(_mfmt(n.net, cc), right=True, color=NET_FG)]))
        body = html.Div([
            html.Div(crumbs, style={"fontSize": "0.8rem", "marginBottom": "6px"}),
            html.Table([html.Thead(html.Tr([_th("Description"), _th("Cost", True), _th("Sales", True)])),
                        html.Tbody(rows)], style=_TBL)])
    return html.Div([html.Div(head, style={"display": "flex", "gap": "6px", "marginBottom": "10px"}), body])


_TBL = {"width": "100%", "borderCollapse": "collapse", "background": "#fff",
        "border": f"1px solid {LINE}", "borderRadius": "10px"}


# --------------------------------------------------------------------------- #
# main render callback
# --------------------------------------------------------------------------- #
@callback(
    Output("ib-name", "children"), Output("ib-sub", "children"),
    Output("ib-c-cost", "children"), Output("ib-c-markup", "children"),
    Output("ib-c-staart", "children"), Output("ib-c-levy", "children"),
    Output("ib-c-net", "children"), Output("ib-content", "children"),
    Input("ib-file", "data"), Input("ib-ccy-sel", "value"), Input("ib-view", "data"),
    Input("ib-expanded", "data"), Input("ib-typesel", "data"), Input("ib-linefilter", "data"),
    Input("ib-edits", "data"), Input("ib-wages", "data"), Input("ib-levies", "data"),
    Input("ib-staart", "data"), Input("ib-report", "data"), Input("ib-classedits", "data"),
)
def _render(fstore, ccy, view, expanded, typesel, linefilter, edits, wages, levies,
            staart, rep, classedits):
    if not fstore or not fstore.get("b64"):
        return ("Drop an IBIS .xtb here to begin", "", "—", "—", "—", "—", "—", None)
    raw, m = _model(fstore)
    ibis.apply_class_edits(m, classedits or {})
    calc = m.header["calc_ccy"]
    ccy = ccy or calc
    cc = {"ccy": ccy, "calc": calc, "valutas": m.valutas}
    R = ibis.compute(m, edits=edits or {}, staart_override=staart, levies=levies or [])
    # apply wage overrides for display of Personnel unit prices
    if wages:
        _apply_wages(m, wages)
        R = ibis.compute(m, edits=edits or {}, staart_override=staart, levies=levies or [])
    hc = ibis.header_cards(R)

    if view == "wage":
        content = _wage_tab(m, wages or {}, cc)
    elif view == "staart":
        content = _staart_tab(m, R, cc)
    elif view == "quote":
        content = _quote_tab(m, R, cc, levies or [])
    elif view == "report":
        content = _report_tab(m, cc, rep or {"mode": "cat"})
    else:
        descriptions = sorted({n.desc for n in m.nodes.values()
                               if not n.group and n.costlines and n.desc})
        content = _calc_tab(m, R, cc, expanded or [], typesel or [], linefilter, descriptions)

    sub = (f"IBIS calculation · version {m.header['versie']} · "
           f"{str(m.header['datum']).replace('T', ' ')} · calc currency {calc}")
    return (m.header["name"], sub, _mfmt(hc["cost"], cc), _mfmt(hc["markup"], cc),
            _mfmt(hc["staart"], cc), _mfmt(hc["levy"], cc), _mfmt(hc["net"], cc), content)


def _apply_wages(m, wages):
    """Rewrite Personnel cost-line unit prices from edited wage rates x norm."""
    by_code = {w["code"]: w for w in m.wages}
    for n in m.nodes.values():
        if n.group or not n.uurloon_code:
            continue
        nr = wages.get(n.uurloon_code)
        if nr is None:
            continue
        a = n.aantal
        norm = (n.uren_raw / a) if (a and abs(a) > 1e-9) else n.uren_raw
        for cl in n.costlines:
            if cl["type"] == "Personnel":
                cl["unit"] = nr * norm if (a and abs(a) > 1e-9) else nr * n.uren_raw
                cl["cost"] = ibis.r2(cl["unit"] * a) if (a and abs(a) > 1e-9) else ibis.r2(cl["unit"])
                f = 1.0 if cl["markup"] is None else (1 + cl["markup"] / 100)
                cl["net"] = ibis.r2(cl["cost"] * f)


# --------------------------------------------------------------------------- #
# upload + currency + tabs
# --------------------------------------------------------------------------- #
@callback(Output("ib-file", "data"),
          Output("ib-ccy-sel", "options"), Output("ib-ccy-sel", "value"),
          Output("ib-edits", "data"), Output("ib-wages", "data"),
          Output("ib-levies", "data"), Output("ib-staart", "data"),
          Output("ib-expanded", "data"), Output("ib-linefilter", "data"),
          Output("ib-classedits", "data"), Output("ib-msg", "children"),
          Input("ib-upload", "contents"), State("ib-upload", "filename"),
          prevent_initial_call=True)
def _upload(contents, filename):
    if not contents:
        return (no_update,) * 11
    try:
        _hdr, payload = contents.split(",", 1)
        raw = base64.b64decode(payload)
        m = ibis.load(raw)
        opts = [{"label": c, "value": c} for c in m.valutas]
        expanded = [nid for nid, n in m.nodes.items() if n.group]  # fully expanded on load
        msg = f"{filename} — loaded. {m.header['name']} v{m.header['versie']}, {len(m.nodes)} lines."
        # Levies start EMPTY: they live outside the .xtb and only in the quote/Excel.
        # The staart (Algemene kosten / Winst en Risico / CAR) stays in the .xtb and
        # drives the STAART card + Staart tab - it is never a levy.
        return ({"name": filename, "b64": payload}, opts, m.header["calc_ccy"],
                {}, {}, [], None, expanded, None, {}, msg)
    except Exception as e:
        return (no_update, no_update, no_update, no_update, no_update, no_update,
                no_update, no_update, no_update, no_update, f"Could not read this file: {e}")


@callback(Output("ib-view", "data"), Input({"type": "ib-tab", "v": ALL}, "n_clicks"),
          prevent_initial_call=True)
def _tab(_n):
    t = ctx.triggered_id
    return t["v"] if t and any(_n) else no_update


# --- expand / collapse tree + line filter ---------------------------------- #
@callback(Output("ib-expanded", "data", allow_duplicate=True),
          Input({"type": "ib-drill", "id": ALL}, "n_clicks"),
          State("ib-expanded", "data"), prevent_initial_call=True)
def _expand(_n, expanded):
    t = ctx.triggered_id
    if not t or not any(v for v in _n if v):
        return no_update
    exp = list(expanded or [])
    if t["id"] in exp:
        exp.remove(t["id"])
    else:
        exp.append(t["id"])
    return exp


@callback(Output("ib-linefilter", "data", allow_duplicate=True),
          Input("ib-linefilter-dd", "value"), prevent_initial_call=True)
def _linefilter(v):
    return v


@callback(Output("ib-linefilter", "data", allow_duplicate=True),
          Input({"type": "ib-linepick", "id": ALL}, "n_clicks"),
          State("ib-file", "data"), prevent_initial_call=True)
def _linepick(_n, fstore):
    t = ctx.triggered_id
    if not t or not any(v for v in _n if v) or not fstore:
        return no_update
    _raw, m = _model(fstore)
    n = m.nodes.get(t["id"])
    return n.desc if n else no_update


@callback(Output("ib-typesel", "data"), Input({"type": "ib-chip", "t": ALL}, "n_clicks"),
          State("ib-typesel", "data"), prevent_initial_call=True)
def _chip(_n, sel):
    t = ctx.triggered_id
    if not t or not any(_n):
        return no_update
    sel = list(sel or [])
    if t["t"] in sel:
        sel.remove(t["t"])
    else:
        sel.append(t["t"])
    return sel


@callback(Output("ib-classedits", "data", allow_duplicate=True),
          Input({"type": "ib-loc", "id": ALL}, "n_clicks"),
          State("ib-file", "data"), State("ib-classedits", "data"),
          prevent_initial_call=True)
def _loc_toggle(_n, fstore, ce):
    t = ctx.triggered_id
    if not t or not any(v for v in _n if v) or not fstore:
        return no_update
    _raw, m = _model(fstore)
    n = m.nodes.get(t["id"])
    if not n:
        return no_update
    ce = dict(ce or {})
    key = str(t["id"])
    cur = ce.get(key, {}).get("loc", n.loc or "")
    newloc = ibis.LOC_LOCAL if (cur or "").lower() == "foreign" else ibis.LOC_FOREIGN
    ce[key] = {**ce.get(key, {}), "loc": newloc}
    return ce


@callback(Output("ib-classedits", "data", allow_duplicate=True),
          Input({"type": "ib-ves", "id": ALL}, "n_clicks"),
          State("ib-file", "data"), State("ib-classedits", "data"),
          prevent_initial_call=True)
def _ves_toggle(_n, fstore, ce):
    t = ctx.triggered_id
    if not t or not any(v for v in _n if v) or not fstore:
        return no_update
    _raw, m = _model(fstore)
    n = m.nodes.get(t["id"])
    if not n:
        return no_update
    ce = dict(ce or {})
    key = str(t["id"])
    cur = ce.get(key, {}).get("alt", n.alt or "")
    newalt = ibis.ALT_NONE if (cur or "").lower() == "vsl" else ibis.ALT_VESSEL
    ce[key] = {**ce.get(key, {}), "alt": newalt}
    return ce


# --- edits ----------------------------------------------------------------- #
@callback(Output("ib-edits", "data", allow_duplicate=True),
          Input({"type": "ib-ed", "id": ALL, "f": ALL, "cat": ALL}, "value"),
          State({"type": "ib-ed", "id": ALL, "f": ALL, "cat": ALL}, "id"),
          State("ib-edits", "data"), prevent_initial_call=True)
def _edit(values, ids, edits):
    if not ctx.triggered:
        return no_update
    edits = dict(edits or {})
    for val, cid in zip(values, ids):
        lid = str(cid["id"])
        e = edits.setdefault(lid, {})
        if cid["f"] == "aantal":
            e["aantal"] = val
        elif cid["f"] == "unit":
            e.setdefault("unit", {})[cid["cat"]] = val
        elif cid["f"] == "markup":
            e.setdefault("markup", {})[cid["cat"]] = val
    return edits


@callback(Output("ib-wages", "data", allow_duplicate=True),
          Input({"type": "ib-wage", "code": ALL}, "value"),
          State({"type": "ib-wage", "code": ALL}, "id"),
          prevent_initial_call=True)
def _wage_edit(values, ids):
    if not ctx.triggered:
        return no_update
    return {cid["code"]: v for v, cid in zip(values, ids) if v is not None}


@callback(Output("ib-staart", "data", allow_duplicate=True),
          Input({"type": "ib-st", "i": ALL}, "value"),
          State({"type": "ib-st", "i": ALL}, "id"),
          State("ib-file", "data"), State("ib-staart", "data"),
          prevent_initial_call=True)
def _staart_edit(values, ids, fstore, cur):
    if not ctx.triggered or not fstore:
        return no_update
    _raw, m = _model(fstore)
    base = ibis.staart_top(m, cur)
    out = []
    for s, cid in zip(base, ids):
        v = dict(s)
        v["pct"] = (values[cid["i"]] or 0) / 100
        out.append(v)
    return out


# --- levies ---------------------------------------------------------------- #
@callback(Output("ib-levies", "data", allow_duplicate=True),
          Input({"type": "ib-preset", "k": ALL}, "n_clicks"),
          prevent_initial_call=True)
def _preset(_n):
    t = ctx.triggered_id
    if not t or not any(_n):
        return no_update
    k = t["k"]
    if k == "_clear":
        return []
    p = ibis.bid_presets().get(k)
    return [dict(x) for x in p["levies"]] if p else no_update


@callback(Output("ib-levies", "data", allow_duplicate=True),
          Input({"type": "ib-lv", "i": ALL, "f": ALL}, "value"),
          Input({"type": "ib-lvper", "i": ALL, "cat": ALL}, "value"),
          Input({"type": "ib-lvdel", "i": ALL}, "n_clicks"),
          Input("ib-lvadd", "n_clicks"),
          State({"type": "ib-lv", "i": ALL, "f": ALL}, "id"),
          State({"type": "ib-lvper", "i": ALL, "cat": ALL}, "id"),
          State("ib-levies", "data"), prevent_initial_call=True)
def _levy_edit(fvals, pvals, dels, add, fids, pids, levies):
    t = ctx.triggered_id
    levies = [dict(x) for x in (levies or [])]
    if t == "ib-lvadd":
        levies.append({"name": "New levy", "origin": "any", "asset": "any", "rate": 0, "per": {}})
        return levies
    if isinstance(t, dict) and t.get("type") == "ib-lvdel":
        if any(dels):
            i = t["i"]
            if 0 <= i < len(levies):
                levies.pop(i)
        return levies
    # field / per edits
    for v, cid in zip(fvals, fids):
        i, f = cid["i"], cid["f"]
        if i < len(levies):
            levies[i][f] = (float(v) if (v not in (None, "") and f == "rate") else v)
    for v, cid in zip(pvals, pids):
        i, cat = cid["i"], cid["cat"]
        if i < len(levies):
            per = dict(levies[i].get("per") or {})
            if v in (None, ""):
                per.pop(cat, None)
            else:
                per[cat] = float(v)
            levies[i]["per"] = per
    return levies


# --- report navigation ----------------------------------------------------- #
@callback(Output("ib-report", "data"),
          Input({"type": "ib-rmode", "m": ALL}, "n_clicks"),
          Input({"type": "ib-rcat", "c": ALL}, "n_clicks"),
          Input({"type": "ib-rres", "r": ALL}, "n_clicks"),
          Input({"type": "ib-rgrp", "i": ALL}, "n_clicks"),
          Input({"type": "ib-rdrill", "id": ALL}, "n_clicks"),
          State("ib-report", "data"), prevent_initial_call=True)
def _report_nav(rm, rc, rr, rg, rd, rep):
    t = ctx.triggered_id
    if not t:
        return no_update
    rep = dict(rep or {"mode": "cat", "cat": None, "res": None, "path": []})
    typ = t["type"]
    if typ == "ib-rmode" and any(rm):
        rep = {"mode": t["m"], "cat": None, "res": None, "path": []}
    elif typ == "ib-rcat" and any(rc):
        rep["cat"] = None if t["c"] == "_back" else t["c"]
        rep["res"] = None
    elif typ == "ib-rres" and any(rr):
        rep["res"] = t["r"]
    elif typ == "ib-rgrp" and any(rg):
        i = t["i"]
        rep["path"] = [] if i < 0 else (rep.get("path") or [])[:i + 1]
    elif typ == "ib-rdrill" and any(rd):
        rep["path"] = (rep.get("path") or []) + [t["id"]]
    else:
        return no_update
    return rep


# --- reset ----------------------------------------------------------------- #
@callback(Output("ib-edits", "data", allow_duplicate=True),
          Output("ib-wages", "data", allow_duplicate=True),
          Output("ib-staart", "data", allow_duplicate=True),
          Output("ib-classedits", "data", allow_duplicate=True),
          Output("ib-msg", "children", allow_duplicate=True),
          Input("ib-btn-reset", "n_clicks"), prevent_initial_call=True)
def _reset(_n):
    return {}, {}, None, {}, "Edits reset to the loaded file."


# --------------------------------------------------------------------------- #
# downloads
# --------------------------------------------------------------------------- #
@callback(Output("ib-dl-xlsx", "data"), Output("ib-msg", "children", allow_duplicate=True),
          Input("ib-btn-xlsx", "n_clicks"),
          State("ib-file", "data"), State("ib-edits", "data"), State("ib-wages", "data"),
          State("ib-levies", "data"), State("ib-staart", "data"), State("ib-ccy-sel", "value"),
          State("ib-classedits", "data"),
          prevent_initial_call=True)
def _dl_xlsx(_n, fstore, edits, wages, levies, staart, ccy, classedits):
    if not fstore:
        return no_update, "Load a file first."
    _raw, m = _model(fstore)
    ibis.apply_class_edits(m, classedits or {})
    if wages:
        _apply_wages(m, wages)
    R = ibis.compute(m, edits=edits or {}, staart_override=staart, levies=levies or [])
    wr = {**{w["code"]: w["rate"] for w in m.wages}, **(wages or {})}
    ccy = ccy or m.header["calc_ccy"]
    xb = ibis.to_xlsx(m, R, wage_rates=wr, ccy=ccy, valutas=m.valutas, calc=m.header["calc_ccy"])
    fname = ("".join(ch if ch.isalnum() else "_" for ch in (m.header["name"] or "quote"))
             + f"_quote_{ccy}.xlsx")
    return dcc.send_bytes(lambda buf: buf.write(xb), fname), f"Exported {fname}"


@callback(Output("ib-dl-xtb", "data"), Output("ib-msg", "children", allow_duplicate=True),
          Input("ib-btn-xtb", "n_clicks"),
          State("ib-file", "data"), State("ib-edits", "data"), State("ib-wages", "data"),
          State("ib-staart", "data"), State("ib-classedits", "data"),
          prevent_initial_call=True)
def _dl_xtb(_n, fstore, edits, wages, staart, classedits):
    if not fstore:
        return no_update, "Load a file first."
    raw, m = _model(fstore)
    nb = ibis.write_xtb(raw, m, edits=edits or {}, wage_rates=wages or {},
                        staart_override=staart, class_edits=classedits or {})
    base = fstore.get("name", "calculation.xtb")
    fname = base[:-4] + "_amended.xtb" if base.endswith(".xtb") else base + "_amended.xtb"
    return dcc.send_bytes(lambda buf: buf.write(nb), fname), f"Wrote {fname} (version bumped; original untouched)."
