"""
Vessel Tracker - Fleet.

Shows the complete fleet (all fields from Patrick's vessel list) with
SeaVantage workspace registration management per vessel:

- "Add" registers a vessel via POST /ship/match (IMO + name; retried with
  the AIS-broadcast name from `latest` if our name does not match) followed
  by POST /fleet. The registration date is recorded locally because the
  API does not return it.
- "Remove" is locked for 7 days after registration (SeaVantage rule);
  until then the button is disabled and shows the unlock date.
  Removal uses a two-step in-row confirm (the portal's standard pattern -
  ConfirmDialogProvider crashes pages client-side).
- A counter guards the account cap (SV_MAX_SHIPS, default 250).
- Rows are editable (Edit -> Save/Cancel). Identity fields (name, IMO,
  MMSI) are locked once the vessel is registered at SeaVantage. Owner and
  operator are edited as one combined "Owner / Operator" field, split on
  the first "/" when saving.
- Non-registered vessels get an "update name" button that pulls the
  AIS-broadcast name from `latest` (fed by both collectors) - the
  authoritative source for the name a vessel actually transmits.
- Region is refreshed automatically from each vessel's last known
  position every time the page loads.

All actions run inside try/except and report through a status banner; the
page never dies on API or DB trouble.
"""
from datetime import datetime, timedelta, timezone

import dash
from dash import html, dcc, Input, Output, State, callback, ctx

from app import auth
from app.engines import ais_db, sv_api

PAGE_PATH = "/vessel-tracker/fleet"

dash.register_page(__name__, path=PAGE_PATH, name="Fleet",
                   category="Vessel Tracker", order=1)

INK = "#1f2937"
MUTED = "#6b7280"
LINE = "#d1d5db"
HEAD_BG = "#f8fafc"
GREEN = "#047857"
AMBER = "#b45309"
RED = "#b91c1c"

_CELL = {"padding": "4px 8px", "borderBottom": f"1px solid {LINE}",
         "fontSize": "0.8rem", "whiteSpace": "nowrap"}
_ELLIPSIS = {"maxWidth": "220px", "overflow": "hidden",
             "textOverflow": "ellipsis"}
_TH = {**_CELL, "textAlign": "left", "background": HEAD_BG, "color": MUTED,
       "fontWeight": "600", "position": "sticky", "top": "0", "zIndex": "1"}
_BTN = {"padding": "3px 10px", "borderRadius": "6px", "fontSize": "0.78rem",
        "cursor": "pointer", "border": f"1px solid {LINE}", "background": "white"}
_BTN_DISABLED = {**_BTN, "cursor": "not-allowed", "color": "#c0c5cc",
                 "background": "#f3f4f6"}

DELETE_LOCK_DAYS = 7


def _removable_from(ts):
    return ts + timedelta(days=DELETE_LOCK_DAYS)


def _title_name(ais_name):
    """AIS names are ALL CAPS; capitalize plain words but keep tokens that
    look like acronyms or designators: containing digits (285) or without
    vowels (PMS, HYSY, CCC, II)."""
    out = []
    for w in (ais_name or "").split():
        keep = (any(ch.isdigit() for ch in w)
                or not any(v in w.lower() for v in "aeiou")
                or set(w.upper()) <= set("IVX"))       # roman numerals (II, III)
        if keep:
            out.append(w)
        else:
            out.append(w.capitalize())
    return " ".join(out)


def _owner_op(owner, operator):
    if owner and operator:
        return f"{owner} / {operator}"
    return owner or operator or ""


def _split_owner_op(value):
    value = (value or "").strip()
    if "/" in value:
        left, right = value.split("/", 1)
        return left.strip() or None, right.strip() or None
    return value or None, None


def _status_and_action(imo, registered_at, match_result, pending_delete):
    """Returns (SeaVantage status cell, action cell) for one row."""
    now = datetime.now(timezone.utc)
    if registered_at is not None:
        status = html.Span(f"added {registered_at.strftime('%d-%m-%y')}",
                           style={"color": GREEN})
        unlock = _removable_from(registered_at)
        if now < unlock:
            action = html.Button(
                f"Remove from {unlock.strftime('%d-%m-%y')}",
                disabled=True, style=_BTN_DISABLED,
                title=f"SeaVantage allows removal {DELETE_LOCK_DAYS} days "
                      f"after registration ({unlock.strftime('%d-%m-%Y %H:%M')} UTC)")
        elif pending_delete == str(imo):
            action = html.Span([
                html.Button("Confirm", id={"type": "vtf-del-confirm", "imo": str(imo)},
                            n_clicks=0,
                            style={**_BTN, "background": "#fef2f2",
                                   "borderColor": "#fecaca", "color": RED,
                                   "marginRight": "6px"}),
                html.Button("Cancel", id={"type": "vtf-del-cancel", "imo": str(imo)},
                            n_clicks=0, style=_BTN),
            ])
        else:
            action = html.Button("Remove", id={"type": "vtf-del", "imo": str(imo)},
                                 n_clicks=0, style=_BTN)
        return status, action

    if match_result and match_result != "SUCCESS":
        status = html.Span(match_result.replace("_", " ").lower(),
                           title="POST /ship/match could not pair IMO and name; "
                                 "retried with the AIS-broadcast name if known.",
                           style={"color": AMBER})
    else:
        status = html.Span("not registered", style={"color": MUTED})
    action = html.Button("Add", id={"type": "vtf-add", "imo": str(imo)},
                         n_clicks=0, style=_BTN)
    return status, action


def _edit_input(field, value, disabled=False, width="110px"):
    return dcc.Input(
        id={"type": "vtf-f", "field": field}, value=value or "",
        disabled=disabled, debounce=False,
        **({"list": "vtf-typelist"} if field == "vessel_type" else {}),
        style={"width": width, "fontSize": "0.8rem", "padding": "2px 5px",
               "border": f"1px solid {LINE}", "borderRadius": "5px",
               "background": "#f3f4f6" if disabled else "white"})


# (label, sort-key or None); sort keys resolve on the row dicts below
_COLUMNS = [("Vessel", "name"), ("", None), ("IMO", "imo"), ("MMSI", "mmsi"),
            ("Type", "vessel_type"), ("Owner / Operator", "owner"),
            ("Dim.", "length_m"),
            ("Built", "built"), ("Flag", "flag"), ("Region", "region"),
            ("Tier", "tier"), ("Notes", None), ("SeaVantage", "registered_at"),
            ("Action", None), ("", None)]


def _dim_txt(d):
    if not d.get("length_m"):
        return "\u2014"
    b = f" \u00d7 {d['beam_m']:.0f}" if d.get("beam_m") else ""
    return f"{d['length_m']:.0f}{b} m"


def _row_dict(r):
    (imo, mmsi, name, owner, operator, built, flag, region, tier, notes,
     active, ship_id, registered_at, match_result, ais_name, lat, lon,
     vessel_type, length_m, beam_m) = r
    return dict(imo=imo, mmsi=mmsi, name=name, owner=owner, operator=operator,
                built=built, flag=flag, region=region, tier=tier, notes=notes,
                active=active, ship_id=ship_id, registered_at=registered_at,
                match_result=match_result, ais_name=ais_name,
                vessel_type=vessel_type, length_m=length_m, beam_m=beam_m)


def _apply_filters(rows, search, ftype, fregion):
    out = []
    needle = (search or "").strip().lower()
    for d in rows:
        if ftype and (d["vessel_type"] or "") != ftype:
            continue
        if fregion and (d["region"] or "") != fregion:
            continue
        if needle:
            hay = " ".join(str(d[k] or "") for k in
                           ("name", "owner", "operator", "notes", "flag",
                            "vessel_type")).lower() + f" {d['imo']} {d['mmsi'] or ''}"
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


def _build_table(pending_delete=None, editing=None, search="", ftype=None,
                 fregion=None, sort=None, can_edit=True):
    raw = ais_db.fleet_with_sv()
    all_rows = [_row_dict(r) for r in raw]
    rows = _apply_sort(_apply_filters(all_rows, search, ftype, fregion), sort)
    n_reg = ais_db.sv_registered_count()
    cap = sv_api.SV_MAX_SHIPS
    at_cap = n_reg >= cap

    sort = sort or {}
    ths = []
    for label, skey in _COLUMNS:
        if skey:
            arrow = ""
            if sort.get("col") == skey:
                arrow = " \u25b2" if sort.get("dir") != "desc" else " \u25bc"
            ths.append(html.Th(html.Button(
                f"{label}{arrow}", n_clicks=0,
                id={"type": "vtf-sort", "col": skey},
                style={"all": "unset", "cursor": "pointer", "fontWeight": "600",
                       "color": MUTED, "whiteSpace": "nowrap"}), style=_TH))
        else:
            ths.append(html.Th(label, style=_TH))

    body = []
    for d in rows:
        imo, mmsi = d["imo"], d["mmsi"]
        locked = d["registered_at"] is not None
        if can_edit:
            status, action = _status_and_action(imo, d["registered_at"],
                                                d["match_result"], pending_delete)
        else:
            status, _ = _status_and_action(imo, d["registered_at"],
                                           d["match_result"], None)
            action = html.Span("\u2014", style={"color": "#c0c5cc"},
                               title="You have view-only access to the fleet")
        if can_edit and d["registered_at"] is None and at_cap:
            action = html.Button("Add", disabled=True, style=_BTN_DISABLED,
                                 title=f"Account limit reached ({cap} vessels)")
        style = {} if d["active"] else {"color": "#aeb4bd"}

        if editing == str(imo):
            cells = [
                _edit_input("name", d["name"], disabled=locked, width="150px"),
                "",
                _edit_input("imo", str(imo), disabled=locked, width="78px"),
                _edit_input("mmsi", str(mmsi or ""), disabled=locked, width="90px"),
                _edit_input("vessel_type", d["vessel_type"], width="70px"),
                _edit_input("owner_op", _owner_op(d["owner"], d["operator"]),
                            width="180px"),
                html.Span(_dim_txt(d), title="From AIS (auto)",
                          style={"color": MUTED, "fontSize": "0.78rem"}),
                _edit_input("built", d["built"], width="60px"),
                _edit_input("flag", d["flag"], width="60px"),
                _edit_input("region", d["region"], width="70px"),
                _edit_input("tier", d["tier"], width="50px"),
                _edit_input("notes", d["notes"], width="140px"),
                status,
                action,
                html.Span([
                    html.Button("Save", n_clicks=0,
                                id={"type": "vtf-save", "imo": str(imo)},
                                style={**_BTN, "background": "#f0fdf4",
                                       "borderColor": "#bbf7d0", "color": GREEN,
                                       "marginRight": "5px"}),
                    html.Button("Cancel", n_clicks=0,
                                id={"type": "vtf-cancel", "imo": str(imo)},
                                style=_BTN),
                ]),
            ]
        else:
            name_btn = ""
            if not locked and can_edit:
                name_btn = html.Button(
                    "\u21bb name", n_clicks=0,
                    id={"type": "vtf-nm", "imo": str(imo)},
                    title="Fetch the AIS-broadcast name (from the collectors) "
                          "and update the vessel name",
                    style={**_BTN, "padding": "1px 7px", "fontSize": "0.72rem"})
            cells = [
                d["name"], name_btn, str(imo), str(mmsi or "\u2014"),
                d["vessel_type"] or "\u2014",
                _owner_op(d["owner"], d["operator"]) or "\u2014",
                _dim_txt(d),
                d["built"] or "\u2014", d["flag"] or "\u2014",
                d["region"] or "\u2014", d["tier"] or "\u2014",
                d["notes"] or "\u2014",
                status, action,
                html.Button("Edit", n_clicks=0,
                            id={"type": "vtf-edit", "imo": str(imo)},
                            style={**_BTN, "padding": "1px 8px",
                                   "fontSize": "0.72rem"}) if can_edit else "",
            ]

        def td(c, i):
            extra = _ELLIPSIS if i in (5, 11) and editing != str(imo) else {}
            tip = c if isinstance(c, str) and i in (5, 11) else None
            return html.Td(c, style={**_CELL, **style, **extra}, title=tip)
        body.append(html.Tr([td(c, i) for i, c in enumerate(cells)]))

    table = html.Div(
        html.Table(
            [html.Thead(html.Tr(ths)), html.Tbody(body)],
            style={"borderCollapse": "collapse", "width": "100%"}),
        style={"maxHeight": "70vh", "overflow": "auto",
               "border": f"1px solid {LINE}", "borderRadius": "8px"})
    counter = html.Span(
        f"{len(rows)} / {len(all_rows)} shown \u00b7 "
        f"{n_reg} / {cap} registered at SeaVantage",
        style={"color": AMBER if at_cap else MUTED,
               "fontWeight": "600" if at_cap else "400"})
    types = sorted({d["vessel_type"] for d in all_rows if d["vessel_type"]})
    regions = sorted({d["region"] for d in all_rows if d["region"]})
    return table, counter, types, regions


def _banner(msg, ok=True):
    if not msg:
        return None
    return html.Div(msg, style={
        "border": f"1px solid {'#bbf7d0' if ok else '#fecaca'}",
        "background": "#f0fdf4" if ok else "#fef2f2",
        "color": GREEN if ok else RED,
        "borderRadius": "8px", "padding": "8px 14px", "margin": "8px 0",
        "fontSize": "0.85rem"})


VESSEL_TYPES = ["DSV", "PLB", "OSV"]           # suggesties; vrij tekstveld

_FILTER_INPUT = {"fontSize": "0.8rem", "padding": "4px 8px",
                 "border": f"1px solid {LINE}", "borderRadius": "6px"}


def _new_field(fid, placeholder, width="110px", required=False):
    return dcc.Input(id=f"vtf-new-{fid}", value="", placeholder=placeholder,
                     **({"list": "vtf-typelist"} if fid == "vessel_type" else {}),
                     style={**_FILTER_INPUT, "width": width,
                            "borderColor": "#f59e0b" if required else LINE})


_ADD_BTN_STYLE = {**_BTN, "padding": "6px 14px", "fontWeight": "600"}

layout = html.Div(className="full-width-page", children=[
    html.H3("Fleet"),
    html.P("Complete vessel list with SeaVantage workspace registration. "
           "Registered vessels are polled every 15 minutes (satellite AIS). "
           f"Removal is locked for {DELETE_LOCK_DAYS} days after registration.",
           style={"color": MUTED, "maxWidth": "760px"}),
    html.Datalist(id="vtf-typelist",
                  children=[html.Option(value=v) for v in VESSEL_TYPES]),
    html.Div([
        html.Button("+ Add vessel", id="vtf-add-open", n_clicks=0,
                    style=_ADD_BTN_STYLE),
        html.Button("Refresh", id="vtf-refresh", n_clicks=0,
                    style={**_BTN, "padding": "6px 14px", "marginLeft": "8px"}),
        dcc.Input(id="vtf-search", value="", debounce=True, type="text",
                  placeholder="Search name / owner / notes\u2026",
                  style={**_FILTER_INPUT, "width": "220px", "marginLeft": "14px"}),
        dcc.Dropdown(id="vtf-ftype", placeholder="Type", clearable=True,
                     style={"width": "120px", "display": "inline-block",
                            "verticalAlign": "middle", "marginLeft": "8px",
                            "fontSize": "0.8rem"}),
        dcc.Dropdown(id="vtf-fregion", placeholder="Region", clearable=True,
                     style={"width": "130px", "display": "inline-block",
                            "verticalAlign": "middle", "marginLeft": "8px",
                            "fontSize": "0.8rem"}),
        html.Span(id="vtf-counter", style={"marginLeft": "14px"}),
    ], style={"margin": "6px 0 4px", "display": "flex", "alignItems": "center",
              "flexWrap": "wrap", "gap": "2px"}),
    # add-vessel form: permanent in the layout (hidden), so its inputs always
    # exist for the callback - conditional rendering broke this page before
    html.Div(id="vtf-addform", style={"display": "none"}, children=html.Div([
        html.Div("New vessel \u2014 Name, IMO and Type are mandatory",
                 style={"fontWeight": "600", "marginBottom": "6px",
                        "fontSize": "0.85rem"}),
        html.Div([
            _new_field("name", "Vessel name *", "160px", required=True),
            _new_field("imo", "IMO (7 digits) *", "110px", required=True),
            _new_field("mmsi", "MMSI", "100px"),
            _new_field("vessel_type", "Type (DSV/PLB/\u2026) *", "120px", required=True),
            _new_field("owner_op", "Owner / Operator", "180px"),
            _new_field("built", "Built", "60px"),
            _new_field("flag", "Flag", "70px"),
            _new_field("region", "Region", "80px"),
            _new_field("tier", "Tier", "50px"),
            _new_field("notes", "Notes", "170px"),
            html.Button("Save vessel", id="vtf-new-save", n_clicks=0,
                        style={**_BTN, "background": "#f0fdf4",
                               "borderColor": "#bbf7d0", "color": GREEN}),
            html.Button("Cancel", id="vtf-new-cancel", n_clicks=0, style=_BTN),
        ], style={"display": "flex", "flexWrap": "wrap", "gap": "6px",
                  "alignItems": "center"}),
    ], style={"border": f"1px solid {LINE}", "borderRadius": "8px",
              "padding": "10px 14px", "margin": "6px 0",
              "background": "#f8fafc"})),
    html.Div(id="vtf-banner"),
    dcc.Store(id="vtf-pending-delete", data=None),
    dcc.Store(id="vtf-editing", data=None),
    dcc.Store(id="vtf-adding", data=False),
    dcc.Store(id="vtf-sort", data={"col": "name", "dir": "asc"}),
    dcc.Loading(html.Div(id="vtf-content"), type="default"),
])


@callback(
    Output("vtf-content", "children"),
    Output("vtf-counter", "children"),
    Output("vtf-banner", "children"),
    Output("vtf-pending-delete", "data"),
    Output("vtf-editing", "data"),
    Output("vtf-adding", "data"),
    Output("vtf-addform", "style"),
    Output("vtf-ftype", "options"),
    Output("vtf-fregion", "options"),
    Output("vtf-add-open", "style"),
    Output("vtf-new-name", "value"),
    Output("vtf-new-imo", "value"),
    Output("vtf-new-mmsi", "value"),
    Output("vtf-new-vessel_type", "value"),
    Output("vtf-new-owner_op", "value"),
    Output("vtf-new-built", "value"),
    Output("vtf-new-flag", "value"),
    Output("vtf-new-region", "value"),
    Output("vtf-new-tier", "value"),
    Output("vtf-new-notes", "value"),
    Input("vtf-refresh", "n_clicks"),
    Input("vtf-add-open", "n_clicks"),
    Input("vtf-new-save", "n_clicks"),
    Input("vtf-new-cancel", "n_clicks"),
    Input("vtf-search", "value"),
    Input("vtf-ftype", "value"),
    Input("vtf-fregion", "value"),
    Input({"type": "vtf-sort", "col": dash.ALL}, "n_clicks"),
    Input({"type": "vtf-add", "imo": dash.ALL}, "n_clicks"),
    Input({"type": "vtf-del", "imo": dash.ALL}, "n_clicks"),
    Input({"type": "vtf-del-confirm", "imo": dash.ALL}, "n_clicks"),
    Input({"type": "vtf-del-cancel", "imo": dash.ALL}, "n_clicks"),
    Input({"type": "vtf-edit", "imo": dash.ALL}, "n_clicks"),
    Input({"type": "vtf-nm", "imo": dash.ALL}, "n_clicks"),
    Input({"type": "vtf-save", "imo": dash.ALL}, "n_clicks"),
    Input({"type": "vtf-cancel", "imo": dash.ALL}, "n_clicks"),
    State({"type": "vtf-f", "field": dash.ALL}, "value"),
    State({"type": "vtf-f", "field": dash.ALL}, "id"),
    State("vtf-new-name", "value"), State("vtf-new-imo", "value"),
    State("vtf-new-mmsi", "value"), State("vtf-new-vessel_type", "value"),
    State("vtf-new-owner_op", "value"), State("vtf-new-built", "value"),
    State("vtf-new-flag", "value"), State("vtf-new-region", "value"),
    State("vtf-new-tier", "value"), State("vtf-new-notes", "value"),
    State("vtf-pending-delete", "data"),
    State("vtf-editing", "data"),
    State("vtf-adding", "data"),
    State("vtf-sort", "data"),
)
def _fleet_actions(_r, _ao, _ns, _nc, search, ftype, fregion,
                   _sort, _a, _d, _dc, _dx, _e, _nm, _sv, _cx,
                   f_values, f_ids,
                   nv_name, nv_imo, nv_mmsi, nv_type, nv_owner_op, nv_built,
                   nv_flag, nv_region, nv_tier, nv_notes,
                   pending, editing, adding, sort):
    trig = ctx.triggered_id
    clicked = bool(ctx.triggered) and bool(ctx.triggered[0].get("value"))
    banner, ok = None, True
    can_edit = auth.may_edit_params(auth.current_user(), PAGE_PATH)
    if not can_edit:
        editing, adding = None, False
    new_pending, new_editing, new_adding = None, editing, bool(adding)
    clear_new = False        # leeg de nieuw-vessel velden na save/open/cancel

    _MUTATING = ("vtf-add", "vtf-del", "vtf-del-confirm", "vtf-edit",
                 "vtf-nm", "vtf-save")
    try:
        if (clicked and not can_edit
                and ((isinstance(trig, dict) and trig.get("type") in _MUTATING)
                     or trig in ("vtf-add-open", "vtf-new-save"))):
            banner, ok = ("You have view-only access to the fleet; ask an "
                          "admin for 'edit fleet' rights.", False)
        elif clicked and isinstance(trig, dict) and trig.get("type") == "vtf-sort":
            col = trig["col"]
            if sort and sort.get("col") == col and sort.get("dir") == "asc":
                sort = {"col": col, "dir": "desc"}
            else:
                sort = {"col": col, "dir": "asc"}
        elif clicked and isinstance(trig, dict):
            imo = int(trig["imo"])
            kind = trig["type"]
            if kind == "vtf-del":
                new_pending, new_editing = str(imo), None
            elif kind == "vtf-del-cancel":
                new_pending = None
            elif kind == "vtf-add":
                banner, ok = _do_add(imo)
                new_editing = None
            elif kind == "vtf-del-confirm":
                banner, ok = _do_remove(imo)
            elif kind == "vtf-edit":
                new_editing, new_adding = str(imo), False
            elif kind == "vtf-nm":
                banner, ok = _do_update_name(imo)
            elif kind == "vtf-save" and editing:
                fields = {fid["field"]: (val or "").strip()
                          for fid, val in zip(f_ids, f_values)}
                banner, ok = _do_save(int(editing), fields)
                new_editing = None
            elif kind == "vtf-cancel":
                new_editing = None
        elif clicked and trig == "vtf-add-open":
            new_adding, new_editing = not new_adding, None
            if new_adding:
                clear_new = True         # verse, lege invoer bij openen
        elif clicked and trig == "vtf-new-cancel":
            new_adding, clear_new = False, True
        elif clicked and trig == "vtf-new-save":
            err = ais_db.fleet_insert({
                "name": nv_name, "imo": nv_imo, "mmsi": nv_mmsi,
                "vessel_type": nv_type,
                "owner": _split_owner_op(nv_owner_op)[0],
                "operator": _split_owner_op(nv_owner_op)[1],
                "built": nv_built, "flag": nv_flag, "region": nv_region,
                "tier": nv_tier, "notes": nv_notes})
            if err:
                banner, ok, new_adding = err, False, True
            else:
                banner, ok, new_adding = (
                    f"{(nv_name or '').strip()} added to the fleet "
                    f"(IMO {(nv_imo or '').strip()}). Positions appear once "
                    f"the vessel is registered in the SeaVantage workspace "
                    f"and the next 15-min poll runs.", True, False)
                clear_new = True
    except (ais_db.AisDbError, sv_api.SvApiError) as exc:
        banner, ok = str(exc), False
    except Exception as exc:  # never kill the page
        banner, ok = f"Unexpected error: {exc}", False

    if trig in (None, "vtf-refresh"):
        try:
            sync_msg = _sync_with_workspace()
            if sync_msg and banner is None:
                banner, ok = sync_msg, True
        except (sv_api.SvApiError, ais_db.AisDbError, Exception):
            pass    # SV onbereikbaar mag de pagina nooit blokkeren

    try:
        n_regions = ais_db.fleet_auto_update_regions()
        n_dims = ais_db.fleet_auto_update_dims()
        if (n_regions or n_dims) and banner is None:
            parts = []
            if n_regions:
                parts.append(f"{n_regions} region(s)")
            if n_dims:
                parts.append(f"{n_dims} dimension(s)")
            banner, ok = (" and ".join(parts) +
                          " updated from AIS data.", True)
    except ais_db.AisDbError:
        pass

    try:
        table, counter, types, regions = _build_table(
            pending_delete=new_pending, editing=new_editing,
            search=search, ftype=ftype, fregion=fregion, sort=sort,
            can_edit=can_edit)
    except Exception as exc:
        return (_banner(str(exc), ok=False), "", None, None, None, False,
                {"display": "none"}, [], [], _ADD_BTN_STYLE,
                *[dash.no_update] * 10)
    form_style = {"display": "block"} if (new_adding and can_edit) else {"display": "none"}
    add_btn_style = _ADD_BTN_STYLE if can_edit else {"display": "none"}
    # tien nieuw-velden: legen wanneer clear_new, anders ongemoeid laten
    new_vals = (["" ] * 10 if clear_new else [dash.no_update] * 10)
    return (table, counter, _banner(banner, ok), new_pending, new_editing,
            new_adding, form_style, types, regions, add_btn_style, *new_vals)


@callback(Output("vtf-sort", "data"),
          Input({"type": "vtf-sort", "col": dash.ALL}, "n_clicks"),
          State("vtf-sort", "data"))
def _store_sort(_clicks, sort):
    trig = ctx.triggered_id
    if not (ctx.triggered and ctx.triggered[0].get("value")) or not isinstance(trig, dict):
        return sort
    col = trig["col"]
    if sort and sort.get("col") == col and sort.get("dir") == "asc":
        return {"col": col, "dir": "desc"}
    return {"col": col, "dir": "asc"}


def _do_update_name(imo):
    row = _fleet_row(imo)
    mmsi, name = row[1], row[2]
    if not mmsi:
        return f"{name}: no MMSI on record, cannot look up the AIS name.", False
    ais_name = ais_db.fleet_ais_name(mmsi)
    if not ais_name:
        return (f"{name}: no AIS broadcast received yet (vessel not heard "
                f"by either collector so far).", False)
    new_name = _title_name(ais_name)
    if new_name == name:
        return f"{name}: AIS name matches, nothing to update.", True
    ais_db.fleet_update(imo, {"name": new_name})
    return f"Name updated: {name} \u2192 {new_name} (AIS broadcast).", True


def _do_save(imo, fields):
    row = _fleet_row(imo)
    locked = row[12] is not None      # registered_at
    name = row[2]
    updates = {}
    owner, operator = _split_owner_op(fields.get("owner_op"))
    updates["owner"], updates["operator"] = owner, operator
    for k in ("built", "flag", "region", "tier", "notes", "vessel_type"):
        updates[k] = fields.get(k) or None
    if not updates["vessel_type"]:
        return "Vessel type is mandatory (DSV, PLB, OSV, \u2026).", False
    if not locked:
        if fields.get("name"):
            updates["name"] = fields["name"]
        m = fields.get("mmsi") or ""
        if m and not m.isdigit():
            return f"MMSI must be numeric, got '{m}'.", False
        updates["mmsi"] = int(m) if m else None
        new_imo = fields.get("imo") or ""
        if new_imo and not new_imo.isdigit():
            return f"IMO must be numeric, got '{new_imo}'.", False
        if new_imo and int(new_imo) != imo:
            updates["imo"] = int(new_imo)
    ais_db.fleet_update(imo, updates)
    return f"{updates.get('name', name)} saved.", True


def _sync_with_workspace():
    """Two-way reconciliation with the SVMP workspace (one snapshot call):
    - vessels registered there but unknown here -> imported into the fleet
      (name/IMO/MMSI from AIS data; vessel type left for the first edit)
    - vessels we consider registered but absent there -> registration
      cleared (deregistered via the SVMP UI).
    A failed or empty snapshot never clears anything (guard against API
    hiccups wiping registrations). Returns a banner message or None."""
    items = sv_api.snapshot()
    if not items:
        return None
    known = {r[0]: r for r in ais_db.fleet_with_sv()}     # imo -> row
    seen_imos, imported = set(), []
    for item in items:
        pos = (item or {}).get("position") or {}
        ship_id = (item or {}).get("shipId")
        imo_raw = pos.get("imoNo")
        if not imo_raw or not str(imo_raw).isdigit():
            continue
        imo = int(imo_raw)
        seen_imos.add(imo)
        mmsi = pos.get("mmsi")
        mmsi = int(mmsi) if (mmsi and str(mmsi).isdigit()) else None
        name = _title_name(pos.get("shipName") or "") or f"IMO {imo}"
        if imo not in known:
            if ais_db.fleet_import_from_sv(imo, mmsi, name):
                imported.append(name)
        if ship_id:   # registratie vastleggen/bevestigen (klok start bij ons)
            ais_db.sv_record_registration(imo, mmsi, str(ship_id), name)
    cleared = []
    for imo, row in known.items():
        if row[12] is not None and imo not in seen_imos:   # registered_at
            ais_db.sv_clear_registration(imo)
            cleared.append(row[2])
    parts = []
    if imported:
        parts.append(f"Imported from your SeaVantage workspace: "
                     f"{', '.join(imported)} — set the vessel type via Edit.")
    if cleared:
        parts.append(f"No longer in the workspace (deregistered): "
                     f"{', '.join(cleared)}.")
    return " ".join(parts) or None


def _fleet_row(imo):
    for row in ais_db.fleet_with_sv():
        if row[0] == imo:
            return row
    raise ais_db.AisDbError(f"IMO {imo} not found in fleet")


def _do_add(imo):
    if ais_db.sv_registered_count() >= sv_api.SV_MAX_SHIPS:
        return f"Account limit reached ({sv_api.SV_MAX_SHIPS} vessels)", False
    row = _fleet_row(imo)
    mmsi, name = row[1], row[2]
    ais_name = row[14]

    # try our fleet name first, then the AIS-broadcast name if different
    attempts = [name.upper()]
    if ais_name and ais_name.upper() != name.upper():
        attempts.append(ais_name.upper())
    result, ship_id = None, None
    for attempt in attempts:
        res = sv_api.match([{"imoNo": str(imo), "shipName": attempt}])
        if not res:
            result = "EMPTY_MATCH_RESPONSE"
            continue
        result = (res[0].get("result") or "").upper()
        if result == "SUCCESS" and res[0].get("shipId"):
            ship_id = res[0]["shipId"]
            break
    if not ship_id:
        ais_db.sv_record_match_failure(imo, mmsi, result or "NO_RESULT")
        return (f"{name}: match failed ({result}). Check the vessel name "
                f"against SeaVantage / AIS spelling.", False)

    sv_api.register([ship_id])
    ais_db.sv_record_registration(imo, mmsi, ship_id, name)
    return f"{name} registered at SeaVantage (shipId {ship_id[:8]}…).", True


def _do_remove(imo):
    row = _fleet_row(imo)
    name, ship_id, registered_at = row[2], row[11], row[12]
    if not ship_id:
        return f"{name}: no SeaVantage shipId known.", False
    if registered_at and datetime.now(timezone.utc) < _removable_from(registered_at):
        return (f"{name}: SeaVantage blocks removal until "
                f"{_removable_from(registered_at).strftime('%d-%m-%Y')}.", False)
    sv_api.deregister([ship_id])
    ais_db.sv_clear_registration(imo)
    return f"{name} removed from the SeaVantage workspace.", True
