"""
Admin - Calculation module (admins only).

Four areas on one page:
  Grants      - division x level (edit/read) per user, plus the library-admin
                flag. Stored in calc.db (auth.db untouched). Page visibility is
                still the portal's normal per-page module grant on /admin/users.
  Moderation  - the check-in queue: new items, rate changes, block templates.
                Approving is what writes to the library.
  Rate sets   - create a draft (copied from an existing set), edit fx and
                markups, and activate it (previous active set is archived;
                existing calcs keep their snapshots, by design).
  Backup      - download calc.db (raw) and/or the all-revisions .qcalc ZIP.
"""
import json

import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ALL, ctx
from dash.exceptions import PreventUpdate

from app import auth
from app.adminui import card, btn, is_admin, denied, back_link, MUTED, ACCENT
from app.calcmod import repo, qcalc_io
from app.calcmod.db import CALC_DB

dash.register_page(__name__, path="/admin/calc", name="Calculation module")

LINE = "#e5e7eb"
FIELD = {"padding": "7px 9px", "borderRadius": "8px", "border": f"1px solid {LINE}",
         "fontSize": "0.85rem", "boxSizing": "border-box", "marginRight": "8px"}
NUM = {**FIELD, "width": "110px", "textAlign": "right"}
DD = {"display": "inline-block", "verticalAlign": "middle", "marginRight": "8px",
      "fontSize": "0.85rem"}
DIV_OPTS = [{"label": n, "value": c} for c, n in
            (("CIV", "Civil"), ("OFF", "Offshore"), ("HYD", "Hydropower"),
             ("*", "All divisions"))]
REG_OPTS = [{"label": r, "value": r} for r in ("EUR", "WAF", "UAE", "SEA")]
LEVEL_OPTS = [{"label": "Edit", "value": "edit"}, {"label": "Read-only", "value": "read"}]


# ---------------------------------------------------------------- grants ----
def _grants_table():
    rows = repo.list_grants()
    if not rows:
        return html.P("No grants yet.", style={"color": MUTED})
    th = {"textAlign": "left", "padding": "5px 9px", "fontSize": "0.75rem",
          "color": MUTED, "borderBottom": f"2px solid {LINE}"}
    td = {"padding": "5px 9px", "fontSize": "0.85rem"}
    return html.Table([
        html.Thead(html.Tr([html.Th(h, style=th) for h in
                            ("User", "Division", "Level", "Lib admin", "")])),
        html.Tbody([html.Tr([
            html.Td(g["user"], style=td), html.Td(g["division"], style=td),
            html.Td(g["level"], style=td),
            html.Td("\u2713" if g["lib_admin"] else "", style=td),
            html.Td(html.Button("Remove",
                                id={"type": "ac-grant-del", "user": g["user"],
                                    "div": g["division"]}, n_clicks=0,
                                style={"padding": "4px 9px", "borderRadius": "7px",
                                       "border": "1px solid #fecaca", "background": "#fff",
                                       "color": "#b91c1c", "cursor": "pointer",
                                       "fontSize": "0.75rem"}), style=td),
        ], style={"borderBottom": f"1px solid {LINE}"}) for g in rows]),
    ], style={"borderCollapse": "collapse", "width": "100%"})


# ------------------------------------------------------------ moderation ----
def _queue():
    reqs = repo.list_requests("submitted")
    if not reqs:
        return html.P("The check-in queue is empty.", style={"color": MUTED})
    out = []
    for r in reqs:
        p = r["payload"]
        dup = None
        if r["kind"].endswith("_item"):
            item = p.get("item") or {}
            desc = item.get("description") or item.get("function") or ""
            body = f"{item.get('code')} \u00b7 {desc}"
            dup = repo.find_item_by_code(r["kind"].split("_")[0],
                                         code=item.get("code"),
                                         erp_no=item.get("erp_no"))
            rates = "; ".join(
                f"{x.get('region')}: " + (
                    f"{x.get('office_rate')}/{x.get('yard_rate')}/{x.get('offshore_rate')}"
                    if r["kind"] == "personnel_item" else f"{x.get('rate')}")
                + f" {x.get('currency', 'USD')}" for x in (p.get("rates") or []))
        elif r["kind"] == "rate_change":
            body = f"Rate change for item {p.get('item_uuid')}"
            rates = json.dumps(p.get("rates"))
        else:
            body = f"Block template: {p.get('name')}"
            rates = ""
        out.append(html.Div([
            html.Div([html.B(f"#{r['id']} \u00b7 {r['kind']} \u00b7 {r['division']}"),
                      html.Span(f"  by {r['submitted_by']} \u00b7 {r['submitted_at']}",
                                style={"color": MUTED, "fontSize": "0.8rem"})]),
            html.Div(body, style={"fontSize": "0.88rem", "margin": "4px 0"}),
            html.Div(rates, style={"fontSize": "0.8rem", "color": MUTED}),
            html.Div(r.get("note") or "", style={"fontSize": "0.8rem", "color": MUTED,
                                                 "fontStyle": "italic"}),
            (html.Div(f"\u26a0 duplicate: {dup['code']} already exists - reject, or "
                      "ask for a rate-change request instead.",
                      style={"color": "#b91c1c", "fontSize": "0.8rem",
                             "fontWeight": 600}) if dup else None),
            html.Div([
                html.Button("Approve", id={"type": "ac-req-ok", "id": r["id"]},
                            n_clicks=0, disabled=bool(dup),
                            style={"padding": "6px 12px",
                                   "borderRadius": "8px", "border": "none",
                                   "background": ACCENT, "color": "#fff",
                                   "fontWeight": 600, "cursor": "pointer",
                                   "marginRight": "8px", "fontSize": "0.8rem",
                                   "opacity": 0.4 if dup else 1}),
                html.Button("Reject", id={"type": "ac-req-no", "id": r["id"]},
                            n_clicks=0, style={"padding": "6px 12px",
                                               "borderRadius": "8px",
                                               "border": "1px solid #fecaca",
                                               "background": "#fff", "color": "#b91c1c",
                                               "cursor": "pointer",
                                               "fontSize": "0.8rem"}),
            ], style={"marginTop": "6px"}),
        ], style={"borderBottom": f"1px solid {LINE}", "padding": "10px 0"}))
    return html.Div(out)


# ------------------------------------------------------- misc categories ----
def _cats_table():
    cats = repo.list_misc_categories(active_only=False)
    th = {"textAlign": "left", "padding": "5px 9px", "fontSize": "0.75rem",
          "color": MUTED, "borderBottom": f"2px solid {LINE}"}
    td = {"padding": "5px 9px", "fontSize": "0.85rem"}
    return html.Table([
        html.Thead(html.Tr([html.Th(h, style=th) for h in
                            ("Category", "Element", "Active", "")])),
        html.Tbody([html.Tr([
            html.Td(c["name"], style=td), html.Td(c["element"], style=td),
            html.Td("✓" if c["active"] else "—", style=td),
            html.Td(html.Button("Deactivate" if c["active"] else "Reactivate",
                                id={"type": "ac-cat-tgl", "name": c["name"],
                                    "el": c["element"], "act": c["active"]},
                                n_clicks=0,
                                style={"padding": "4px 9px", "borderRadius": "7px",
                                       "border": f"1px solid {LINE}",
                                       "background": "#fff", "cursor": "pointer",
                                       "fontSize": "0.75rem"}), style=td),
        ], style={"borderBottom": f"1px solid {LINE}"}) for c in cats]),
    ], style={"borderCollapse": "collapse", "width": "100%"})


@callback(Output("ac-cats", "children"),
          Output("ac-cat-status", "children"),
          Input("ac-cat-save", "n_clicks"),
          Input({"type": "ac-cat-tgl", "name": ALL, "el": ALL, "act": ALL}, "n_clicks"),
          State("ac-cat-name", "value"), State("ac-cat-el", "value"),
          prevent_initial_call=True)
def _cats(n_save, _n_tgl, name, element):
    if not is_admin():
        raise PreventUpdate
    trig = ctx.triggered_id
    if isinstance(trig, dict):
        if not ctx.triggered[0]["value"]:
            raise PreventUpdate
        repo.set_misc_category(trig["name"], trig["el"], active=not trig["act"])
        return _cats_table(), ""
    if not (n_save and name and element):
        return no_update, "Category name and element are required."
    repo.set_misc_category(name, element)
    return _cats_table(), f"Saved '{name.strip().lower()}' → {element}."


# ------------------------------------------------------------- rate sets ----
def _rs_panel():
    sets = repo.list_rate_sets()
    rs_opts = [{"label": f"{r['label']} \u00b7 {r['status']}", "value": r["id"]}
               for r in sets]
    return html.Div([
        html.Div([
            dcc.Input(id="ac-rs-label", placeholder="New rate set label (e.g. 2026-H2)",
                      style={**FIELD, "width": "260px"}),
            dcc.Dropdown(id="ac-rs-copy", options=rs_opts, placeholder="Copy from\u2026",
                         style={**DD, "width": "220px"}),
            html.Button("Create draft", id="ac-rs-create", n_clicks=0,
                        style={"padding": "8px 14px", "borderRadius": "8px",
                               "border": "none", "background": ACCENT, "color": "#fff",
                               "fontWeight": 600, "cursor": "pointer"}),
        ], style={"marginBottom": "10px"}),
        html.Div([
            dcc.Dropdown(id="ac-rs-sel", options=rs_opts, placeholder="Select a rate set",
                         style={**DD, "width": "240px"}),
            html.Button("Activate (archive current)", id="ac-rs-activate", n_clicks=0,
                        style={"padding": "8px 14px", "borderRadius": "8px",
                               "border": f"1px solid {LINE}", "background": "#fff",
                               "cursor": "pointer", "fontWeight": 600}),
        ], style={"marginBottom": "10px"}),
        html.Div([
            html.H5("FX (1 unit \u2192 USD)", style={"margin": "8px 0 4px"}),
            dcc.Input(id="ac-fx-cur", placeholder="Currency (EUR)",
                      style={**FIELD, "width": "130px"}),
            dcc.Input(id="ac-fx-rate", type="number", placeholder="Rate to USD",
                      style=NUM),
            html.Button("Set FX", id="ac-fx-set", n_clicks=0,
                        style={"padding": "7px 12px", "borderRadius": "8px",
                               "border": f"1px solid {LINE}", "background": "#fff",
                               "cursor": "pointer"}),
        ]),
        html.Div([
            html.H5("Markups (fractions, e.g. 0.10 = 10%)", style={"margin": "12px 0 4px"}),
            dcc.Dropdown(id="ac-mk-div", options=DIV_OPTS[:3], placeholder="Division",
                         style={**DD, "width": "150px"}),
            dcc.Dropdown(id="ac-mk-reg", options=REG_OPTS, placeholder="Region",
                         style={**DD, "width": "120px"}),
            dcc.Input(id="ac-mk-ll", type="number", placeholder="Levy local", style=NUM),
            dcc.Input(id="ac-mk-le", type="number", placeholder="Levy expat", style=NUM),
            dcc.Input(id="ac-mk-oh", type="number", placeholder="Overhead", style=NUM),
            dcc.Input(id="ac-mk-rk", type="number", placeholder="Risk", style=NUM),
            dcc.Input(id="ac-mk-pf", type="number", placeholder="Profit", style=NUM),
            dcc.Input(id="ac-mk-mg", type="number", placeholder="Margin", style=NUM),
            html.Button("Save markups", id="ac-mk-set", n_clicks=0,
                        style={"padding": "7px 12px", "borderRadius": "8px",
                               "border": f"1px solid {LINE}", "background": "#fff",
                               "cursor": "pointer", "marginTop": "6px"}),
        ]),
        html.Div(id="ac-rs-status", style={"fontSize": "0.85rem", "marginTop": "8px",
                                           "minHeight": "1.1em"}),
    ])


def layout():
    if not is_admin():
        return denied()
    return html.Div([
        back_link(),
        html.H3("Calculation module"),

        card([html.H4("Division grants", style={"marginTop": 0}),
              html.P("Who may edit or read calculations per division, and who moderates "
                     "the libraries. Page access itself is granted on Users & access.",
                     style={"color": MUTED, "fontSize": "0.85rem"}),
              html.Div(id="ac-grants", children=_grants_table()),
              html.Div([
                  dcc.Input(id="ac-grant-user", placeholder="User e-mail",
                            style={**FIELD, "width": "240px"}),
                  dcc.Dropdown(id="ac-grant-div", options=DIV_OPTS, placeholder="Division",
                               style={**DD, "width": "170px"}),
                  dcc.Dropdown(id="ac-grant-level", options=LEVEL_OPTS,
                               placeholder="Level", style={**DD, "width": "140px"}),
                  dcc.Checklist(id="ac-grant-lib",
                                options=[{"label": " library admin", "value": "yes"}],
                                value=[], style={"display": "inline-block",
                                                 "marginRight": "8px"}),
                  btn("Save grant", "ac-grant-save"),
              ], style={"marginTop": "10px"}),
              html.Div(id="ac-grant-status", style={"fontSize": "0.85rem",
                                                    "marginTop": "8px",
                                                    "minHeight": "1.1em"})]),

        card([html.H4("Library check-in queue", style={"marginTop": 0}),
              html.Div(id="ac-queue", children=_queue()),
              html.Div(id="ac-queue-status", style={"fontSize": "0.85rem",
                                                    "color": "#b91c1c",
                                                    "marginTop": "8px",
                                                    "minHeight": "1.1em"})]),

        card([html.H4("Misc sub-categories", style={"marginTop": 0}),
              html.P("Each sub-category maps to the element it prefills in the editor: "
                     "materials or sub-contracting. Deactivating hides it from new "
                     "check-ins; existing items keep their category.",
                     style={"color": MUTED, "fontSize": "0.85rem"}),
              html.Div(id="ac-cats", children=_cats_table()),
              html.Div([
                  dcc.Input(id="ac-cat-name", placeholder="Category name",
                            style={**FIELD, "width": "220px"}),
                  dcc.Dropdown(id="ac-cat-el",
                               options=[{"label": "Materials", "value": "materials"},
                                        {"label": "Sub-contracting",
                                         "value": "subcontracting"}],
                               placeholder="Element", style={**DD, "width": "180px"}),
                  btn("Save category", "ac-cat-save"),
              ], style={"marginTop": "10px"}),
              html.Div(id="ac-cat-status", style={"fontSize": "0.85rem",
                                                  "marginTop": "8px",
                                                  "minHeight": "1.1em"})]),

        card([html.H4("Rate sets, FX & markups", style={"marginTop": 0}),
              html.P("Rates live in versioned sets; existing calculations keep their "
                     "embedded snapshot when a new set goes active.",
                     style={"color": MUTED, "fontSize": "0.85rem"}),
              _rs_panel()]),

        card([html.H4("Backup", style={"marginTop": 0}),
              html.P(["Two layers: the raw database (", html.Code("calc.db"),
                      ") and a ZIP with every revision of every calculation as a "
                      "self-contained .qcalc file for the corporate network."],
                     style={"color": MUTED, "fontSize": "0.85rem"}),
              btn("Download calc.db", "ac-bk-db"),
              btn("Download .qcalc ZIP", "ac-bk-zip"),
              dcc.Download(id="ac-bk-download")]),
    ])


# ------------------------------------------------------------- callbacks ----
@callback(Output("ac-grants", "children"),
          Output("ac-grant-status", "children"),
          Input("ac-grant-save", "n_clicks"),
          Input({"type": "ac-grant-del", "user": ALL, "div": ALL}, "n_clicks"),
          State("ac-grant-user", "value"), State("ac-grant-div", "value"),
          State("ac-grant-level", "value"), State("ac-grant-lib", "value"),
          prevent_initial_call=True)
def _grants(n_save, _n_del, user, division, level, lib):
    if not is_admin():
        raise PreventUpdate
    trig = ctx.triggered_id
    if isinstance(trig, dict):
        if not ctx.triggered[0]["value"]:
            raise PreventUpdate
        repo.delete_grant(trig["user"], trig["div"])
        return _grants_table(), f"Removed grant for {trig['user']}."
    if not (n_save and user and division and level):
        return no_update, "User, division and level are required."
    repo.set_grant(user.strip().lower(), division, level, lib_admin=bool(lib))
    return _grants_table(), f"Saved grant for {user.strip().lower()}."


@callback(Output("ac-queue", "children"),
          Output("ac-queue-status", "children"),
          Input({"type": "ac-req-ok", "id": ALL}, "n_clicks"),
          Input({"type": "ac-req-no", "id": ALL}, "n_clicks"),
          prevent_initial_call=True)
def _review(_ok, _no):
    if not is_admin():
        raise PreventUpdate
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    user = auth.current_user()
    err = repo.review_request(trig["id"], trig["type"] == "ac-req-ok",
                              user["email"] if user else "admin")
    return _queue(), (err or "")


@callback(Output("ac-rs-status", "children"),
          Input("ac-rs-create", "n_clicks"), Input("ac-rs-activate", "n_clicks"),
          Input("ac-fx-set", "n_clicks"), Input("ac-mk-set", "n_clicks"),
          State("ac-rs-label", "value"), State("ac-rs-copy", "value"),
          State("ac-rs-sel", "value"),
          State("ac-fx-cur", "value"), State("ac-fx-rate", "value"),
          State("ac-mk-div", "value"), State("ac-mk-reg", "value"),
          State("ac-mk-ll", "value"), State("ac-mk-le", "value"),
          State("ac-mk-oh", "value"), State("ac-mk-rk", "value"),
          State("ac-mk-pf", "value"), State("ac-mk-mg", "value"),
          prevent_initial_call=True)
def _rates(n_cr, n_act, n_fx, n_mk, label, copy_from, sel, fx_cur, fx_rate,
           mk_div, mk_reg, ll, le, oh, rk, pf, mg):
    if not is_admin():
        raise PreventUpdate
    user = auth.current_user()
    trig = ctx.triggered_id
    if trig == "ac-rs-create":
        if not label:
            return "Give the new rate set a label."
        try:
            repo.create_rate_set(label.strip(), user["email"] if user else "admin",
                                 copy_from_id=copy_from)
        except Exception as e:
            return f"Could not create: {e}"
        return f"Draft rate set '{label.strip()}' created. Reload the page to select it."
    if trig == "ac-rs-activate":
        if not sel:
            return "Select the rate set to activate."
        repo.activate_rate_set(sel)
        return "Activated. New calculations now snapshot from this set."
    if trig == "ac-fx-set":
        if not (sel and fx_cur and fx_rate):
            return "Select a rate set and give currency + rate."
        repo.add_currency(fx_cur.strip().upper(), fx_cur.strip().upper())
        repo.set_fx(sel, fx_cur.strip().upper(), float(fx_rate))
        return f"FX {fx_cur.strip().upper()} \u2192 USD = {fx_rate} saved."
    if trig == "ac-mk-set":
        if not (sel and mk_div and mk_reg):
            return "Select a rate set, division and region."
        repo.set_markups(sel, mk_div, mk_reg, levy_local_pct=ll, levy_expat_pct=le,
                         overhead_pct=oh, risk_pct=rk, profit_pct=pf, margin_pct=mg)
        return f"Markups saved for {mk_div} \u00b7 {mk_reg}."
    raise PreventUpdate


@callback(Output("ac-bk-download", "data"),
          Input("ac-bk-db", "n_clicks"), Input("ac-bk-zip", "n_clicks"),
          prevent_initial_call=True)
def _backup(n_db, n_zip):
    if not is_admin():
        raise PreventUpdate
    trig = ctx.triggered_id
    if trig == "ac-bk-db" and n_db:
        with open(CALC_DB, "rb") as fh:
            data = fh.read()
        return dcc.send_bytes(lambda f: f.write(data), "calc.db")
    if trig == "ac-bk-zip" and n_zip:
        zb = qcalc_io.backup_zip_bytes()
        return dcc.send_bytes(lambda f: f.write(zb), "calc_backup_qcalc.zip")
    raise PreventUpdate
