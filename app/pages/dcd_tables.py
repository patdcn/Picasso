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
from dash import html, dcc, Input, Output, State, callback, clientside_callback, ALL, ctx, no_update

from app import reports
from app.engines import dcd_tables as dcd
from app.engines import profile_chart
from app.engines import profiles

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
                     disabled=disabled, style={"fontSize": "0.8rem"}),
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
        dcc.Store(id="dcd-sel"),
        html.Div(id="dcd-chart", style={"marginTop": "10px"}),
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
    left = [html.Div(t.get("title", t["code"]),
                     style={"fontWeight": 700, "fontSize": "0.98rem", "color": INK}),
            html.Div([html.Span("Code: ", style={"color": MUTED}),
                      html.Span(t["code"], style={"fontWeight": 700, "letterSpacing": "0.02em"}),
                      *( [html.Span(f"\u2002\u00b7\u2002maximum diving depth {depth} metres",
                                    style={"color": MUTED})] if depth is not None else [])],
                     style={"fontSize": "0.85rem", "marginTop": "2px"})]
    rules = list(t.get("rules", []))
    if t.get("kind") == "surfaceox":
        rules += [
            "The diver must be under pressure in the chamber within 3 minutes of reaching the "
            "surface \u2014 this limit is critical; any delay strongly increases the risk of "
            "decompression sickness.",
            "If the 3-minute limit is exceeded (or the required in-water stops cannot be made), "
            "this table may not be used \u2014 apply the Crash Dive emergency procedure: recompress "
            "to the first in-water stop depth + 9 m, hold 5 min, then decompress on the SIL15 air "
            "table for the actual bottom time + 10 min (breathing O\u2082 from the 12 m stop in "
            "20-min periods with 5-min air breaks, if available). Observe a 12-hour repeat interval "
            "afterwards; all emergency rules apply.",
        ]
    right = html.Ul([html.Li(r) for r in rules],
                    style={"margin": 0, "paddingLeft": "16px", "color": MUTED,
                           "fontSize": "0.78rem", "lineHeight": 1.4, "listStyle": "square",
                           "maxWidth": "62ch"})
    return html.Div([
        html.Div(left, style={"flex": "1 1 auto"}),
        html.Div(right, style={"flex": "0 0 auto"}),
    ], style={"display": "flex", "gap": "24px", "alignItems": "flex-start",
              "justifyContent": "space-between", "flexWrap": "wrap",
              "borderLeft": f"4px solid {TEAL}", "background": "#f8fafc",
              "border": f"1px solid {LINE}", "borderLeftWidth": "4px",
              "borderLeftColor": TEAL, "borderRadius": "6px",
              "padding": "10px 14px", "marginBottom": "12px"})


# --- table styling, tuned to resemble the source DCD tables ---
HEAD = "#dbe4ec"          # slate-blue header, like the printed tables
GRID = "#94a3b8"          # cell borders
FRAME = "#334155"         # dark outer frame
BACKUP_ROW = "#eef2f7"

_TH = {"border": f"1px solid {GRID}", "padding": "4px 7px", "background": HEAD,
       "fontSize": "0.74rem", "fontWeight": 700, "color": "#1e293b",
       "textAlign": "center", "verticalAlign": "middle"}
_TD = {"border": f"1px solid {GRID}", "padding": "3px 7px", "fontSize": "0.82rem",
       "textAlign": "center", "fontFamily": "ui-monospace,monospace", "color": INK}


def _cell(v, extra=None):
    st = dict(_TD)
    if extra:
        st.update(extra)
    return html.Td("" if v is None or v == "" else v, style=st)


def _table(thead, body):
    return html.Table([thead, html.Tbody(body)],
                      style={"borderCollapse": "collapse", "marginTop": "2px",
                             "border": f"2px solid {FRAME}"})


def _highlight(cells):
    for c in cells:
        c.style = {**(c.style or {}), "background": "#d1eee9", "color": TEAL,
                   "fontWeight": 700, "borderTop": f"2px solid {TEAL}",
                   "borderBottom": f"2px solid {TEAL}"}


def _prow(cells, i, sel_i):
    if i == sel_i:
        _highlight(cells)
    return html.Tr(cells, id={"type": "dcd-prow", "i": i}, n_clicks=0,
                   className="dcd-prow", style={"cursor": "pointer"})


def _grid_inwater(t, block, sel_i=None):
    sd = t["stop_depths"]
    thead = html.Thead([
        html.Tr([
            html.Th("dive time", rowSpan=2, style=_TH),
            html.Th("till 1st stop", rowSpan=2, style=_TH),
            html.Th("in-water stops (metres)", colSpan=len(sd), style=_TH),
            html.Th("total deco time", rowSpan=2, style=_TH),
            html.Th("total OTU", rowSpan=2, style=_TH),
        ]),
        html.Tr([html.Th(str(d), style=_TH) for d in sd]),
    ])
    body, bold_done = [], False
    for i, r in enumerate(block["rows"]):
        thick = {}
        if r.get("backup") and not bold_done:
            bold_done = True
            thick = {"borderTop": f"3px solid {FRAME}"}   # the bold air-backup rule
        row_bg = {"background": BACKUP_ROW} if r.get("backup") else {}
        cells = [_cell(r["bt"], {"fontWeight": 700, "background": HEAD, **thick}),
                 _cell(r.get("till"), {**row_bg, **thick})]
        for d in sd:
            cells.append(_cell(r["stops"].get(str(d), ""), {"background": "#fbfdff", **row_bg, **thick}))
        cells.append(_cell(r.get("deco"), {"color": TEAL, "fontWeight": 600, **row_bg, **thick}))
        cells.append(_cell(r.get("otu"), {**row_bg, **thick}))
        body.append(_prow(cells, i, sel_i))
    return html.Div([_table(thead, body),
                     html.Div("Bold rule = air back-up line (in-water air only, as O2 / "
                              "surface-decompression back-up).",
                              style={"fontSize": "0.72rem", "color": MUTED, "marginTop": "5px"})
                     if bold_done else None])


def _grid_surfaceox(t, block, sel_i=None):
    cols = t["columns"]
    di = t["deco_i"]
    iw_idx = [i for i in range(2, di) if cols[i].lower().startswith("iw")]
    ch_idx = [i for i in range(2, di) if not cols[i].lower().startswith("iw")]

    def _depth_label(i):
        lab = cols[i]
        return lab[3:].strip() if lab.lower().startswith("iw ") else lab

    top = [html.Th("dive time", rowSpan=2, style=_TH),
           html.Th("till 1st stop", rowSpan=2, style=_TH)]
    if iw_idx:
        top.append(html.Th("in-water stops (metres)", colSpan=len(iw_idx), style=_TH))
    if ch_idx:
        top.append(html.Th("stops in deco-chamber (metres)", colSpan=len(ch_idx), style=_TH))
    top += [html.Th("total deco time", rowSpan=2, style=_TH),
            html.Th("total OTU", rowSpan=2, style=_TH)]
    sub = [html.Th(_depth_label(i), style=_TH) for i in iw_idx + ch_idx]
    thead = html.Thead([html.Tr(top), html.Tr(sub)])

    body = []
    for j, r in enumerate(block["rows"]):
        cells = [_cell(r[0] if len(r) > 0 else "", {"fontWeight": 700, "background": HEAD}),
                 _cell(r[1] if len(r) > 1 else "")]
        for i in iw_idx + ch_idx:
            cells.append(_cell(r[i] if i < len(r) else "", {"background": "#fbfdff"}))
        cells.append(_cell(r[di] if di < len(r) else "", {"color": TEAL, "fontWeight": 600}))
        cells.append(_cell(r[t["otu_i"]] if t["otu_i"] < len(r) else ""))
        body.append(_prow(cells, j, sel_i))
    return _table(thead, body)


def _grid_reference(t):
    thead = html.Thead(html.Tr([html.Th(c, style=_TH) for c in t["columns"]]))
    body = []
    for r in t["rows"]:
        cells = [_cell("\u2013" if v is None else v,
                       {"fontWeight": 700, "background": HEAD} if i == 0 else {})
                 for i, v in enumerate(r)]
        body.append(html.Tr(cells))
    return _table(thead, body)


def _render(t, sel_i=None):
    if t["kind"] == "reference":
        return html.Div([_rules_header(t), _grid_reference(t)], className="dcd-table-print")
    block = t.get("block")
    if not block:
        return _not_loaded()
    depth = block["depth"]
    grid = _grid_inwater(t, block, sel_i) if t["kind"] == "inwater" \
        else _grid_surfaceox(t, block, sel_i)
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
    Input("dcd-sel", "data"),
)
def _show(code, depth, sel):
    if not code:
        return _not_loaded()
    t = dcd.ui_table(code, depth)
    if not t:
        return _not_loaded()
    sel_i = sel["i"] if (sel and sel.get("code") == code and sel.get("depth") == depth) else None
    return _render(t, sel_i)



def _chart_hint(show):
    if not show:
        return None
    return html.Div("Tip: click any schedule row above to plot its dive profile here "
                    "(air/nitrox in-water families, or SOX/HSOX surface-O\u2082).",
                    className="no-print",
                    style={"color": MUTED, "fontSize": "0.82rem", "fontStyle": "italic",
                           "marginTop": "4px"})


@callback(
    Output("dcd-sel", "data"),
    Input({"type": "dcd-prow", "i": ALL}, "n_clicks"),
    State("dcd-family", "value"),
    State("dcd-depth", "value"),
    prevent_initial_call=True,
)
def _select_row(_nclicks, code, depth):
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or not ctx.triggered or not ctx.triggered[0]["value"]:
        return no_update
    return {"code": code, "depth": depth, "i": trig["i"]}


@callback(
    Output("dcd-sel", "data", allow_duplicate=True),
    Input("dcd-family", "value"),
    Input("dcd-depth", "value"),
    prevent_initial_call=True,
)
def _clear_sel(_code, _depth):
    return None


@callback(
    Output("dcd-chart", "children"),
    Input("dcd-sel", "data"),
    State("dcd-family", "value"),
    State("dcd-depth", "value"),
)
def _chart(sel, code, depth):
    t = dcd.ui_table(code, depth) if code else None
    chartable = bool(t and t.get("kind") in ("inwater", "surfaceox"))
    if not sel:
        return _chart_hint(chartable)
    if not t or t.get("kind") not in ("inwater", "surfaceox"):
        return _chart_hint(chartable)
    legs = profiles.dcd_legs(t, t.get("block"), sel["i"])
    if not legs:
        return _chart_hint(chartable)
    fig = profile_chart.build_figure(
        legs, native_unit="m", display_unit="m",
        title=f"{t['title']} \u2014 {depth} m dive profile", style_labels=profiles.DCD_STYLE_LABELS)
    return dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"height": "410px"})


clientside_callback(
    "function(n){ if(n){ setTimeout(function(){ window.print(); }, 60); } "
    "return window.dash_clientside.no_update; }",
    Output("dcd-print-sink", "children"),
    Input("dcd-print-btn", "n_clicks"),
    prevent_initial_call=True,
)
