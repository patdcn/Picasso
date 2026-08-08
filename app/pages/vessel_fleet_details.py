"""
Vessel Tracker - Fleet Details.

Read-only capability overview of the whole fleet: dimensions, deck space,
POB, cranes, SAT system, bell configuration and ROV hangars, sourced from
the spec columns on the `fleet` table (migration 09_fleet_specs).

- Sort by clicking column headers (empty values always sort last).
- Filters: free text, region, SAT type, bell, confidence, minimum divers /
  crane SWL / deck area / POB, built-year range, active-only, and a
  "needs verification" toggle (rows whose source note carries a VERIFY
  flag or a conflict against a web source).
- Click the arrow at the start of a row to expand the source note + fleet
  notes for that vessel.
- Export downloads the CURRENT filtered view as CSV (for tender annexes).

Editing happens on the AIS Fleet page (Specs button per vessel); this page
is deliberately read-only. The whole render runs inside try/except and
shows an error card instead of dying when the AIS database is unreachable,
in line with the portal's _safe() philosophy.
"""
import csv
import io
from datetime import datetime, timezone

import dash
from dash import html, dcc, Input, Output, State, callback, ctx

from app.engines import ais_db

PAGE_PATH = "/vessel-tracker/fleet-details"

dash.register_page(__name__, path=PAGE_PATH, name="Fleet Details",
                   category="Vessel Tracker", order=1.2)

INK = "#1f2937"
MUTED = "#6b7280"
LINE = "#d1d5db"
HEAD_BG = "#f8fafc"
GREEN = "#047857"
AMBER = "#b45309"
RED = "#b91c1c"

_CELL = {"padding": "4px 8px", "borderBottom": f"1px solid {LINE}",
         "fontSize": "0.8rem", "whiteSpace": "nowrap"}
_TH = {**_CELL, "textAlign": "left", "background": HEAD_BG, "color": MUTED,
       "fontWeight": "600", "position": "sticky", "top": "0", "zIndex": "1"}
_BTN = {"padding": "3px 10px", "borderRadius": "6px", "fontSize": "0.78rem",
        "cursor": "pointer", "border": f"1px solid {LINE}",
        "background": "white"}
_FILTER_INPUT = {"fontSize": "0.8rem", "padding": "4px 8px",
                 "border": f"1px solid {LINE}", "borderRadius": "6px"}
_DD = {"display": "inline-block", "verticalAlign": "middle",
       "fontSize": "0.8rem"}

_CONF_COLOR = {"high": GREEN, "medium": AMBER, "low": RED}

# (label, sort key, title). Sort keys resolve on the row dicts below.
_COLUMNS = [
    ("", None, None),                                   # expand toggle
    ("Vessel", "name", None),
    ("Type", "vessel_type", None),
    ("Built", "built_year", None),
    ("Flag", "flag", None),
    ("Region", "region", None),
    ("Tier", "tier", None),
    ("Dim.", "length_m", "LOA \u00d7 beam from AIS"),
    ("Deck m\u00b2", "deck_space_m2", None),
    ("t/m\u00b2", "deck_strength_t_m2", "Deck strength"),
    ("POB", "pob", None),
    ("Crane 1", "crane1_swl_t", "Main crane SWL (t)"),
    ("Crane 2", "crane2_swl_t", "Auxiliary crane SWL (t)"),
    ("SAT", "sat_type", "integrated / deck / none"),
    ("Divers", "sat_divers", "Saturation system capacity"),
    ("Bell", "bell_config", None),
    ("ROV", "rov_hangar", "Work-class ROVs in hangar"),
    ("\u25cf", "spec_confidence", "Data confidence \u2014 hover the dot for "
                                  "the source; expand the row for details"),
]

_CSV_FIELDS = ("imo", "name", "vessel_type", "built_year", "flag", "region",
               "tier", "length_m", "beam_m", "deck_space_m2",
               "deck_strength_t_m2", "pob", "crane1_swl_t", "crane2_swl_t",
               "sat_type", "sat_divers", "bell_config", "rov_hangar",
               "spec_confidence", "spec_source", "notes", "active")


def _built_year(built):
    """fleet.built is TEXT ('2018-01' or '2018'); sortable int year."""
    try:
        return int(str(built).strip()[:4])
    except (TypeError, ValueError):
        return None


def _row_dict(r):
    (imo, mmsi, name, owner, operator, built, flag, region, tier, notes,
     active, vessel_type, length_m, beam_m, deck_space_m2,
     deck_strength_t_m2, pob, crane1_swl_t, crane2_swl_t, sat_type,
     sat_divers, bell_config, rov_hangar, spec_confidence, spec_source) = r
    return dict(imo=imo, mmsi=mmsi, name=name, owner=owner, operator=operator,
                built=built, built_year=_built_year(built), flag=flag,
                region=region, tier=tier, notes=notes, active=active,
                vessel_type=vessel_type, length_m=length_m, beam_m=beam_m,
                deck_space_m2=deck_space_m2,
                deck_strength_t_m2=deck_strength_t_m2, pob=pob,
                crane1_swl_t=crane1_swl_t, crane2_swl_t=crane2_swl_t,
                sat_type=sat_type, sat_divers=sat_divers,
                bell_config=bell_config, rov_hangar=rov_hangar,
                spec_confidence=spec_confidence, spec_source=spec_source)


def _needs_verify(d):
    src = (d.get("spec_source") or "").lower()
    return ("verify" in src or "web source had" in src
            or d.get("spec_confidence") == "low")


def _num(value):
    """'150' -> 150.0, ''/None/garbage -> None (filter inputs are text)."""
    try:
        v = float(str(value).strip())
        return v
    except (TypeError, ValueError):
        return None


def _apply_filters(rows, search, fregion, fsat, fbell, fconf,
                   min_divers, min_crane, min_deck, min_pob,
                   built_from, built_to, active_only, verify_only):
    needle = (search or "").strip().lower()
    min_crane, min_deck = _num(min_crane), _num(min_deck)
    min_pob = _num(min_pob)
    yr_from, yr_to = _num(built_from), _num(built_to)
    out = []
    for d in rows:
        if active_only and not d["active"]:
            continue
        if fregion and (d["region"] or "") != fregion:
            continue
        if fsat and (d["sat_type"] or "") != fsat:
            continue
        if fbell and (d["bell_config"] or "") != fbell:
            continue
        if fconf and (d["spec_confidence"] or "") != fconf:
            continue
        if min_divers and (d["sat_divers"] or 0) < int(min_divers):
            continue
        if min_crane is not None and (d["crane1_swl_t"] or 0) < min_crane:
            continue
        if min_deck is not None and (d["deck_space_m2"] or 0) < min_deck:
            continue
        if min_pob is not None and (d["pob"] or 0) < min_pob:
            continue
        if yr_from is not None and (d["built_year"] or 0) < yr_from:
            continue
        if yr_to is not None and (d["built_year"] or 9999) > yr_to:
            continue
        if verify_only and not _needs_verify(d):
            continue
        if needle:
            hay = " ".join(str(d[k] or "") for k in
                           ("name", "owner", "operator", "notes", "flag",
                            "vessel_type", "spec_source")).lower()
            hay += f" {d['imo']} {d['mmsi'] or ''}"
            if needle not in hay:
                continue
        out.append(d)
    return out


def _apply_sort(rows, sort):
    """Sort with empty values ALWAYS last, in both directions."""
    col = (sort or {}).get("col") or "name"
    rev = (sort or {}).get("dir") == "desc"
    filled = [d for d in rows if d.get(col) is not None]
    empty = [d for d in rows if d.get(col) is None]

    def key(d):
        v = d.get(col)
        return str(v).lower() if isinstance(v, str) else v
    try:
        return sorted(filled, key=key, reverse=rev) + empty
    except TypeError:
        return sorted(filled, key=lambda d: str(d.get(col)),
                      reverse=rev) + empty


def _fmt(v):
    if v is None:
        return "\u2014"
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def _dim_txt(d):
    if not d.get("length_m"):
        return "\u2014"
    b = f" \u00d7 {d['beam_m']:.0f}" if d.get("beam_m") else ""
    return f"{d['length_m']:.0f}{b}"


def _conf_dot(d):
    conf = d.get("spec_confidence")
    if not conf:
        return html.Span("\u2014", style={"color": "#c0c5cc"})
    tip = f"{conf}"
    src = d.get("spec_source")
    if src:
        tip += f" \u2014 {src[:300]}"
    return html.Span("\u25cf", title=tip,
                     style={"color": _CONF_COLOR.get(conf, MUTED),
                            "fontSize": "0.9rem", "cursor": "help"})


def _detail_row(d, n_cols):
    parts = []
    if d.get("owner") or d.get("operator"):
        who = " / ".join(x for x in (d.get("owner"), d.get("operator")) if x)
        parts.append(html.Div([html.B("Owner / Operator: "), who]))
    if d.get("spec_source"):
        parts.append(html.Div([html.B("Spec source: "), d["spec_source"]]))
    if d.get("notes"):
        parts.append(html.Div([html.B("Fleet notes: "), d["notes"]]))
    if _needs_verify(d):
        parts.append(html.Div("\u26a0 This row carries a verification flag "
                              "or low confidence \u2014 update it via the "
                              "Specs button on the AIS Fleet page once "
                              "confirmed.", style={"color": AMBER}))
    if not parts:
        parts = [html.Span("No notes for this vessel.",
                           style={"color": MUTED})]
    return html.Tr(html.Td(
        html.Div(parts, style={"display": "flex", "flexDirection": "column",
                               "gap": "3px", "whiteSpace": "normal",
                               "maxWidth": "1100px"}),
        colSpan=n_cols,
        style={**_CELL, "background": "#fbfcfe", "fontSize": "0.78rem",
               "whiteSpace": "normal"}))


def _build_table(rows, sort, expanded):
    sort = sort or {}
    expanded = set(expanded or [])
    ths = []
    for label, skey, tip in _COLUMNS:
        if skey:
            arrow = ""
            if sort.get("col") == skey:
                arrow = " \u25b2" if sort.get("dir") != "desc" else " \u25bc"
            ths.append(html.Th(html.Button(
                f"{label}{arrow}", n_clicks=0,
                id={"type": "vfd-sort", "col": skey}, title=tip,
                style={"all": "unset", "cursor": "pointer",
                       "fontWeight": "600", "color": MUTED,
                       "whiteSpace": "nowrap"}), style=_TH))
        else:
            ths.append(html.Th(label, style=_TH))

    body = []
    for d in rows:
        imo = str(d["imo"])
        is_open = imo in expanded
        style = {} if d["active"] else {"color": "#aeb4bd"}
        toggle = html.Button(
            "\u25be" if is_open else "\u25b8", n_clicks=0,
            id={"type": "vfd-x", "imo": imo},
            title="Show source note and fleet notes",
            style={"all": "unset", "cursor": "pointer", "color": MUTED,
                   "padding": "0 2px"})
        cells = [
            toggle,
            d["name"],
            d["vessel_type"] or "\u2014",
            _fmt(d["built_year"]),
            d["flag"] or "\u2014",
            d["region"] or "\u2014",
            d["tier"] or "\u2014",
            _dim_txt(d),
            _fmt(d["deck_space_m2"]),
            _fmt(d["deck_strength_t_m2"]),
            _fmt(d["pob"]),
            _fmt(d["crane1_swl_t"]),
            _fmt(d["crane2_swl_t"]),
            d["sat_type"] or "\u2014",
            _fmt(d["sat_divers"]),
            d["bell_config"] or "\u2014",
            _fmt(d["rov_hangar"]),
            _conf_dot(d),
        ]
        body.append(html.Tr([html.Td(c, style={**_CELL, **style})
                             for c in cells]))
        if is_open:
            body.append(_detail_row(d, len(_COLUMNS)))

    return html.Div(
        html.Table([html.Thead(html.Tr(ths)), html.Tbody(body)],
                   style={"borderCollapse": "collapse", "width": "100%"}),
        style={"maxHeight": "70vh", "overflow": "auto",
               "border": f"1px solid {LINE}", "borderRadius": "8px"})


def _error_card(exc):
    return html.Div([
        html.B("Fleet details unavailable"),
        html.Div(str(exc), style={"marginTop": "4px", "fontSize": "0.8rem"}),
    ], style={"border": "1px solid #fecaca", "background": "#fef2f2",
              "color": RED, "borderRadius": "8px", "padding": "12px 16px"})


def _dd_filter(fid, placeholder, width, options=None):
    return dcc.Dropdown(id=fid, placeholder=placeholder, clearable=True,
                        options=options or [],
                        style={**_DD, "width": width})


def _num_filter(fid, placeholder, width="90px"):
    return dcc.Input(id=fid, value="", debounce=True, type="text",
                     placeholder=placeholder,
                     style={**_FILTER_INPUT, "width": width})


layout = html.Div(className="full-width-page", children=[
    html.H3("Fleet Details"),
    html.P("Capability overview of every vessel in the fleet: deck, POB, "
           "cranes, SAT system, bell and ROV hangars. Hover the \u25cf for "
           "the data source; expand a row (\u25b8) for the full source note. "
           "Editing happens on the AIS Fleet page.",
           style={"color": MUTED, "maxWidth": "820px"}),
    html.Div([
        dcc.Input(id="vfd-search", value="", debounce=True, type="text",
                  placeholder="Search name / owner / notes\u2026",
                  style={**_FILTER_INPUT, "width": "210px"}),
        _dd_filter("vfd-fregion", "Region", "110px"),
        _dd_filter("vfd-fsat", "SAT type", "120px",
                   [{"label": v, "value": v}
                    for v in ("integrated", "deck", "none")]),
        _dd_filter("vfd-fbell", "Bell", "100px",
                   [{"label": v, "value": v}
                    for v in ("single", "twin", "none")]),
        _dd_filter("vfd-fdivers", "Min. divers", "115px",
                   [{"label": f"\u2265 {n}", "value": n}
                    for n in (9, 12, 15, 18, 24)]),
        _num_filter("vfd-fcrane", "Min. crane t"),
        _num_filter("vfd-fdeck", "Min. deck m\u00b2"),
        _num_filter("vfd-fpob", "Min. POB", "80px"),
        _num_filter("vfd-fyfrom", "Built \u2265", "75px"),
        _num_filter("vfd-fyto", "Built \u2264", "75px"),
        _dd_filter("vfd-fconf", "Confidence", "115px",
                   [{"label": v, "value": v}
                    for v in ("high", "medium", "low")]),
        dcc.Checklist(id="vfd-flags",
                      options=[{"label": " active only", "value": "active"},
                               {"label": " needs verification",
                                "value": "verify"}],
                      value=["active"], inline=True,
                      style={"fontSize": "0.8rem"},
                      inputStyle={"marginLeft": "10px"}),
        html.Button("Export CSV", id="vfd-export", n_clicks=0,
                    title="Download the current filtered view",
                    style=_BTN),
        html.Span(id="vfd-counter", style={"color": MUTED}),
    ], style={"margin": "6px 0 8px", "display": "flex",
              "alignItems": "center", "flexWrap": "wrap", "gap": "6px"}),
    dcc.Store(id="vfd-sort", data={"col": "name", "dir": "asc"}),
    dcc.Store(id="vfd-expanded", data=[]),
    dcc.Download(id="vfd-download"),
    dcc.Loading(html.Div(id="vfd-content"), type="default"),
])


_FILTER_STATES = [
    State("vfd-search", "value"), State("vfd-fregion", "value"),
    State("vfd-fsat", "value"), State("vfd-fbell", "value"),
    State("vfd-fconf", "value"), State("vfd-fdivers", "value"),
    State("vfd-fcrane", "value"), State("vfd-fdeck", "value"),
    State("vfd-fpob", "value"), State("vfd-fyfrom", "value"),
    State("vfd-fyto", "value"), State("vfd-flags", "value"),
]


def _filtered(search, fregion, fsat, fbell, fconf, fdivers, fcrane, fdeck,
              fpob, yfrom, yto, flags):
    rows = [_row_dict(r) for r in ais_db.fleet_details()]
    flags = flags or []
    subset = _apply_filters(rows, search, fregion, fsat, fbell, fconf,
                            fdivers, fcrane, fdeck, fpob, yfrom, yto,
                            "active" in flags, "verify" in flags)
    return rows, subset


@callback(
    Output("vfd-content", "children"),
    Output("vfd-counter", "children"),
    Output("vfd-fregion", "options"),
    Output("vfd-sort", "data"),
    Output("vfd-expanded", "data"),
    Input("vfd-search", "value"),
    Input("vfd-fregion", "value"),
    Input("vfd-fsat", "value"),
    Input("vfd-fbell", "value"),
    Input("vfd-fconf", "value"),
    Input("vfd-fdivers", "value"),
    Input("vfd-fcrane", "value"),
    Input("vfd-fdeck", "value"),
    Input("vfd-fpob", "value"),
    Input("vfd-fyfrom", "value"),
    Input("vfd-fyto", "value"),
    Input("vfd-flags", "value"),
    Input({"type": "vfd-sort", "col": dash.ALL}, "n_clicks"),
    Input({"type": "vfd-x", "imo": dash.ALL}, "n_clicks"),
    State("vfd-sort", "data"),
    State("vfd-expanded", "data"),
)
def _render(search, fregion, fsat, fbell, fconf, fdivers, fcrane, fdeck,
            fpob, yfrom, yto, flags, _sortclicks, _xclicks, sort, expanded):
    trig = ctx.triggered_id
    clicked = bool(ctx.triggered) and bool(ctx.triggered[0].get("value"))
    sort = sort or {"col": "name", "dir": "asc"}
    expanded = list(expanded or [])

    if clicked and isinstance(trig, dict):
        if trig.get("type") == "vfd-sort":
            col = trig["col"]
            if sort.get("col") == col and sort.get("dir") == "asc":
                sort = {"col": col, "dir": "desc"}
            else:
                sort = {"col": col, "dir": "asc"}
        elif trig.get("type") == "vfd-x":
            imo = trig["imo"]
            if imo in expanded:
                expanded.remove(imo)
            else:
                expanded.append(imo)

    try:
        rows, subset = _filtered(search, fregion, fsat, fbell, fconf,
                                 fdivers, fcrane, fdeck, fpob, yfrom, yto,
                                 flags)
    except ais_db.AisDbError as exc:
        return _error_card(exc), "", [], sort, expanded
    except Exception as exc:                     # never kill the page
        return _error_card(exc), "", [], sort, expanded

    subset = _apply_sort(subset, sort)
    table = _build_table(subset, sort, expanded)
    n_sat = sum(1 for d in subset if d.get("sat_divers"))
    counter = (f"{len(subset)} / {len(rows)} shown \u00b7 "
               f"{n_sat} with SAT capacity")
    regions = sorted({d["region"] for d in rows if d["region"]})
    region_opts = [{"label": v, "value": v} for v in regions]
    return table, counter, region_opts, sort, expanded


@callback(
    Output("vfd-download", "data"),
    Input("vfd-export", "n_clicks"),
    *_FILTER_STATES,
    State("vfd-sort", "data"),
    prevent_initial_call=True,
)
def _export(n_clicks, search, fregion, fsat, fbell, fconf, fdivers, fcrane,
            fdeck, fpob, yfrom, yto, flags, sort):
    if not n_clicks:
        return dash.no_update
    try:
        _, subset = _filtered(search, fregion, fsat, fbell, fconf, fdivers,
                              fcrane, fdeck, fpob, yfrom, yto, flags)
    except Exception:
        return dash.no_update
    subset = _apply_sort(subset, sort)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for d in subset:
        writer.writerow({k: ("" if d.get(k) is None else d.get(k))
                         for k in _CSV_FIELDS})
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return dict(content=buf.getvalue(),
                filename=f"fleet_details_{stamp}.csv")
