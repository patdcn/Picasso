"""
Air MG Diving - US Navy decompression tables.

Presents the US Navy Diving Manual (Rev 7) tables, read from a finalized JSON on
the /data volume (USN_TABLES_JSON, default /data/tools/usn/usn_tables.json). Pick a
table from the dropdown to view and print it. Copyright data stays off the repo;
until the JSON is staged the page shows a "not loaded" note.

Currently loaded: Air No-Decompression Limits & Repetitive Groups (Table 9-7).
The air decompression table (9-9), surface-decompression (SurDO2 / SurDair) and
nitrox (N2O2) tables extract cleanly from the same source and will be added next.
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

PDF_BTN_STYLE = {
    "padding": "8px 14px", "borderRadius": "8px", "border": "none",
    "background": TEAL, "color": "#fff", "fontWeight": 600,
    "cursor": "pointer", "fontSize": "0.85rem",
}


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
        html.P("US Navy Diving Manual (Rev 7). Select a table to view and print it. "
               "Figures are indicative, for commercial planning only \u2014 not for operational "
               "decompression.",
               style={"color": MUTED, "maxWidth": "72ch", "lineHeight": 1.5}),

        html.Div([
            html.Label("Table", style={"fontSize": "0.78rem", "fontWeight": 600,
                                       "color": INK, "display": "block", "marginBottom": "3px"}),
            dcc.Dropdown(id="usn-table", options=_table_options(), value=default,
                         clearable=False, style={"fontSize": "0.82rem"}),
        ], className="no-print", style={"width": "460px", "marginTop": "8px",
                                        "marginBottom": "6px"}),

        html.Div(id="usn-output", style={"marginTop": "14px"}),
        reports.print_footer(),
    ])


def _not_loaded():
    return html.Div([
        html.H4("Tables not loaded", style={"color": INK, "marginBottom": "6px"}),
        html.P(["No US Navy table data found on the volume. Stage ",
                html.Code("usn_tables.json"), " to ", html.Code("/data/tools/usn/"),
                " (Admin \u2192 Data volume) and reload."],
               style={"color": MUTED, "maxWidth": "60ch", "lineHeight": 1.5}),
    ], style={"padding": "18px", "border": f"1px dashed {LINE}", "borderRadius": "10px",
              "background": "#f8fafc"})


def _rules_header(t):
    left = [html.Div(t.get("title", t["code"]),
                     style={"fontWeight": 700, "fontSize": "0.98rem", "color": INK}),
            html.Div([html.Span("US Navy Diving Manual Rev 7", style={"color": MUTED}),
                      *( [html.Span(f"\u2002\u00b7\u2002{t['subtitle']}", style={"color": MUTED})]
                         if t.get("subtitle") else [])],
                     style={"fontSize": "0.85rem", "marginTop": "2px"})]
    right = html.Ul([html.Li(r) for r in t.get("rules", [])],
                    style={"margin": 0, "paddingLeft": "16px", "color": MUTED,
                           "fontSize": "0.78rem", "lineHeight": 1.4, "listStyle": "square",
                           "maxWidth": "64ch"})
    return html.Div([
        html.Div(left, style={"flex": "1 1 auto"}),
        html.Div(right, style={"flex": "0 0 auto"}),
    ], style={"display": "flex", "gap": "24px", "alignItems": "flex-start",
              "justifyContent": "space-between", "flexWrap": "wrap",
              "border": f"1px solid {LINE}", "borderLeft": f"4px solid {TEAL}",
              "background": "#f8fafc", "borderRadius": "6px", "padding": "10px 14px",
              "marginBottom": "12px"})


_TH = {"border": f"1px solid {GRID}", "padding": "4px 7px", "background": HEAD,
       "fontSize": "0.74rem", "fontWeight": 700, "color": "#1e293b",
       "textAlign": "center", "verticalAlign": "middle"}
_TD = {"border": f"1px solid {GRID}", "padding": "3px 7px", "fontSize": "0.8rem",
       "textAlign": "center", "fontFamily": "ui-monospace,monospace", "color": INK}


def _cell(v, extra=None):
    st = dict(_TD)
    if extra:
        st.update(extra)
    return html.Td("" if v is None or v == "" else v, style=st)


def _grid(t):
    cols = t["columns"]
    gf = t.get("group_from")
    if gf is not None:
        top = [html.Th(cols[i], rowSpan=2, style=_TH) for i in range(gf)]
        top.append(html.Th(t.get("group_label", ""), colSpan=len(cols) - gf, style=_TH))
        sub = [html.Th(cols[i], style=_TH) for i in range(gf, len(cols))]
        thead = html.Thead([html.Tr(top), html.Tr(sub)])
    else:
        thead = html.Thead(html.Tr([html.Th(c, style=_TH) for c in cols]))
    body = []
    for r in t["rows"]:
        cells = []
        for i, v in enumerate(r):
            extra = {"fontWeight": 700, "background": HEAD} if i == 0 else \
                    {"fontWeight": 600} if i == 1 else {}
            cells.append(_cell(v, extra))
        body.append(html.Tr(cells))
    table = html.Table([thead, html.Tbody(body)],
                       style={"borderCollapse": "collapse", "border": f"2px solid {FRAME}"})
    # wide tables scroll horizontally on screen; print CSS lays them out full width
    return html.Div(table, style={"overflowX": "auto", "maxWidth": "100%"})


def _render(t):
    return html.Div([_rules_header(t), _grid(t)], className="usn-table-print")


@callback(
    Output("usn-output", "children"),
    Input("usn-table", "value"),
)
def _show(code):
    if not code:
        return _not_loaded()
    t = usn.ui_table(code)
    if not t:
        return _not_loaded()
    return _render(t)


clientside_callback(
    "function(n){ if(n){ setTimeout(function(){ window.print(); }, 60); } "
    "return window.dash_clientside.no_update; }",
    Output("usn-print-sink", "children"),
    Input("usn-print-btn", "n_clicks"),
    prevent_initial_call=True,
)
