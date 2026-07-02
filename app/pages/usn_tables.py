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
from dash import html, dcc, Input, Output, callback, clientside_callback

from app import reports
from app.engines import usn_tables as usn

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
        ], className="no-print",
           style={"display": "flex", "gap": "18px", "alignItems": "flex-end",
                  "flexWrap": "wrap", "marginTop": "8px", "marginBottom": "6px"}),

        html.Div(id="usn-output", style={"marginTop": "14px"}),
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
def _block(t, block, unit):
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
    for r in block["rows"]:
        if r.get("type") == "divider":
            body.append(html.Tr([html.Td(
                r.get("text", ""), colSpan=ncol,
                style={"border": f"1px solid {GRID}", "background": "#0f172a",
                       "color": "#fbbf24", "fontSize": "0.7rem", "fontWeight": 700,
                       "padding": "2px 8px", "textAlign": "left"})]))
            continue
        is_air = r.get("type") == "air"
        rb = {} if is_air else {"background": "#f1f5f9"}
        cells = [_cell(r.get("bt", ""), {"fontWeight": 700, "background": HEAD} if is_air else rb),
                 _cell(r.get("tfs", ""), rb),
                 _cell(r.get("gas", ""), {"fontWeight": 600, **rb})]
        stops = r.get("stops", {})
        for d in sd:
            cells.append(_cell(stops.get(str(d), ""), {"background": "#fbfdff", **rb}))
        cells.append(_cell(r.get("tat", ""), {"color": TEAL, "fontWeight": 600, **rb}))
        cells.append(_cell(r.get("periods", ""), rb))
        cells.append(_cell(r.get("group", ""), {"fontWeight": 600, **rb}))
        body.append(html.Tr(cells))
    return _wrap(html.Table([thead, html.Tbody(body)],
                            style={"borderCollapse": "collapse", "border": f"2px solid {FRAME}"}))


# ------- callbacks -------
@callback(
    Output("usn-depth", "options"),
    Output("usn-depth", "value"),
    Output("usn-depth-wrap", "style"),
    Input("usn-table", "value"),
    Input("usn-unit", "value"),
)
def _depths(code, unit):
    depths = usn.ui_depths(code)
    hidden = {"width": "150px", "display": "none"}
    shown = {"width": "150px", "display": "block"}
    if not depths:
        return [], None, hidden
    opts = [{"label": f"{_depth(d, unit)} {_ulabel(unit)}", "value": d} for d in depths]
    return opts, depths[0], shown


@callback(
    Output("usn-output", "children"),
    Input("usn-table", "value"),
    Input("usn-depth", "value"),
    Input("usn-unit", "value"),
)
def _show(code, depth, unit):
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
        sub = f"maximum diving depth {_depth(blk['depth'], unit)} {_ulabel(unit)}"
        return html.Div([_rules_header(t, sub), _block(t, blk, unit)], className="usn-table-print")
    return html.Div([_rules_header(t), _grid(t, unit)], className="usn-table-print")


clientside_callback(
    "function(n){ if(n){ setTimeout(function(){ window.print(); }, 60); } "
    "return window.dash_clientside.no_update; }",
    Output("usn-print-sink", "children"),
    Input("usn-print-btn", "n_clicks"),
    prevent_initial_call=True,
)
