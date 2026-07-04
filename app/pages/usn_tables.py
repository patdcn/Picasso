"""
Air MG Diving - US Navy decompression tables.

Presents the US Navy Diving Manual (Rev 7) tables, read from a finalized JSON on
the /data volume (USN_TABLES_JSON, default /data/tools/usn/usn_tables.json). Pick a
table (and depth, for the air decompression table); toggle ft/m; print. Copyright
data stays off the repo; until the JSON is staged the page shows a "not loaded" note.

Loaded: Air No-Decompression Limits (Table 9-7) and the Air Decompression Table
(Table 9-9, which carries both in-water air and surface-decompression / SurDO2).
Nitrox (N2O2), HeO2 and shallow-water tables extract from the same source and are
added as further entries in usn_tables.json.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, clientside_callback, ALL, ctx, no_update

from app import reports
from app.engines import usn_tables as usn
from app.engines import profile_chart
from app.engines import profiles

dash.register_page(__name__, path="/air-diving/usn-tables", name="US Navy Tables",
                   category="Air MG Diving", order=2)

INK = "#1f2937"
MUTED = "#6b7280"
TEAL = "#0f766e"
LINE = "#d1d5db"
HEAD = "#dbe4ec"
GRID = "#94a3b8"
FRAME = "#334155"
FT_TO_M = 0.3048

PDF_BTN_STYLE = {"padding": "8px 14px", "borderRadius": "8px", "border": "none",
                 "background": TEAL, "color": "#fff", "fontWeight": 600,
                 "cursor": "pointer", "fontSize": "0.85rem"}


# ------- unit helpers -------
def _depth(fsw, unit):
    try:
        f = float(fsw)
    except (TypeError, ValueError):
        return fsw
    return f"{f*FT_TO_M:.1f}" if unit == "m" else f"{int(f) if f == int(f) else f}"

def _ulabel(unit):
    return "m" if unit == "m" else "fsw"


def _table_options():
    return [{"label": t["label"], "value": t["code"]} for t in usn.ui_tables()]


def layout():
    tabs = usn.ui_tables()
    default = tabs[0]["code"] if tabs else None
    return html.Div([
        reports.print_header(),
        html.Div([
            html.Button([html.Span("\u2913\u2002"), "Export to PDF"], id="usn-print-btn",
                        n_clicks=0, style=PDF_BTN_STYLE,
                        title="Opens your browser's print dialog \u2014 choose 'Save as PDF'"),
            html.Div(id="usn-print-sink", style={"display": "none"}),
        ], className="no-print",
           style={"display": "flex", "justifyContent": "flex-end", "marginBottom": "2px"}),

        html.H3("US Navy Decompression Tables"),
        html.P("US Navy Diving Manual (Rev 7). Select a table to view and print it. Figures are "
               "indicative, for commercial planning only \u2014 not for operational decompression.",
               style={"color": MUTED, "maxWidth": "72ch", "lineHeight": 1.5}),

        html.Div([
            html.Div([
                html.Label("Table", style={"fontSize": "0.78rem", "fontWeight": 600,
                                           "color": INK, "display": "block", "marginBottom": "3px"}),
                dcc.Dropdown(id="usn-table", options=_table_options(), value=default,
                             clearable=False, style={"fontSize": "0.82rem"}),
            ], style={"width": "440px"}),
            html.Div([
                html.Label("Depth", style={"fontSize": "0.78rem", "fontWeight": 600,
                                           "color": INK, "display": "block", "marginBottom": "3px"}),
                dcc.Dropdown(id="usn-depth", options=[], value=None, clearable=False,
                             style={"fontSize": "0.82rem"}),
            ], id="usn-depth-wrap", style={"width": "150px", "display": "none"}),
            html.Div([
                html.Label("Units", style={"fontSize": "0.78rem", "fontWeight": 600,
                                           "color": INK, "display": "block", "marginBottom": "3px"}),
                dcc.RadioItems(id="usn-unit",
                               options=[{"label": " ft", "value": "ft"}, {"label": " m", "value": "m"}],
                               value="ft", inline=True,
                               inputStyle={"marginRight": "4px"},
                               labelStyle={"marginRight": "12px", "fontSize": "0.85rem"}),
            ]),
            html.Div([
                html.Label("Profile", style={"fontSize": "0.78rem", "fontWeight": 600,
                                             "color": INK, "display": "block", "marginBottom": "3px"}),
                dcc.RadioItems(id="usn-mode",
                               options=[{"label": " in-water", "value": "inwater"},
                                        {"label": " SurDO2", "value": "surdo2"}],
                               value="inwater", inline=True,
                               inputStyle={"marginRight": "4px"},
                               labelStyle={"marginRight": "12px", "fontSize": "0.85rem"}),
            ], id="usn-mode-wrap", style={"display": "none"}),
            html.Div([
                html.Div([
                    html.Label("Repetitive dive \u2014 previous group",
                               style={"fontSize": "0.78rem", "fontWeight": 600, "color": INK,
                                      "display": "block", "marginBottom": "3px"}),
                    dcc.Dropdown(id="usn-rep-prev",
                                 options=[{"label": "none (single dive)", "value": ""}] +
                                         [{"label": f"group {g}", "value": g} for g in "ABCDEFGHIJKLMNO"] +
                                         [{"label": "group Z", "value": "Z"}],
                                 value="", clearable=False, style={"fontSize": "0.8rem"}),
                ], style={"width": "210px"}),
                html.Div([
                    html.Label("Surface interval (h:mm)",
                               style={"fontSize": "0.78rem", "fontWeight": 600, "color": INK,
                                      "display": "block", "marginBottom": "3px"}),
                    dcc.Input(id="usn-rep-si", type="text", placeholder="e.g. 1:30", value="",
                              debounce=True, style={"width": "100%", "padding": "7px 9px",
                                                    "borderRadius": "8px", "border": "1px solid #d1d5db",
                                                    "boxSizing": "border-box", "fontSize": "0.85rem"}),
                ], style={"width": "130px"}),
            ], id="usn-rep-wrap", style={"display": "none"}),
        ], className="no-print",
           style={"display": "flex", "gap": "18px", "alignItems": "flex-end",
                  "flexWrap": "wrap", "marginTop": "8px", "marginBottom": "6px"}),

        html.Div(id="usn-output", style={"marginTop": "14px"}),
        dcc.Store(id="usn-sel"),
        html.Div(id="usn-chart", style={"marginTop": "10px"}),
        reports.print_footer(),
    ])


def _not_loaded():
    return html.Div([
        html.H4("Tables not loaded", style={"color": INK, "marginBottom": "6px"}),
        html.P(["No US Navy table data found. Stage ", html.Code("usn_tables.json"),
                " to ", html.Code("/data/tools/usn/"), " (Admin \u2192 Data volume) and reload."],
               style={"color": MUTED, "maxWidth": "60ch", "lineHeight": 1.5}),
    ], style={"padding": "18px", "border": f"1px dashed {LINE}", "borderRadius": "10px",
              "background": "#f8fafc"})


def _rules_header(t, extra_sub=None):
    sub = [html.Span("US Navy Diving Manual Rev 7", style={"color": MUTED})]
    if t.get("subtitle"):
        sub.append(html.Span(f"\u2002\u00b7\u2002{t['subtitle']}", style={"color": MUTED}))
    if extra_sub:
        sub.append(html.Span(f"\u2002\u00b7\u2002{extra_sub}", style={"color": INK}))
    right = html.Ul([html.Li(r) for r in t.get("rules", [])],
                    style={"margin": 0, "paddingLeft": "16px", "color": MUTED,
                           "fontSize": "0.78rem", "lineHeight": 1.4, "listStyle": "square",
                           "maxWidth": "64ch"})
    return html.Div([
        html.Div([html.Div(t.get("title", t["code"]),
                           style={"fontWeight": 700, "fontSize": "0.98rem", "color": INK}),
                  html.Div(sub, style={"fontSize": "0.85rem", "marginTop": "2px"})],
                 style={"flex": "1 1 auto"}),
        html.Div(right, style={"flex": "0 0 auto"}),
    ], style={"display": "flex", "gap": "24px", "alignItems": "flex-start",
              "justifyContent": "space-between", "flexWrap": "wrap",
              "border": f"1px solid {LINE}", "borderLeft": f"4px solid {TEAL}",
              "background": "#f8fafc", "borderRadius": "6px", "padding": "10px 14px",
              "marginBottom": "12px"})


_TH = {"border": f"1px solid {GRID}", "padding": "4px 7px", "background": HEAD,
       "fontSize": "0.73rem", "fontWeight": 700, "color": "#1e293b",
       "textAlign": "center", "verticalAlign": "middle"}
_TD = {"border": f"1px solid {GRID}", "padding": "3px 7px", "fontSize": "0.8rem",
       "textAlign": "center", "fontFamily": "ui-monospace,monospace", "color": INK}


def _cell(v, extra=None):
    st = dict(_TD)
    if extra:
        st.update(extra)
    return html.Td("" if v is None or v == "" else v, style=st)


def _wrap(table):
    return html.Div(table, style={"overflowX": "auto", "maxWidth": "100%"})


# ---- no-decompression style grid ----
def _grid(t, unit):
    cols = list(t["columns"])
    dvc = set(t.get("depth_value_cols", []))
    unat = t.get("unit_native", "fsw")
    # header: swap the (fsw) unit token in depth column headers when metric
    def hdr(i):
        h = cols[i]
        if i in dvc and unit == "m":
            h = h.replace("(fsw)", "(m)")
        return h
    gf = t.get("group_from")
    if gf is not None:
        top = [html.Th(hdr(i), rowSpan=2, style=_TH) for i in range(gf)]
        top.append(html.Th(t.get("group_label", ""), colSpan=len(cols) - gf, style=_TH))
        sub = [html.Th(cols[i], style=_TH) for i in range(gf, len(cols))]
        thead = html.Thead([html.Tr(top), html.Tr(sub)])
    else:
        thead = html.Thead(html.Tr([html.Th(hdr(i), style=_TH) for i in range(len(cols))]))
    body = []
    for r in t["rows"]:
        cells = []
        for i, v in enumerate(r):
            disp = _depth(v, unit) if (i in dvc and unit == "m") else v
            extra = {"fontWeight": 700, "background": HEAD} if i == 0 else \
                    {"fontWeight": 600} if i == 1 else {}
            cells.append(_cell(disp, extra))
        body.append(html.Tr(cells))
    return _wrap(html.Table([thead, html.Tbody(body)],
                            style={"borderCollapse": "collapse", "border": f"2px solid {FRAME}"}))


# ---- air decompression per-depth block ----
def _block(t, block, unit, sel_i=None, rnt=None):
    return _block_air(t, block, unit, sel_i, rnt) if t.get("variant") == "air" \
        else _block_simple(t, block, unit, sel_i)


def _bt_num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_si(s):
    """Parse a surface interval 'h:mm' or plain minutes -> minutes (int), or None."""
    if not s or not str(s).strip():
        return None
    s = str(s).strip()
    try:
        if ":" in s:
            h, m = s.split(":", 1)
            return int(h or 0) * 60 + int(m or 0)
        return int(round(float(s)))
    except (TypeError, ValueError):
        return None


def _rep_note(text, tone="teal"):
    bg, bd = ("#e6f2f1", TEAL) if tone == "teal" else ("#fef3c7", "#b45309")
    if tone == "muted":
        bg, bd = "#f3f4f6", "#9ca3af"
    return html.Div(text, className="no-print",
                    style={"background": bg, "border": f"1px solid {bd}", "borderRadius": "8px",
                           "padding": "8px 12px", "margin": "6px 0", "fontSize": "0.85rem"})


def _rep_banner(prev, si_str, si_min, newg, clean, rnt, depth, unit):
    dlab = f"{_depth(depth, unit)} {_ulabel(unit)}"
    if si_min is None:
        return _rep_note([html.Span("Repetitive dive  ", style={"fontWeight": 700}),
                          f"previous group {prev} \u2014 enter a surface interval (h:mm) to compute "
                          "the new group and residual nitrogen time."], tone="muted")
    si_lab = f"{si_min // 60}:{si_min % 60:02d}"
    if si_min < 10:
        return _rep_note([html.Span("Repetitive dive  ", style={"fontWeight": 700}),
                          f"surface interval {si_lab} is under 0:10 \u2014 the USN treats this as one "
                          "continuous dive (add bottom times, use the deeper depth), not a repetitive "
                          "dive."], tone="amber")
    if clean:
        return _rep_note([html.Span("Repetitive dive  ", style={"fontWeight": 700}),
                          f"previous group {prev} \u00b7 surface interval {si_lab} \u2192 no residual "
                          "nitrogen. The interval is long enough that this is not a repetitive dive \u2014 "
                          "use actual bottom times. All schedules shown."], tone="teal")
    body = [html.Span("Repetitive dive  ", style={"fontWeight": 700}),
            html.Span(f"group {prev} \u00b7 surface interval {si_lab} \u2192 "),
            html.Span(f"new group {newg}", style={"fontWeight": 700, "color": TEAL}),
            html.Span(f" \u00b7 residual N\u2082 time at {dlab} = {rnt} min" if rnt is not None
                      else " \u00b7 RNT not determinable at this depth (see NDM 9-9.1)")]
    tail = html.Div("The bottom-time column is total bottom time (RNT + actual). Schedules whose total "
                    "is \u2264 RNT are hidden; \u201cact\u201d is the actual bottom time left after "
                    "residual nitrogen.", style={"fontSize": "0.76rem", "color": MUTED, "marginTop": "3px"})
    return _rep_note([html.Div(body), tail] if rnt is not None else [html.Div(body)],
                     tone="teal" if rnt is not None else "amber")


def _highlight(cells):
    for c in cells:
        c.style = {**(c.style or {}), "background": "#d1eee9", "color": TEAL,
                   "fontWeight": 700, "borderTop": f"2px solid {TEAL}",
                   "borderBottom": f"2px solid {TEAL}"}


def _block_air(t, block, unit, sel_i=None, rnt=None):
    sd = t["stop_depths"]
    ncol = 3 + len(sd) + 3
    thead = html.Thead([
        html.Tr([
            html.Th("bottom time (min)", rowSpan=2, style=_TH),
            html.Th("to 1st stop (M:SS)", rowSpan=2, style=_TH),
            html.Th("gas mix", rowSpan=2, style=_TH),
            html.Th(f"decompression stops ({_ulabel(unit)})", colSpan=len(sd), style=_TH),
            html.Th("total ascent (M:SS)", rowSpan=2, style=_TH),
            html.Th("chamber O\u2082 periods", rowSpan=2, style=_TH),
            html.Th("repet group", rowSpan=2, style=_TH),
        ]),
        html.Tr([html.Th(_depth(d, unit), style=_TH) for d in sd]),
    ])
    body = []
    skip_pair = False
    for i, r in enumerate(block["rows"]):
        typ = r.get("type")
        if typ == "divider":
            body.append(_divider_row(r, ncol))
            skip_pair = False
            continue
        is_air = typ == "air"
        btn = _bt_num(r.get("bt")) if is_air else None
        if is_air:
            skip_pair = rnt is not None and btn is not None and btn <= rnt
        if skip_pair:                       # hide this air row and its paired air/O2 row
            continue
        rb = {} if is_air else {"background": "#f1f5f9"}
        bt_content = r.get("bt", "")
        if is_air and rnt is not None and btn is not None:
            bt_content = html.Span([
                html.Span(str(r.get("bt", ""))), html.Br(),
                html.Span(f"act {int(round(btn - rnt))}",
                          style={"fontSize": "0.68rem", "color": TEAL, "fontWeight": 600})])
        cells = [_cell(bt_content, {"fontWeight": 700, "background": HEAD} if is_air else rb),
                 _cell(r.get("tfs", ""), rb),
                 _cell(r.get("gas", ""), {"fontWeight": 600, **rb})]
        stops = r.get("stops", {})
        for d in sd:
            cells.append(_cell(stops.get(str(d), ""), {"background": "#fbfdff", **rb}))
        cells.append(_cell(r.get("tat", ""), {"color": TEAL, "fontWeight": 600, **rb}))
        cells.append(_cell(r.get("periods", ""), rb))
        cells.append(_cell(r.get("group", ""), {"fontWeight": 600, **rb}))
        if i == sel_i:
            _highlight(cells)
        body.append(html.Tr(cells, id={"type": "usn-prow", "i": i}, n_clicks=0,
                            className="usn-prow", style={"cursor": "pointer"}))
    return _wrap(html.Table([thead, html.Tbody(body)],
                            style={"borderCollapse": "collapse", "border": f"2px solid {FRAME}"}))


def _block_simple(t, block, unit, sel_i=None):
    sd = t["stop_depths"]
    ncol = 2 + len(sd) + 2
    thead = html.Thead([
        html.Tr([
            html.Th("bottom time (min)", rowSpan=2, style=_TH),
            html.Th("to 1st stop (M:SS)", rowSpan=2, style=_TH),
            html.Th(f"decompression stops ({_ulabel(unit)})", colSpan=len(sd), style=_TH),
            html.Th("total ascent (M:SS)", rowSpan=2, style=_TH),
            html.Th("repet group", rowSpan=2, style=_TH),
        ]),
        html.Tr([html.Th(_depth(d, unit), style=_TH) for d in sd]),
    ])
    body = []
    for i, r in enumerate(block["rows"]):
        if r.get("type") == "divider":
            body.append(_divider_row(r, ncol))
            continue
        cells = [_cell(r.get("bt", ""), {"fontWeight": 700, "background": HEAD}),
                 _cell(r.get("tfs", ""))]
        stops = r.get("stops", {})
        for d in sd:
            cells.append(_cell(stops.get(str(d), ""), {"background": "#fbfdff"}))
        cells.append(_cell(r.get("tat", ""), {"color": TEAL, "fontWeight": 600}))
        cells.append(_cell(r.get("group", ""), {"fontWeight": 600}))
        if i == sel_i:
            _highlight(cells)
        body.append(html.Tr(cells, id={"type": "usn-prow", "i": i}, n_clicks=0,
                            className="usn-prow", style={"cursor": "pointer"}))
    return _wrap(html.Table([thead, html.Tbody(body)],
                            style={"borderCollapse": "collapse", "border": f"2px solid {FRAME}"}))


def _divider_row(r, ncol):
    return html.Tr([html.Td(
        r.get("text", ""), colSpan=ncol,
        style={"border": f"1px solid {GRID}", "background": "#0f172a",
               "color": "#fbbf24", "fontSize": "0.7rem", "fontWeight": 700,
               "padding": "2px 8px", "textAlign": "left"})])


# ------- callbacks -------
@callback(
    Output("usn-depth", "options"),
    Output("usn-depth", "value"),
    Output("usn-depth-wrap", "style"),
    Output("usn-mode-wrap", "style"),
    Output("usn-rep-wrap", "style"),
    Input("usn-table", "value"),
    Input("usn-unit", "value"),
)
def _depths(code, unit):
    depths = usn.ui_depths(code)
    hidden = {"width": "150px", "display": "none"}
    shown = {"width": "150px", "display": "block"}
    t = usn.ui_table(code) if code else None
    is_air = bool(t and t.get("variant") == "air")
    mode_style = {"display": "block"} if is_air else {"display": "none"}
    rep_style = {"display": "flex", "gap": "12px"} if is_air else {"display": "none"}
    if not depths:
        return [], None, hidden, mode_style, rep_style
    opts = [{"label": f"{_depth(d, unit)} {_ulabel(unit)}", "value": d} for d in depths]
    return opts, depths[0], shown, mode_style, rep_style


@callback(
    Output("usn-output", "children"),
    Input("usn-table", "value"),
    Input("usn-depth", "value"),
    Input("usn-unit", "value"),
    Input("usn-sel", "data"),
    Input("usn-rep-prev", "value"),
    Input("usn-rep-si", "value"),
)
def _show(code, depth, unit, sel, prev, si_str):
    if not code:
        return _not_loaded()
    t = usn.ui_table(code)
    if not t:
        return _not_loaded()
    if t.get("kind") == "deco_blocks":
        res = usn.ui_block(code, depth)
        blk = res and res.get("block")
        if not blk:
            return _not_loaded()
        sel_i = sel["i"] if (sel and sel.get("code") == code and sel.get("depth") == depth) else None
        is_air = t.get("variant") == "air"
        rnt = newg = None
        clean = False
        si_min = None
        if is_air and prev:
            si_min = _parse_si(si_str)
            if si_min is not None and si_min >= 10:
                newg = usn.new_group_air(prev, si_min)
                if newg is None:
                    clean = True
                else:
                    rnt = usn.rnt_for(newg, blk["depth"])
        sub = f"maximum diving depth {_depth(blk['depth'], unit)} {_ulabel(unit)}"
        children = [_rules_header(t, sub)]
        if is_air and prev:
            children.append(_rep_banner(prev, si_str, si_min, newg, clean, rnt, blk["depth"], unit))
        children.append(_block(t, blk, unit, sel_i, rnt))
        return html.Div(children, className="usn-table-print")
    return html.Div([_rules_header(t), _grid(t, unit)], className="usn-table-print")


def _chart_hint(show):
    if not show:
        return None
    return html.Div("Tip: click any schedule row above to plot that row's dive profile here. "
                    "For the air table, switch Profile to SurDO2 to see the surface-decompression run.",
                    className="no-print",
                    style={"color": MUTED, "fontSize": "0.82rem", "fontStyle": "italic",
                           "marginTop": "4px"})


@callback(
    Output("usn-sel", "data"),
    Input({"type": "usn-prow", "i": ALL}, "n_clicks"),
    State("usn-table", "value"),
    State("usn-depth", "value"),
    prevent_initial_call=True,
)
def _select_row(_nclicks, code, depth):
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or not ctx.triggered or not ctx.triggered[0]["value"]:
        return no_update
    return {"code": code, "depth": depth, "i": trig["i"]}


@callback(
    Output("usn-sel", "data", allow_duplicate=True),
    Input("usn-table", "value"),
    Input("usn-depth", "value"),
    prevent_initial_call=True,
)
def _clear_sel(_code, _depth):
    return None


@callback(
    Output("usn-chart", "children"),
    Input("usn-sel", "data"),
    Input("usn-unit", "value"),
    Input("usn-mode", "value"),
    State("usn-table", "value"),
)
def _chart(sel, unit, mode, code):
    t = usn.ui_table(code) if code else None
    is_deco = bool(t and t.get("kind") == "deco_blocks")
    if not sel:
        return _chart_hint(is_deco)
    res = usn.ui_block(sel["code"], sel["depth"])
    blk = res and res.get("block")
    if not t or not blk:
        return _chart_hint(is_deco)
    mode = mode if (t.get("variant") == "air") else "inwater"
    legs = profiles.usn_legs(t, blk, sel["i"], mode)
    if not legs:
        return _chart_hint(is_deco)
    disp = "m" if unit == "m" else "ft"
    dval = _depth(blk["depth"], unit)
    kind = "SurDO2" if mode == "surdo2" else "dive"
    fig = profile_chart.build_figure(
        legs, native_unit="fsw", display_unit=disp,
        title=f"{t['title']} \u2014 {dval} {_ulabel(unit)} {kind} profile")
    return dcc.Graph(figure=fig, config={"displayModeBar": False},
                     style={"height": "410px"})


clientside_callback(
    "function(n){ if(n){ setTimeout(function(){ window.print(); }, 60); } "
    "return window.dash_clientside.no_update; }",
    Output("usn-print-sink", "children"),
    Input("usn-print-btn", "n_clicks"),
    prevent_initial_call=True,
)
