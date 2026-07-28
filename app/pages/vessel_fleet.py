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

from app.engines import ais_db, sv_api

dash.register_page(__name__, path="/vessel-tracker/fleet", name="Fleet",
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
        style={"width": width, "fontSize": "0.8rem", "padding": "2px 5px",
               "border": f"1px solid {LINE}", "borderRadius": "5px",
               "background": "#f3f4f6" if disabled else "white"})


def _build_table(pending_delete=None, editing=None):
    rows = ais_db.fleet_with_sv()
    n_reg = ais_db.sv_registered_count()
    cap = sv_api.SV_MAX_SHIPS
    at_cap = n_reg >= cap

    headers = ["Vessel", "", "IMO", "MMSI", "Owner / Operator",
               "Built", "Flag", "Region", "Tier", "Notes",
               "SeaVantage", "Action", ""]
    body = []
    for (imo, mmsi, name, owner, operator, built, flag, region, tier, notes,
         active, ship_id, registered_at, match_result, ais_name,
         _lat, _lon) in rows:
        locked = registered_at is not None
        status, action = _status_and_action(imo, registered_at, match_result,
                                            pending_delete)
        if registered_at is None and at_cap:
            action = html.Button("Add", disabled=True, style=_BTN_DISABLED,
                                 title=f"Account limit reached ({cap} vessels)")
        style = {} if active else {"color": "#aeb4bd"}

        if editing == str(imo):
            # --- edit mode: inputs; identity locked when SV-registered ----
            cells = [
                _edit_input("name", name, disabled=locked, width="150px"),
                "",
                _edit_input("imo", str(imo), disabled=locked, width="78px"),
                _edit_input("mmsi", str(mmsi or ""), disabled=locked, width="90px"),
                _edit_input("owner_op", _owner_op(owner, operator), width="190px"),
                _edit_input("built", built, width="70px"),
                _edit_input("flag", flag, width="60px"),
                _edit_input("region", region, width="70px"),
                _edit_input("tier", tier, width="60px"),
                _edit_input("notes", notes, width="150px"),
                status,
                action,
                html.Span([
                    html.Button("Save", id="vtf-save", n_clicks=0,
                                style={**_BTN, "background": "#f0fdf4",
                                       "borderColor": "#bbf7d0", "color": GREEN,
                                       "marginRight": "5px"}),
                    html.Button("Cancel", id="vtf-cancel", n_clicks=0, style=_BTN),
                ]),
            ]
        else:
            name_btn = ""
            if not locked:
                name_btn = html.Button(
                    "\u21bb name", n_clicks=0,
                    id={"type": "vtf-nm", "imo": str(imo)},
                    title="Fetch the AIS-broadcast name (from the collectors) "
                          "and update the vessel name",
                    style={**_BTN, "padding": "1px 7px", "fontSize": "0.72rem"})
            cells = [
                name, name_btn, str(imo), str(mmsi or "\u2014"),
                _owner_op(owner, operator) or "\u2014",
                built or "\u2014", flag or "\u2014", region or "\u2014",
                tier or "\u2014", notes or "\u2014",
                status, action,
                html.Button("Edit", n_clicks=0,
                            id={"type": "vtf-edit", "imo": str(imo)},
                            style={**_BTN, "padding": "1px 8px",
                                   "fontSize": "0.72rem"}),
            ]

        def td(c, i):
            extra = _ELLIPSIS if i in (4, 9) and editing != str(imo) else {}
            tip = c if isinstance(c, str) and i in (4, 9) else None
            return html.Td(c, style={**_CELL, **style, **extra}, title=tip)
        body.append(html.Tr([td(c, i) for i, c in enumerate(cells)]))

    table = html.Div(
        html.Table(
            [html.Thead(html.Tr([html.Th(h, style=_TH) for h in headers])),
             html.Tbody(body)],
            style={"borderCollapse": "collapse", "width": "100%"}),
        style={"maxHeight": "70vh", "overflow": "auto",
               "border": f"1px solid {LINE}", "borderRadius": "8px"})
    counter = html.Span(f"{n_reg} / {cap} registered at SeaVantage",
                        style={"color": AMBER if at_cap else MUTED,
                               "fontWeight": "600" if at_cap else "400"})
    return table, counter


def _banner(msg, ok=True):
    if not msg:
        return None
    return html.Div(msg, style={
        "border": f"1px solid {'#bbf7d0' if ok else '#fecaca'}",
        "background": "#f0fdf4" if ok else "#fef2f2",
        "color": GREEN if ok else RED,
        "borderRadius": "8px", "padding": "8px 14px", "margin": "8px 0",
        "fontSize": "0.85rem"})


layout = html.Div(className="full-width-page", children=[
    html.H3("Fleet"),
    html.P("Complete vessel list with SeaVantage workspace registration. "
           "Registered vessels are polled every 15 minutes (satellite AIS). "
           f"Removal is locked for {DELETE_LOCK_DAYS} days after registration.",
           style={"color": MUTED, "maxWidth": "760px"}),
    html.Div([
        html.Button("Refresh", id="vtf-refresh", n_clicks=0,
                    style={**_BTN, "padding": "6px 14px"}),
        html.Span(id="vtf-counter", style={"marginLeft": "14px"}),
    ], style={"margin": "6px 0 4px"}),
    html.Div(id="vtf-banner"),
    dcc.Store(id="vtf-pending-delete", data=None),
    dcc.Store(id="vtf-editing", data=None),
    dcc.Loading(html.Div(id="vtf-content"), type="default"),
])


@callback(
    Output("vtf-content", "children"),
    Output("vtf-counter", "children"),
    Output("vtf-banner", "children"),
    Output("vtf-pending-delete", "data"),
    Output("vtf-editing", "data"),
    Input("vtf-refresh", "n_clicks"),
    Input({"type": "vtf-add", "imo": dash.ALL}, "n_clicks"),
    Input({"type": "vtf-del", "imo": dash.ALL}, "n_clicks"),
    Input({"type": "vtf-del-confirm", "imo": dash.ALL}, "n_clicks"),
    Input({"type": "vtf-del-cancel", "imo": dash.ALL}, "n_clicks"),
    Input({"type": "vtf-edit", "imo": dash.ALL}, "n_clicks"),
    Input({"type": "vtf-nm", "imo": dash.ALL}, "n_clicks"),
    Input("vtf-save", "n_clicks"),
    Input("vtf-cancel", "n_clicks"),
    State({"type": "vtf-f", "field": dash.ALL}, "value"),
    State({"type": "vtf-f", "field": dash.ALL}, "id"),
    State("vtf-pending-delete", "data"),
    State("vtf-editing", "data"),
)
def _fleet_actions(_r, _a, _d, _dc, _dx, _e, _nm, _sv, _cx,
                   f_values, f_ids, pending, editing):
    trig = ctx.triggered_id
    clicked = bool(ctx.triggered) and bool(ctx.triggered[0].get("value"))
    banner, ok = None, True
    new_pending, new_editing = None, editing

    try:
        if clicked and isinstance(trig, dict):
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
                new_editing = str(imo)
            elif kind == "vtf-nm":
                banner, ok = _do_update_name(imo)
        elif clicked and trig == "vtf-save" and editing:
            fields = {fid["field"]: (val or "").strip()
                      for fid, val in zip(f_ids, f_values)}
            banner, ok = _do_save(int(editing), fields)
            new_editing = None
        elif clicked and trig == "vtf-cancel":
            new_editing = None
    except (ais_db.AisDbError, sv_api.SvApiError) as exc:
        banner, ok = str(exc), False
    except Exception as exc:  # never kill the page
        banner, ok = f"Unexpected error: {exc}", False

    # refresh regions from last known positions on every (re)build
    try:
        n_regions = ais_db.fleet_auto_update_regions()
        if n_regions and banner is None:
            banner, ok = f"{n_regions} region(s) updated from last known positions.", True
    except ais_db.AisDbError:
        pass

    try:
        table, counter = _build_table(pending_delete=new_pending,
                                      editing=new_editing)
    except Exception as exc:
        return _banner(str(exc), ok=False), "", None, None, None
    return table, counter, _banner(banner, ok), new_pending, new_editing


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
    for k in ("built", "flag", "region", "tier", "notes"):
        updates[k] = fields.get(k) or None
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
