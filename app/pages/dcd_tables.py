"""
Air MG Diving - DCD (decompression) tables.

Presents the finalized DCD 2015 tables (N-Sea / W. Sterk) in the same layout as
the source: a rules header (ascent speed, stop-time rule, repetitive interval)
followed by the decompression grid, with the bold air-backup line shown. Pick a
family and depth from the dropdowns; "Export to PDF" prints the selected table
with the DCN letterhead.

The table data is copyright, so it is NOT bundled in the repo. The page reads a
finalized JSON from the /data volume (DCD_TABLES_JSON, default
/data/tools/dcd/dcd_tables.json). Until that file is staged the page shows a
"not loaded" note instead of failing.
"""
import dash
from dash import html, dcc, Input, Output, callback, clientside_callback

from app import reports
from app.engines import dcd_tables as dcd

dash.register_page(__name__, path="/air-diving/dcd-tables", name="DCD Tables",
                   category="Air MG Diving", order=1)

INK = "#1f2937"
MUTED = "#6b7280"
TEAL = "#0f766e"
LINE = "#d1d5db"
BACKUP_BG = "#f1f5f9"
HEAD_BG = "#f8fafc"

PDF_BTN_STYLE = {
    "padding": "8px 14px", "borderRadius": "8px", "border": "none",
    "background": TEAL, "color": "#fff", "fontWeight": 600,
    "cursor": "pointer", "fontSize": "0.85rem",
}


def _dropdown(id_, label, options, value, disabled=False, width="260px"):
    return html.Div([
        html.Label(label, style={"fontSize": "0.78rem", "fontWeight": 600,
                                 "color": INK, "display": "block", "marginBottom": "3px"}),
        dcc.Dropdown(id=id_, options=options, value=value, clearable=False,
                     disabled=disabled, style={"fontSize": "0.85rem"}),
    ], style={"width": width})


def _family_options():
    return [{"label": f["label"], "value": f["code"]} for f in dcd.ui_families()]


def layout():
    fams = dcd.ui_families()
    default_code = fams[0]["code"] if fams else None
    return html.Div([
        reports.print_header(),
        html.Div([
            html.Button([html.Span("\u2913\u2002"), "Export to PDF"], id="dcd-print-btn",
                        n_clicks=0, style=PDF_BTN_STYLE,
                        title="Opens your browser's print dialog \u2014 choose 'Save as PDF'"),
            html.Div(id="dcd-print-sink", style={"display": "none"}),
        ], className="no-print",
           style={"display": "flex", "justifyContent": "flex-end", "marginBottom": "2px"}),

        html.H3("DCD Decompression Tables"),
        html.P("DCD 2015 revised NDC tables. Select a table "
               "family and depth to view and print it. Figures are indicative, for commercial "
               "planning only \u2014 not for operational decompression.",
               style={"color": MUTED, "maxWidth": "72ch", "lineHeight": 1.5}),

        html.Div([
            _dropdown("dcd-standard", "Standard",
                      [{"label": "DCD 2015", "value": "DCD15"}],
                      "DCD15", disabled=True, width="230px"),
            _dropdown("dcd-family", "Table family", _family_options(), default_code, width="360px"),
            _dropdown("dcd-depth", "Depth", [], None, width="150px"),
        ], className="no-print",
           style={"display": "flex", "gap": "16px", "alignItems": "flex-end",
                  "flexWrap": "wrap", "marginTop": "8px", "marginBottom": "6px"}),

        html.Div(id="dcd-table-output", style={"marginTop": "14px"}),
        reports.print_footer(),
    ])


def _not_loaded():
    return html.Div([
        html.H4("Tables not loaded", style={"color": INK, "marginBottom": "6px"}),
        html.P(["No table data found on the volume. Stage the finalized ",
                html.Code("dcd_tables.json"), " to ", html.Code("/data/tools/dcd/"),
                " and reload."],
               style={"color": MUTED, "maxWidth": "60ch", "lineHeight": 1.5}),
    ], style={"padding": "18px", "border": f"1px dashed {LINE}", "borderRadius": "10px",
              "background": HEAD_BG})


def _rules_header(t, depth=None):
    bits = [html.Span(f"Code: {t['code']}", style={"fontWeight": 700, "color": INK})]
    if depth is not None:
        bits.append(html.Span(f"\u2002\u00b7\u2002Maximum diving depth {depth} m",
                              style={"color": INK}))
    rules = html.Ul([html.Li(r, style={"marginBottom": "1px"}) for r in t.get("rules", [])],
                    style={"margin": "6px 0 0 0", "paddingLeft": "18px",
                           "color": MUTED, "fontSize": "0.82rem", "lineHeight": 1.45})
    return html.Div([
        html.Div(t.get("title", t["code"]),
                 style={"fontWeight": 700, "fontSize": "1.02rem", "color": INK}),
        html.Div(bits, style={"fontSize": "0.85rem", "marginTop": "2px"}),
        rules,
    ], style={"marginBottom": "10px"})


_TH = {"border": f"1px solid {LINE}", "padding": "4px 6px", "background": HEAD_BG,
       "fontSize": "0.78rem", "fontWeight": 700, "color": INK, "textAlign": "center"}
_TD = {"border": f"1px solid {LINE}", "padding": "3px 6px", "fontSize": "0.82rem",
       "textAlign": "center", "fontFamily": "monospace", "color": INK}


def _cell(v, extra=None):
    st = dict(_TD)
    if extra:
        st.update(extra)
    return html.Td("" if v is None or v == "" else v, style=st)


def _table(head, body):
    return html.Table([html.Thead(html.Tr(head)), html.Tbody(body)],
                      style={"borderCollapse": "collapse", "marginTop": "4px"})


def _grid_inwater(t, block):
    sd = t["stop_depths"]
    head = ([html.Th("dive", style=_TH), html.Th("1st", style=_TH)]
            + [html.Th(str(d), style=_TH) for d in sd]
            + [html.Th("deco", style=_TH), html.Th("OTU", style=_TH)])
    body, divider_done = [], False
    for r in block["rows"]:
        if r.get("backup") and not divider_done:
            divider_done = True
            body.append(html.Tr([html.Td(
                "\u2014 air backup line (in-water air only as O2 / SurD backup) \u2014",
                colSpan=len(sd) + 4,
                style={"border": f"1px solid {LINE}", "background": "#0f172a",
                       "color": "#fbbf24", "fontSize": "0.72rem", "fontWeight": 700,
                       "padding": "2px 8px", "textAlign": "left"})]))
        row_bg = {"background": BACKUP_BG} if r.get("backup") else {}
        cells = [_cell(r["bt"], {"fontWeight": 700, **row_bg}),
                 _cell(r.get("till"), row_bg)]
        for d in sd:
            cells.append(_cell(r["stops"].get(str(d), ""), {"background": "#fbfcfe", **row_bg}))
        cells.append(_cell(r.get("deco"), {"color": "#0f766e", "fontWeight": 600, **row_bg}))
        cells.append(_cell(r.get("otu"), row_bg))
        body.append(html.Tr(cells))
    return _table(head, body)


def _grid_surfaceox(t, block):
    cols = t["columns"]
    di = t["deco_i"]
    head = [html.Th(c, style=_TH) for c in cols]
    body = []
    for r in block["rows"]:
        cells = []
        for i, _c in enumerate(cols):
            v = r[i] if i < len(r) else ""
            extra = {"fontWeight": 700} if i == 0 else \
                    {"color": "#0f766e", "fontWeight": 600} if i == di else \
                    {"background": "#fbfcfe"} if 1 < i < di else {}
            cells.append(_cell(v, extra))
        body.append(html.Tr(cells))
    return _table(head, body)


def _grid_reference(t):
    head = [html.Th(c, style=_TH) for c in t["columns"]]
    body = []
    for r in t["rows"]:
        cells = [_cell("\u2013" if v is None else v,
                       {"fontWeight": 700} if i == 0 else {}) for i, v in enumerate(r)]
        body.append(html.Tr(cells))
    return _table(head, body)


def _render(t):
    if t["kind"] == "reference":
        return html.Div([_rules_header(t), _grid_reference(t)], className="dcd-table-print")
    block = t.get("block")
    if not block:
        return _not_loaded()
    depth = block["depth"]
    grid = _grid_inwater(t, block) if t["kind"] == "inwater" else _grid_surfaceox(t, block)
    return html.Div([_rules_header(t, depth), grid], className="dcd-table-print")


@callback(
    Output("dcd-depth", "options"),
    Output("dcd-depth", "value"),
    Output("dcd-depth", "disabled"),
    Input("dcd-family", "value"),
)
def _populate_depths(code):
    depths = dcd.ui_depths(code)
    if not depths:
        return [], None, True
    return [{"label": f"{d} m", "value": d} for d in depths], depths[0], False


@callback(
    Output("dcd-table-output", "children"),
    Input("dcd-family", "value"),
    Input("dcd-depth", "value"),
)
def _show(code, depth):
    if not code:
        return _not_loaded()
    t = dcd.ui_table(code, depth)
    if not t:
        return _not_loaded()
    return _render(t)


clientside_callback(
    "function(n){ if(n){ setTimeout(function(){ window.print(); }, 60); } "
    "return window.dash_clientside.no_update; }",
    Output("dcd-print-sink", "children"),
    Input("dcd-print-btn", "n_clicks"),
    prevent_initial_call=True,
)
