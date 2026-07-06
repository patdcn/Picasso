"""
SAT Diving — Depth excursion (unlimited-duration excursion limits).

From a storage (living) depth, computes the maximum DOWNWARD (descending) and
UPWARD (ascending) excursion a saturated diver may make without a decompression
obligation on return to storage depth, per the U.S. Navy Diving Manual (Rev 7)
Ch.13, Table 13-7 (downward) and Table 13-8 (upward). The original USN tables are
shown on the page for reference.

All lookups are done in fsw (the tables' native unit) and converted to metres for
display. INDICATIVE PLANNING ONLY -- see the disclaimer block.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, clientside_callback, no_update

from app.engines import sat_excursion as eng
from app import reports

dash.register_page(__name__, path="/diving/depth-excursion", name="Depth excursion",
                   category="SAT Diving", order=2)

MUTED = "#64748b"
ACCENT = "#0f766e"
INK = "#0f172a"
GRID = "#e2e8f0"
AMBER = "#b45309"
AMBER_BG = "rgba(186,117,23,0.13)"
DESC = "#b45309"      # descending accent (down / warmer)
ASC = "#0369a1"       # ascending accent (up / cooler)

PDF_BTN_STYLE = {
    "padding": "8px 14px", "borderRadius": "8px", "border": "none",
    "background": ACCENT, "color": "#fff", "fontWeight": 600,
    "cursor": "pointer", "fontSize": "0.85rem",
}


# --------------------------------------------------------------------------- #
# Small UI helpers
# --------------------------------------------------------------------------- #
def _label(txt):
    return html.Label(txt, style={"fontSize": "0.75rem", "fontWeight": 600,
                                  "color": MUTED, "display": "block",
                                  "marginBottom": "4px"})


def _result_card(card_id, title, accent, arrow):
    """Result card; the *-depth / *-dist / *-row ids are filled by the callback."""
    return html.Div([
        html.Div([html.Span(arrow, style={"marginRight": "6px"}), title],
                 style={"fontSize": "0.78rem", "color": MUTED, "fontWeight": 700,
                        "textTransform": "uppercase", "letterSpacing": "0.04em"}),
        html.Div(id=f"de-{card_id}-depth",
                 style={"fontSize": "1.9rem", "fontWeight": 800, "color": accent,
                        "lineHeight": "1.15", "marginTop": "4px"}),
        html.Div(id=f"de-{card_id}-dist",
                 style={"fontSize": "0.9rem", "color": INK, "marginTop": "2px"}),
        html.Div(id=f"de-{card_id}-row",
                 style={"fontSize": "0.78rem", "color": MUTED, "marginTop": "2px"}),
    ], style={"background": "#f8fafc", "border": f"1px solid {GRID}",
              "borderLeft": f"4px solid {accent}", "borderRadius": "12px",
              "padding": "14px 18px", "flex": "1 1 240px", "minWidth": "230px"})


# Metric reference table: round storage steps over the tables' valid range.
# (850 fsw = 259 m is the downward table's deepest row, so cap at 255 m.)
METRIC_MIN_M = 10
METRIC_MAX_M = 255
METRIC_STEP_M = 5


def _table_rows(mapping, depth_sign, unit):
    """(storage, distance, depth) as display strings.

    fsw : the table exactly as published (10-fsw storage rows, integer feet).
    msw : re-tabulated at round metric storage depths via the SAME engine the
          calculator uses, so the reference table and the result cards agree.
    """
    rows = []
    if unit == "msw":
        d = float(METRIC_MIN_M)
        while d <= METRIC_MAX_M + 1e-9:
            e = eng.envelope(eng.msw_to_fsw(d))
            if depth_sign > 0:
                dist = e["down_dist_fsw"] / eng.FT_PER_M
                depth = e["max_desc_fsw"] / eng.FT_PER_M
            else:
                dist = e["up_dist_fsw"] / eng.FT_PER_M
                depth = e["max_asc_fsw"] / eng.FT_PER_M
            rows.append((f"{d:.0f}", f"{dist:.1f}", f"{depth:.1f}"))
            d += METRIC_STEP_M
    else:
        for s in sorted(mapping):
            dist = mapping[s]
            depth = s + dist if depth_sign > 0 else s - dist
            rows.append((f"{s:.0f}", f"{dist:.0f}", f"{depth:.0f}"))
    return rows


def _subtable(rows, headers):
    """One half of a reference table from pre-formatted (storage, dist, depth) rows."""
    head = {"padding": "5px 10px 5px 0", "fontSize": "0.72rem", "fontWeight": 700,
            "textAlign": "right", "color": INK, "borderBottom": f"1px solid {GRID}"}
    head0 = {**head, "textAlign": "left"}
    cell = {"padding": "1px 10px 1px 0", "fontSize": "0.76rem", "textAlign": "right"}
    cell0 = {**cell, "textAlign": "left", "color": MUTED}
    trs = [html.Tr([
        html.Td(s, style=cell0),
        html.Td(dist, style=cell),
        html.Td(depth, style={**cell, "fontWeight": 600}),
    ]) for (s, dist, depth) in rows]
    return html.Table(
        [html.Thead(html.Tr([html.Th(headers[0], style=head0),
                             html.Th(headers[1], style=head),
                             html.Th(headers[2], style=head)]))]
        + [html.Tbody(trs)],
        style={"borderCollapse": "collapse", "flex": "1 1 auto"})


def _ref_table(section, title, mapping, dist_label, depth_sign, unit):
    """A reference table split into two halves (mirrors the manual's own two-column
    layout, and keeps the printed table to a single page)."""
    rows = _table_rows(mapping, depth_sign, unit)
    su = "m" if unit == "msw" else "fsw"
    du = "m" if unit == "msw" else "ft"
    headers = (f"Storage ({su})", f"{dist_label} ({du})", f"Depth ({su})")
    caption = (f"Computed at round {METRIC_STEP_M} m storage depths "
               "(from the fsw source)" if unit == "msw" else "As published (fsw)")
    mid = (len(rows) + 1) // 2
    return html.Div([
        html.Div([html.Span(f"{section}  ", style={"fontWeight": 700, "color": ACCENT}),
                  title], style={"fontSize": "0.85rem", "marginBottom": "2px"}),
        html.Div(caption, style={"fontSize": "0.72rem", "color": MUTED,
                                 "marginBottom": "6px"}),
        html.Div(
            html.Div([_subtable(rows[:mid], headers), _subtable(rows[mid:], headers)],
                     style={"display": "flex", "gap": "18px"}),
            className="de-print-expand",
            style={"maxHeight": "340px", "overflowY": "auto",
                   "border": f"1px solid {GRID}", "borderRadius": "10px",
                   "padding": "8px 12px"}),
    ], style={"flex": "1 1 340px", "minWidth": "320px"})


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
def layout():
    return html.Div([
        reports.print_header(),
        html.Div([
            html.Button([html.Span("\u2913\u2002"), "Export to PDF"],
                        id="de-pdf-btn", n_clicks=0, style=PDF_BTN_STYLE,
                        title="Opens your browser's print dialog \u2014 "
                              "choose 'Save as PDF' (A3 portrait)"),
            html.Div(id="de-print-sink", style={"display": "none"}),
        ], className="no-print",
           style={"display": "flex", "justifyContent": "flex-end",
                  "marginBottom": "2px"}),

        html.H3("Depth excursion (SAT)", style={"marginBottom": "2px"}),
        html.P("Maximum descending and ascending excursions from a saturation "
               "storage depth, per the U.S. Navy Diving Manual (Rev 7) Ch.13 "
               "Unlimited-Duration Excursion Limits \u2014 Table 13-7 (downward) "
               "and Table 13-8 (upward). Indicative planning only.",
               style={"color": MUTED, "marginTop": 0, "maxWidth": "820px"}),

        dcc.Store(id="de-unit-prev", data="msw"),

        # ---- input panel ----
        html.Div([
            html.Div([
                _label("Storage depth"),
                html.Div([
                    dcc.Input(id="de-depth", type="number", value=40, min=0,
                              step="any", debounce=True,
                              style={"width": "120px", "fontSize": "1.05rem",
                                     "padding": "6px 8px", "fontWeight": 700}),
                    html.Span("m", id="de-depth-unit",
                              style={"marginLeft": "8px", "color": MUTED,
                                     "fontSize": "0.9rem"}),
                ], style={"display": "flex", "alignItems": "center"}),
            ], style={"flex": "0 0 auto"}),

            html.Div([
                _label("Units"),
                dcc.RadioItems(
                    id="de-unit",
                    options=[{"label": " m (msw)", "value": "msw"},
                             {"label": " ft (fsw)", "value": "fsw"}],
                    value="msw", inline=True,
                    style={"fontSize": "0.85rem"},
                    labelStyle={"marginRight": "14px"}),
            ], style={"flex": "0 0 auto"}),
        ], style={"display": "flex", "gap": "34px", "flexWrap": "wrap",
                  "alignItems": "flex-start", "background": "#fff",
                  "border": f"1px solid {GRID}", "borderRadius": "12px",
                  "padding": "16px"}),

        # ---- result cards ----
        html.Div([
            _result_card("desc", "Max descending depth", DESC, "\u25bc"),
            _result_card("asc", "Max ascending depth", ASC, "\u25b2"),
        ], style={"display": "flex", "gap": "14px", "flexWrap": "wrap",
                  "margin": "16px 0 4px"}),
        html.Div(id="de-note",
                 style={"fontSize": "0.8rem", "color": MUTED, "margin": "2px 2px 4px"}),

        # ---- reference tables ----
        html.Details([
            html.Summary("Original USN tables (reference)",
                         style={"cursor": "pointer", "fontSize": "0.9rem",
                                "fontWeight": 700, "color": ACCENT,
                                "margin": "18px 0 10px"}),
            html.Div(id="de-ref-tables",
                     style={"display": "flex", "gap": "22px", "flexWrap": "wrap"}),
        ], open=True),

        _rules_block(),
        reports.print_footer(),
    ], style={"paddingBottom": "24px"})


# --------------------------------------------------------------------------- #
# Rules / provenance / disclaimer
# --------------------------------------------------------------------------- #
def _rules_block():
    def li(t):
        return html.Li(t, style={"marginBottom": "5px"})
    return html.Div([
        html.H4("Rules implemented", style={"marginBottom": "6px"}),
        html.Ul([
            li("Descending: maximum downward excursion distance from Table 13-7, "
               "added to the storage depth. Ascending: maximum upward excursion "
               "distance from Table 13-8, subtracted from the storage depth."),
            li("Both tables are entered in fsw (their native unit). If the storage "
               "depth falls between listed rows, the manual's conservative rule is "
               "used: read the next SHALLOWER row for downward (Table 13-7) and the "
               "next DEEPER row for upward (Table 13-8). The table row actually used "
               "is shown beneath each result."),
            li("The upward-limit table is the tabulation of the U.S. Navy 1989 "
               "empirical formula UEXD = (\u221a(0.1574\u00b7D + 6.197) \u2212 1) / "
               "0.0787 (Thalmann 1989; validated 36\u20131100 fsw). The tabulated "
               "integer values are used directly."),
            li("Excursions carry a 4-hour in-water limit and an ascent rate not "
               "exceeding 60 fsw/min. Upward excursions additionally require "
               "\u2265 48 h of stabilisation at storage depth and the chamber ppO2 "
               "conditions of \u00a713-14 / \u00a713-23 before they may be made."),
            li("Depths are computed in fsw; the metre view converts at "
               "1 m = 3.281 ft for display only. The tables cover storage depths "
               "of 29\u2013850 fsw (\u2248 9\u2013259 m); the underlying trials "
               "validated 150\u20131000 fsw."),
        ], style={"color": INK, "fontSize": "0.85rem", "paddingLeft": "18px",
                  "lineHeight": "1.5"}),
        html.Div([
            html.Span("Disclaimer  ", style={"fontWeight": 700, "color": AMBER}),
            html.Span("This tool is for indicative planning only. It is not an "
                      "operational excursion authorisation and must not be used to "
                      "control a dive. Excursions shall be planned and conducted "
                      "under the responsible Diving Supervisor / Diving Medical "
                      "Officer using the controlling tables and unit procedures. "
                      "Always validate against the current U.S. Navy Diving Manual."),
        ], style={"marginTop": "12px", "padding": "10px 14px",
                  "background": AMBER_BG, "border": f"1px solid {AMBER}",
                  "borderRadius": "10px", "fontSize": "0.82rem", "color": "#7c2d12"}),
    ], style={"marginTop": "28px", "paddingTop": "14px",
              "borderTop": f"1px solid {GRID}"})


# --------------------------------------------------------------------------- #
# Unit toggle: convert the displayed depth value and its suffix.
# --------------------------------------------------------------------------- #
@callback(
    Output("de-depth", "value"),
    Output("de-depth-unit", "children"),
    Output("de-unit-prev", "data"),
    Input("de-unit", "value"),
    State("de-depth", "value"),
    State("de-unit-prev", "data"),
    prevent_initial_call=True,
)
def _convert_units(unit, depth, prev):
    suffix = "m" if unit == "msw" else "ft"
    if unit == prev or depth is None:
        return (no_update, suffix, unit)
    conv = (round(eng.fsw_to_msw(depth), 1) if unit == "msw"
            else round(eng.msw_to_fsw(depth)))
    return (conv, suffix, unit)


# --------------------------------------------------------------------------- #
# Main compute: storage depth -> descending / ascending cards + note.
# --------------------------------------------------------------------------- #
def _depth_str(fsw, unit):
    return f"{eng.fsw_to_msw(fsw):.1f} m" if unit == "msw" else f"{fsw:.0f} fsw"


def _both(fsw):
    return f"{eng.fsw_to_msw(fsw):.1f} m ({fsw:.0f} fsw)"


def _row_str(fsw, unit):
    """Table row (a fsw index) shown in the selected unit."""
    return f"{eng.fsw_to_msw(fsw):.1f} m ({fsw:.0f} fsw)" if unit == "msw" else f"{fsw:.0f} fsw"


@callback(
    Output("de-desc-depth", "children"),
    Output("de-desc-dist", "children"),
    Output("de-desc-row", "children"),
    Output("de-asc-depth", "children"),
    Output("de-asc-dist", "children"),
    Output("de-asc-row", "children"),
    Output("de-note", "children"),
    Input("de-unit", "value"),
    Input("de-depth", "value"),
)
def _compute(unit, depth):
    dash_ = "\u2014"
    if depth is None or depth == "":
        return (dash_, "", "", dash_, "", "", "Enter a storage depth.")

    storage_fsw = eng.msw_to_fsw(depth) if unit == "msw" else float(depth)
    e = eng.envelope(storage_fsw)

    desc_depth = _depth_str(e["max_desc_fsw"], unit)
    desc_dist = ("excursion down "
                 + (f"{eng.fsw_to_msw(e['down_dist_fsw']):.1f} m "
                    f"({e['down_dist_fsw']:.0f} ft)" if unit == "msw"
                    else f"{e['down_dist_fsw']:.0f} ft "
                         f"({eng.fsw_to_msw(e['down_dist_fsw']):.1f} m)"))
    desc_row = f"Table 13-7 \u00b7 row {_row_str(e['down_row_fsw'], unit)}"

    asc_depth = _depth_str(e["max_asc_fsw"], unit)
    asc_dist = ("excursion up "
                + (f"{eng.fsw_to_msw(e['up_dist_fsw']):.1f} m "
                   f"({e['up_dist_fsw']:.0f} ft)" if unit == "msw"
                   else f"{e['up_dist_fsw']:.0f} ft "
                        f"({eng.fsw_to_msw(e['up_dist_fsw']):.1f} m)"))
    asc_row = f"Table 13-8 \u00b7 row {_row_str(e['up_row_fsw'], unit)}"

    note = (f"Storage depth {_both(e['storage_fsw'])}. Excursion window "
            f"{_depth_str(e['max_asc_fsw'], unit)} \u2192 "
            f"{_depth_str(e['max_desc_fsw'], unit)}.")
    if not e["in_range"]:
        note += ("  \u26a0 Storage depth is outside the combined table range "
                 f"({eng.MIN_STORAGE_FSW:.0f}\u2013{eng.MAX_STORAGE_FSW:.0f} fsw); "
                 "values are clamped to the nearest table row.")

    return (desc_depth, desc_dist, desc_row, asc_depth, asc_dist, asc_row, note)


# --------------------------------------------------------------------------- #
# Reference tables: rebuilt in the selected unit (fsw as printed, or converted
# to metres). Split into two halves so the full tables print on one page.
# --------------------------------------------------------------------------- #
@callback(
    Output("de-ref-tables", "children"),
    Input("de-unit", "value"),
)
def _ref_tables(unit):
    return [
        _ref_table("Table 13-7", "Unlimited-Duration Downward Excursion Limits",
                   eng.DOWNWARD, "Deepest excursion distance", +1, unit),
        _ref_table("Table 13-8", "Unlimited-Duration Upward Excursion Limits",
                   eng.UPWARD, "Shallowest excursion distance", -1, unit),
    ]


# --------------------------------------------------------------------------- #
# Export to PDF — open the browser print dialog (A3 portrait CSS in portal.css).
# --------------------------------------------------------------------------- #
clientside_callback(
    "function(n){ if(n){ setTimeout(function(){ window.print(); }, 60); } "
    "return window.dash_clientside.no_update; }",
    Output("de-print-sink", "children"),
    Input("de-pdf-btn", "n_clicks"),
    prevent_initial_call=True,
)
