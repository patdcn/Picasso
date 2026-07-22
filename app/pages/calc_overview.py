"""
Calculation - DCN Calculations (module v1) - overview page.

Lists every calculation the signed-in user may see (division grants from
calc.db), with latest revision, status and lock holder. From here: create a
new calc (Q number typed in - they are generated in Business Central), open
one in the editor, duplicate a calc to a new Q number, or import a .qcalc
file (as a new Q or as the next revision of its own Q).

Access model: the portal's per-page module grant gates the page itself; the
division x level grants (Admin -> Calculation module) decide which divisions
are visible and whether the editor opens read-only.
"""
import base64
import json

import dash
from dash import html, dcc, Input, Output, State, callback, no_update

from app import auth
from app.calcmod import repo, qcalc_io

dash.register_page(__name__, path="/calculation/calcs", name="DCN Calculations",
                   title="DCN Calculations", category="Calculation", order=2)

MODULE = "/calculation/calcs"

INK, MUTED, TEAL, LINE = "#1f2937", "#6b7280", "#0f766e", "#e5e7eb"
PANEL = "#f8fafc"
BTN = {"padding": "8px 14px", "borderRadius": "8px", "border": "none", "background": TEAL,
       "color": "#fff", "fontWeight": 600, "cursor": "pointer", "fontSize": "0.85rem"}
BTN_GHOST = {"padding": "6px 11px", "borderRadius": "8px", "border": f"1px solid {LINE}",
             "background": "#fff", "color": INK, "cursor": "pointer", "fontSize": "0.8rem"}
FIELD = {"padding": "7px 9px", "borderRadius": "8px", "border": f"1px solid {LINE}",
         "fontSize": "0.85rem", "boxSizing": "border-box"}
CARD = {"background": "#fff", "border": f"1px solid {LINE}", "borderRadius": "12px",
        "padding": "16px", "marginBottom": "16px"}

DIV_LABEL = {"CIV": "Civil", "OFF": "Offshore", "HYD": "Hydropower"}


def _user():
    return auth.current_user()


def _divs(user):
    return repo.visible_divisions(user["email"], user.get("is_admin"))


def _table(user):
    divs = _divs(user)
    calcs = repo.list_calcs(divs)
    if not calcs:
        return html.P("No calculations yet in your divisions.", style={"color": MUTED})
    head = html.Tr([html.Th(h, style={"textAlign": "left", "padding": "6px 10px",
                                      "borderBottom": f"2px solid {LINE}", "fontSize": "0.8rem",
                                      "color": MUTED})
                    for h in ("Q number", "Title", "Client", "Division", "Region",
                              "Rev", "Status", "Lock", "")])
    rows = []
    for cal in calcs:
        lock = ""
        if cal["locked_by"]:
            st = repo.lock_status(cal["qnumber"])
            if st and not st["stale"]:
                lock = f"\U0001f512 {cal['locked_by']}"
        badge_bg = "#dcfce7" if cal["latest_status"] == "issued" else "#fef9c3"
        rows.append(html.Tr([
            html.Td(html.B(cal["qnumber"]), style={"padding": "6px 10px"}),
            html.Td(cal["title"], style={"padding": "6px 10px"}),
            html.Td(cal.get("client") or "", style={"padding": "6px 10px"}),
            html.Td(DIV_LABEL.get(cal["division"], cal["division"]), style={"padding": "6px 10px"}),
            html.Td(cal["region"], style={"padding": "6px 10px"}),
            html.Td(f"Rev {cal['latest_rev']}", style={"padding": "6px 10px"}),
            html.Td(html.Span(cal["latest_status"], style={
                "background": badge_bg, "borderRadius": "6px", "padding": "2px 8px",
                "fontSize": "0.75rem"}), style={"padding": "6px 10px"}),
            html.Td(lock, style={"padding": "6px 10px", "fontSize": "0.8rem", "color": MUTED}),
            html.Td(dcc.Link("Open", href=f"/calculation/editor?q={cal['qnumber']}",
                             style={"color": TEAL, "fontWeight": 600}),
                    style={"padding": "6px 10px"}),
        ], style={"borderBottom": f"1px solid {LINE}"}))
    return html.Table([html.Thead(head), html.Tbody(rows)],
                      style={"borderCollapse": "collapse", "width": "100%",
                             "fontSize": "0.88rem"})


def layout(**_qs):
    user = _user()
    if not user:
        return html.Div()
    divs = _divs(user)
    can_edit_any = user.get("is_admin") or any(
        (repo.get_grant(user["email"], d) or {}).get("level") == "edit" for d in divs)
    div_opts = [{"label": DIV_LABEL[d], "value": d} for d in divs]
    reg_opts = [{"label": r, "value": r} for r in ("EUR", "WAF", "UAE", "SEA")]

    new_card = html.Div([
        html.H4("New calculation", style={"marginTop": 0}),
        html.Div([
            dcc.Input(id="co-new-q", placeholder="Q number (Q0XXXX, from Business Central)",
                      style={**FIELD, "width": "280px", "marginRight": "8px"}),
            dcc.Input(id="co-new-title", placeholder="Title",
                      style={**FIELD, "width": "280px", "marginRight": "8px"}),
            dcc.Input(id="co-new-client", placeholder="Client",
                      style={**FIELD, "width": "200px", "marginRight": "8px"}),
            dcc.Dropdown(id="co-new-div", options=div_opts, placeholder="Division",
                         style={"width": "160px", "display": "inline-block",
                                "verticalAlign": "middle", "marginRight": "8px"}),
            dcc.Dropdown(id="co-new-region", options=reg_opts, placeholder="Region",
                         style={"width": "130px", "display": "inline-block",
                                "verticalAlign": "middle", "marginRight": "8px"}),
            html.Button("Create", id="co-new-btn", n_clicks=0, style=BTN),
        ]),
        html.Div(id="co-new-status", style={"fontSize": "0.85rem", "marginTop": "8px",
                                            "minHeight": "1.1em"}),
    ], style=CARD) if can_edit_any else None

    dup_card = html.Div([
        html.H4("Duplicate a calculation", style={"marginTop": 0}),
        html.P("Copies the latest revision of an existing calc into rev 0 of a new Q number. "
               "Embedded rates travel unchanged; updating against the current library is a "
               "separate action inside the editor.", style={"color": MUTED, "fontSize": "0.83rem"}),
        html.Div([
            dcc.Dropdown(id="co-dup-src", placeholder="Source calculation",
                         options=[{"label": f"{cal['qnumber']} \u2014 {cal['title']}",
                                   "value": cal["qnumber"]} for cal in repo.list_calcs(divs)],
                         style={"width": "340px", "display": "inline-block",
                                "verticalAlign": "middle", "marginRight": "8px"}),
            dcc.Input(id="co-dup-q", placeholder="New Q number",
                      style={**FIELD, "width": "180px", "marginRight": "8px"}),
            dcc.Input(id="co-dup-title", placeholder="New title",
                      style={**FIELD, "width": "260px", "marginRight": "8px"}),
            html.Button("Duplicate", id="co-dup-btn", n_clicks=0, style=BTN),
        ]),
        html.Div(id="co-dup-status", style={"fontSize": "0.85rem", "marginTop": "8px",
                                            "minHeight": "1.1em"}),
    ], style=CARD) if can_edit_any else None

    imp_card = html.Div([
        html.H4("Import a .qcalc file", style={"marginTop": 0}),
        html.P("A .qcalc exported from this portal (e.g. archived on the corporate network). "
               "If its Q number exists here it becomes the next revision; otherwise it is "
               "created under its own Q number. Or give a new Q number to import it as a "
               "fresh calculation.", style={"color": MUTED, "fontSize": "0.83rem"}),
        html.Div([
            dcc.Upload(id="co-imp-up", children=html.Button("Choose .qcalc file",
                                                            style=BTN_GHOST),
                       accept=".qcalc,application/json", multiple=False,
                       style={"display": "inline-block", "marginRight": "10px"}),
            dcc.Input(id="co-imp-q", placeholder="Import as new Q number (optional)",
                      style={**FIELD, "width": "280px"}),
        ]),
        html.Div(id="co-imp-status", style={"fontSize": "0.85rem", "marginTop": "8px",
                                            "minHeight": "1.1em"}),
    ], style=CARD) if can_edit_any else None

    return html.Div([
        html.H3("DCN Calculations"),
        html.P("Q numbers come from Business Central; revisions and embedded rate snapshots "
               "are managed here. Open a calculation to edit (with the lock) or view it "
               "read-only, live.", style={"color": MUTED, "maxWidth": "720px"}),
        new_card, dup_card, imp_card,
        html.Div(id="co-table", children=_table(user), style=CARD),
    ])


@callback(Output("co-new-status", "children"),
          Output("co-table", "children", allow_duplicate=True),
          Input("co-new-btn", "n_clicks"),
          State("co-new-q", "value"), State("co-new-title", "value"),
          State("co-new-client", "value"), State("co-new-div", "value"),
          State("co-new-region", "value"), prevent_initial_call=True)
def _create(n, q, title, client, division, region):
    user = _user()
    if not n or not user:
        return no_update, no_update
    q = (q or "").strip().upper()
    if not (q and title and division and region):
        return "Q number, title, division and region are required.", no_update
    g = repo.get_grant(user["email"], division)
    if not (user.get("is_admin") or (g and g["level"] == "edit")):
        return f"You have no edit rights in {DIV_LABEL.get(division, division)}.", no_update
    if repo.get_calc(q):
        return f"{q} already exists.", no_update
    try:
        repo.create_calc(q, title.strip(), (client or "").strip() or None,
                         division, region, user["email"])
    except Exception as e:
        return f"Could not create: {e}", no_update
    return f"{q} created (rev 0).", _table(user)


@callback(Output("co-dup-status", "children"),
          Output("co-table", "children", allow_duplicate=True),
          Input("co-dup-btn", "n_clicks"),
          State("co-dup-src", "value"), State("co-dup-q", "value"),
          State("co-dup-title", "value"), prevent_initial_call=True)
def _duplicate(n, src, new_q, title):
    user = _user()
    if not n or not user:
        return no_update, no_update
    new_q = (new_q or "").strip().upper()
    if not (src and new_q and title):
        return "Source, new Q number and new title are required.", no_update
    src_calc = repo.get_calc(src)
    g = repo.get_grant(user["email"], src_calc["division"]) if src_calc else None
    if not (user.get("is_admin") or (g and g["level"] == "edit")):
        return "You have no edit rights in the source calc's division.", no_update
    if repo.get_calc(new_q):
        return f"{new_q} already exists.", no_update
    try:
        repo.duplicate_calc(src, new_q, title.strip(), src_calc.get("client"), user["email"])
    except Exception as e:
        return f"Could not duplicate: {e}", no_update
    return f"{new_q} created from {src}.", _table(user)


@callback(Output("co-imp-status", "children"),
          Output("co-table", "children", allow_duplicate=True),
          Input("co-imp-up", "contents"),
          State("co-imp-up", "filename"), State("co-imp-q", "value"),
          prevent_initial_call=True)
def _import(contents, filename, new_q):
    user = _user()
    if not contents or not user:
        return no_update, no_update
    try:
        raw = base64.b64decode(contents.split(",", 1)[1])
        data = json.loads(raw)
    except Exception:
        return f"{filename}: not readable as a .qcalc file.", no_update
    division = (data.get("calc") or {}).get("division")
    g = repo.get_grant(user["email"], division) if division else None
    if not (user.get("is_admin") or (g and g["level"] == "edit")):
        return "You have no edit rights in this file's division.", no_update
    try:
        q, r = qcalc_io.import_qcalc(
            data, user["email"], as_new_qnumber=(new_q or "").strip().upper() or None)
    except Exception as e:
        return f"Import failed: {e}", no_update
    return f"Imported as {q} rev {r}.", _table(user)
