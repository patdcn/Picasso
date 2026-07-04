"""
Air MG Diving - Compare Tables.

Pick up to three schedules from the DCD and US Navy in-water and surface-
decompression (SurDO2) tables and overlay their dive profiles on one chart.
Each schedule is coloured by breathing gas and given its own line dash so the
three read clearly. No-stop-limit and RNT tables are excluded.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, MATCH, ALL, no_update

from app import reports
from app.engines import profiles
from app.engines import profile_chart

dash.register_page(__name__, path="/air-diving/compare-tables", name="Compare Tables",
                   category="Air MG Diving", order=3)

INK = "#1f2937"
MUTED = "#6b7280"
TEAL = "#0f766e"
LINE = "#d1d5db"
SLOT_COLORS = ["#0f766e", "#b45309", "#6d28d9"]

PDF_BTN_STYLE = {"padding": "8px 14px", "borderRadius": "8px", "border": "none",
                 "background": TEAL, "color": "#fff", "fontWeight": 600,
                 "cursor": "pointer", "fontSize": "0.85rem"}


def _opts(cat=None):
    return [{"label": o["label"], "value": o["value"]}
            for o in profiles.selectable_tables() if cat is None or o["cat"] == cat]


def _dd(id_, placeholder, options=None):
    return dcc.Dropdown(id=id_, options=options or [], placeholder=placeholder,
                        clearable=True, style={"fontSize": "0.8rem", "marginBottom": "6px"})


def _slot(k):
    return html.Div([
        html.Div([html.Span(style={"display": "inline-block", "width": "10px", "height": "10px",
                                   "borderRadius": "2px", "background": SLOT_COLORS[k],
                                   "marginRight": "6px"}),
                  html.Span(f"Schedule {k + 1}", style={"fontWeight": 700, "fontSize": "0.82rem",
                                                        "color": INK})],
                 style={"marginBottom": "6px"}),
        _dd({"type": "cmp-table", "k": k}, "table", _opts()),
        _dd({"type": "cmp-depth", "k": k}, "depth"),
        _dd({"type": "cmp-row", "k": k}, "bottom time"),
    ], style={"flex": "1 1 240px", "minWidth": "220px", "border": f"1px solid {LINE}",
              "borderRadius": "10px", "padding": "12px", "background": "#fafafa"})


def layout():
    return html.Div([
        reports.print_header(),
        html.Div([
            html.Button([html.Span("\u2913\u2002"), "Export to PDF"], id="cmp-print-btn",
                        n_clicks=0, style=PDF_BTN_STYLE),
            html.Div(id="cmp-print-sink", style={"display": "none"}),
        ], className="no-print",
           style={"display": "flex", "justifyContent": "flex-end", "marginBottom": "2px"}),

        html.H3("Compare Tables"),
        html.P("Pick up to three schedules from the DCD and US Navy in-water and "
               "surface-decompression tables; their dive profiles overlay on one chart "
               "(depths shown in metres). Schedule 1 sets the type \u2014 schedules 2 and 3 are "
               "then limited to the same kind (in-water with in-water, SurDO2 with SurDO2). Each "
               "schedule is coloured by gas and given its own line style. Indicative, for commercial "
               "planning only \u2014 not for operational decompression.",
               style={"color": MUTED, "maxWidth": "74ch", "lineHeight": 1.5}),

        html.Div([_slot(0), _slot(1), _slot(2)], className="no-print",
                 style={"display": "flex", "gap": "14px", "flexWrap": "wrap",
                        "marginTop": "8px", "marginBottom": "10px"}),

        html.Div(id="cmp-chart"),
        reports.print_footer(),
    ])


def _dlabel(value, d):
    source = value.split("|")[0]
    return f"{d} m" if source == "dcd" else f"{d} fsw"


def _short(value):
    source, code, mode = value.split("|")
    if source == "dcd":
        return "DCD " + code
    name = {"USN-AIR-DECO": "Air", "USN-N2O2-13-DECO": "N\u2082O\u2082 1.3",
            "USN-HEO2-13-DECO": "HeO\u2082 1.3", "USN-N2O2-075-DECO": "N\u2082O\u2082 0.75",
            "USN-HEO2-075-DECO": "HeO\u2082 0.75"}.get(code, code)
    return f"USN {name}" + (" SurDO2" if mode == "surdo2" else "")


def _hint():
    return html.Div("Choose a table, depth and bottom time in one or more slots above to plot "
                    "the profiles here.", className="no-print",
                    style={"color": MUTED, "fontSize": "0.85rem", "fontStyle": "italic",
                           "marginTop": "6px"})


@callback(
    Output({"type": "cmp-depth", "k": MATCH}, "options"),
    Output({"type": "cmp-depth", "k": MATCH}, "value"),
    Input({"type": "cmp-table", "k": MATCH}, "value"),
    prevent_initial_call=True,
)
def _depths(value):
    if not value:
        return [], None
    return [{"label": _dlabel(value, d), "value": d} for d in profiles.depths(value)], None


@callback(
    Output({"type": "cmp-row", "k": MATCH}, "options"),
    Output({"type": "cmp-row", "k": MATCH}, "value"),
    Input({"type": "cmp-depth", "k": MATCH}, "value"),
    State({"type": "cmp-table", "k": MATCH}, "value"),
    prevent_initial_call=True,
)
def _rows(depth, value):
    if not value or depth is None:
        return [], None
    return profiles.rows(value, depth), None


@callback(
    Output("cmp-chart", "children"),
    Input({"type": "cmp-row", "k": ALL}, "value"),
    State({"type": "cmp-table", "k": ALL}, "value"),
    State({"type": "cmp-depth", "k": ALL}, "value"),
)
def _chart(row_vals, tables, depths):
    profs = []
    for val, dep, ri in zip(tables or [], depths or [], row_vals or []):
        if not val or dep is None or ri is None:
            continue
        legs, unit = profiles.legs_for(val, dep, ri)
        if not legs:
            continue
        rlabel = next((r["label"] for r in profiles.rows(val, dep) if r["value"] == ri), "")
        label = f"{_short(val)} {_dlabel(val, dep)} \u00b7 {rlabel}"
        profs.append({"legs": legs, "native_unit": unit, "label": label})
    if not profs:
        return _hint()
    fig = profile_chart.build_multi_figure(profs, display_unit="m",
                                           title="Profile comparison (metres)")
    return dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"height": "440px"})


@callback(
    Output({"type": "cmp-table", "k": 1}, "options"),
    Output({"type": "cmp-table", "k": 2}, "options"),
    Output({"type": "cmp-table", "k": 1}, "value"),
    Output({"type": "cmp-table", "k": 2}, "value"),
    Input({"type": "cmp-table", "k": 0}, "value"),
    State({"type": "cmp-table", "k": 1}, "value"),
    State({"type": "cmp-table", "k": 2}, "value"),
    prevent_initial_call=True,
)
def _constrain(v0, v1, v2):
    # Schedule 1 (slot 0) sets the category; schedules 2 and 3 are limited to it.
    if not v0:
        allo = _opts()
        return allo, allo, no_update, no_update
    cat = profiles.table_category(v0)
    filt = _opts(cat)
    keep1 = no_update if (v1 and profiles.table_category(v1) == cat) else None
    keep2 = no_update if (v2 and profiles.table_category(v2) == cat) else None
    return filt, filt, keep1, keep2


dash.clientside_callback(
    "function(n){ if(n){ setTimeout(function(){ window.print(); }, 60); } "
    "return window.dash_clientside.no_update; }",
    Output("cmp-print-sink", "children"),
    Input("cmp-print-btn", "n_clicks"),
    prevent_initial_call=True,
)
