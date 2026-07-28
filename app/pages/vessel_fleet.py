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


def _build_table(pending_delete=None):
    rows = ais_db.fleet_with_sv()
    n_reg = ais_db.sv_registered_count()
    cap = sv_api.SV_MAX_SHIPS
    at_cap = n_reg >= cap

    headers = ["Vessel", "IMO", "MMSI", "Owner / BB Charterer", "Operator",
               "Built", "Flag", "Region", "Tier", "Notes",
               "SeaVantage", "Action"]
    body = []
    for (imo, mmsi, name, owner, operator, built, flag, region, tier, notes,
         active, ship_id, registered_at, match_result, ais_name) in rows:
        status, action = _status_and_action(imo, registered_at, match_result,
                                            pending_delete)
        if registered_at is None and at_cap:
            action = html.Button("Add", disabled=True, style=_BTN_DISABLED,
                                 title=f"Account limit reached ({cap} vessels)")
        style = {} if active else {"color": "#aeb4bd"}
        def td(c, extra=None, tip=None):
            st = {**_CELL, **style, **(extra or {})}
            return html.Td(c, style=st, title=tip)
        body.append(html.Tr([
            td(name), td(str(imo)), td(str(mmsi or "—")),
            td(owner or "—", _ELLIPSIS, owner), td(operator or "—", _ELLIPSIS, operator),
            td(built or "—"), td(flag or "—"), td(region or "—"), td(tier or "—"),
            td(notes or "—", _ELLIPSIS, notes),
            td(status), td(action),
        ]))

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
    dcc.Loading(html.Div(id="vtf-content"), type="default"),
])


@callback(
    Output("vtf-content", "children"),
    Output("vtf-counter", "children"),
    Output("vtf-banner", "children"),
    Output("vtf-pending-delete", "data"),
    Input("vtf-refresh", "n_clicks"),
    Input({"type": "vtf-add", "imo": dash.ALL}, "n_clicks"),
    Input({"type": "vtf-del", "imo": dash.ALL}, "n_clicks"),
    Input({"type": "vtf-del-confirm", "imo": dash.ALL}, "n_clicks"),
    Input({"type": "vtf-del-cancel", "imo": dash.ALL}, "n_clicks"),
    State("vtf-pending-delete", "data"),
)
def _fleet_actions(_r, _a, _d, _dc, _dx, pending):
    trig = ctx.triggered_id
    # guard against pattern-matched fall-through on (re)render: only act on a
    # real click (triggered value truthy); otherwise just (re)build the table
    clicked = bool(ctx.triggered) and bool(ctx.triggered[0].get("value"))
    banner, ok = None, True
    new_pending = None

    try:
        if isinstance(trig, dict) and clicked:
            imo = int(trig["imo"])
            kind = trig["type"]
            if kind == "vtf-del":
                new_pending = str(imo)                       # step 1 of confirm
            elif kind == "vtf-del-cancel":
                new_pending = None
            elif kind == "vtf-add":
                banner, ok = _do_add(imo)
            elif kind == "vtf-del-confirm":
                banner, ok = _do_remove(imo)
    except (ais_db.AisDbError, sv_api.SvApiError) as exc:
        banner, ok = str(exc), False
    except Exception as exc:  # never kill the page
        banner, ok = f"Unexpected error: {exc}", False

    try:
        table, counter = _build_table(pending_delete=new_pending)
    except (ais_db.AisDbError, Exception) as exc:
        return _banner(str(exc), ok=False), "", None, None
    return table, counter, _banner(banner, ok), new_pending


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
