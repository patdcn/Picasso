"""
Calculation - Calculation admin (module v1).

All calc-module administration lives HERE, under the Calculation menu - not
in the portal /admin area. Access: calc super-users and portal admins (the
portal's per-page grant on this path is the outer gate as usual; the inner
gate is the role).

Content: rate sets (create draft / copy / activate), markups per division x
region, misc sub-categories (materials / sub-contracting), backups (raw
calc.db + all-revisions .qcalc ZIP), and a read-only overview of calc roles.
Role ASSIGNMENT happens on Admin -> Users & access (portal admins), per the
agreed model: page access + role 'user' (make calculations) or 'super'
(moderate libraries, rates, currencies). Currencies & FX are managed on the
Calculation libraries page.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ALL, ctx
from dash.exceptions import PreventUpdate

from app import auth
from app.calcmod import repo, qcalc_io
from app.calcmod.db import CALC_DB

dash.register_page(__name__, path="/calculation/admin", name="Calculation admin",
                   title="Calculation admin", category="Calculation", order=6)

MODULE = "/calculation/admin"

INK, MUTED, TEAL, LINE, RED = "#1f2937", "#6b7280", "#0f766e", "#e5e7eb", "#b91c1c"
BTN = {"padding": "8px 14px", "borderRadius": "8px", "border": "none",
       "background": TEAL, "color": "#fff", "fontWeight": 600, "cursor": "pointer",
       "fontSize": "0.85rem", "marginRight": "8px"}
BTN_GHOST = {"padding": "7px 12px", "borderRadius": "8px",
             "border": f"1px solid {LINE}", "background": "#fff", "color": INK,
             "cursor": "pointer", "fontSize": "0.82rem", "marginRight": "8px"}
FIELD = {"padding": "7px 9px", "borderRadius": "8px", "border": f"1px solid {LINE}",
         "fontSize": "0.85rem", "boxSizing": "border-box", "marginRight": "8px"}
NUM = {**FIELD, "width": "110px", "textAlign": "right"}
CARD = {"background": "#fff", "border": f"1px solid {LINE}", "borderRadius": "12px",
        "padding": "16px", "marginBottom": "16px"}
DD = {"display": "inline-block", "verticalAlign": "middle", "marginRight": "8px",
      "fontSize": "0.85rem"}
DIV_OPTS = [{"label": n, "value": c} for c, n in
            (("CIV", "Civil"), ("OFF", "Offshore"), ("HYD", "Hydropower"))]
REG_OPTS = [{"label": r, "value": r} for r in ("EUR", "WAF", "UAE", "SEA")]


def _may():
    user = auth.current_user()
    return bool(user and (user.get("is_admin")
                          or repo.get_role(user["email"]) == "super"))


# ---------------------------------------------------------------- cards ----
def _cats_table():
    cats = repo.list_misc_categories(active_only=False)
    th = {"textAlign": "left", "padding": "5px 9px", "fontSize": "0.75rem",
          "color": MUTED, "borderBottom": f"2px solid {LINE}"}
    td = {"padding": "5px 9px", "fontSize": "0.85rem"}

    def _tbl(element, title):
        rows = [c for c in cats if c["element"] == element]
        return html.Div([
            html.H5(title, style={"margin": "10px 0 4px"}),
            html.Table([
                html.Thead(html.Tr([html.Th(h, style=th) for h in
                                    ("Sub-category", "Active", "")])),
                html.Tbody([html.Tr([
                    html.Td(c["name"], style=td),
                    html.Td("\u2713" if c["active"] else "\u2014", style=td),
                    html.Td(html.Button(
                        "Deactivate" if c["active"] else "Reactivate",
                        id={"type": "ca-cat-tgl", "name": c["name"],
                            "el": c["element"], "act": c["active"]},
                        n_clicks=0, style={**BTN_GHOST, "fontSize": "0.75rem",
                                           "padding": "4px 9px"}), style=td),
                ], style={"borderBottom": f"1px solid {LINE}"}) for c in rows]),
            ], style={"borderCollapse": "collapse", "width": "100%"}),
        ])

    return html.Div([_tbl("materials", "Materials sub-categories"),
                     _tbl("subcontracting", "Sub-contracting sub-categories")])


def _roles_table():
    roles = repo.list_roles()
    if not roles:
        return html.P("No calc roles assigned yet.", style={"color": MUTED})
    td = {"padding": "4px 10px", "fontSize": "0.85rem"}
    return html.Table([html.Tbody([
        html.Tr([html.Td(r["user"], style=td),
                 html.Td(r["role"], style={**td, "fontWeight": 600,
                                           "color": TEAL if r["role"] == "super"
                                           else INK})])
        for r in roles])], style={"borderCollapse": "collapse"})


def _rs_panel():
    sets = repo.list_rate_sets()
    rs_opts = [{"label": f"{r['label']} \u00b7 {r['status']}", "value": r["id"]}
               for r in sets]
    return html.Div([
        html.Div([
            dcc.Input(id="ca-rs-label", placeholder="New rate set label (e.g. 2026-H2)",
                      style={**FIELD, "width": "260px"}),
            dcc.Dropdown(id="ca-rs-copy", options=rs_opts, placeholder="Copy from\u2026",
                         style={**DD, "width": "220px"}),
            html.Button("Create draft", id="ca-rs-create", n_clicks=0, style=BTN),
        ], style={"marginBottom": "10px"}),
        html.Div([
            dcc.Dropdown(id="ca-rs-sel", options=rs_opts, placeholder="Select a rate set",
                         style={**DD, "width": "240px"}),
            html.Button("Activate (archive current)", id="ca-rs-activate", n_clicks=0,
                        style=BTN_GHOST),
        ], style={"marginBottom": "10px"}),
        html.Div([
            html.H5("Markups (fractions, e.g. 0.10 = 10%)", style={"margin": "12px 0 4px"}),
            dcc.Dropdown(id="ca-mk-div", options=DIV_OPTS, placeholder="Division",
                         style={**DD, "width": "150px"}),
            dcc.Dropdown(id="ca-mk-reg", options=REG_OPTS, placeholder="Region",
                         style={**DD, "width": "120px"}),
            dcc.Input(id="ca-mk-ll", type="number", placeholder="Levy local", style=NUM),
            dcc.Input(id="ca-mk-le", type="number", placeholder="Levy expat", style=NUM),
            dcc.Input(id="ca-mk-oh", type="number", placeholder="Overhead", style=NUM),
            dcc.Input(id="ca-mk-rk", type="number", placeholder="Risk", style=NUM),
            dcc.Input(id="ca-mk-pf", type="number", placeholder="Profit", style=NUM),
            dcc.Input(id="ca-mk-mg", type="number", placeholder="Margin", style=NUM),
            html.Button("Save markups", id="ca-mk-set", n_clicks=0,
                        style={**BTN_GHOST, "marginTop": "6px"}),
        ]),
        html.Div(id="ca-rs-status", style={"fontSize": "0.85rem", "marginTop": "8px",
                                           "minHeight": "1.1em"}),
    ])


def layout(**_qs):
    user = auth.current_user()
    if not user:
        return html.Div()
    if not _may():
        return html.Div([
            html.H3("Calculation admin"),
            html.P("This area is for calc super-users and portal administrators. "
                   "Ask an administrator for the super role on "
                   "Admin \u2192 Users & access.", style={"color": MUTED}),
        ])
    return html.Div([
        html.H3("Calculation admin"),
        html.P("Rate sets, markups, sub-categories and backups for the calculation "
               "module. Currencies & FX are on the Calculation libraries page; "
               "role assignment is on Admin \u2192 Users & access.",
               style={"color": MUTED, "maxWidth": "760px"}),

        html.Div([html.H4("Rate sets & markups", style={"marginTop": 0}),
                  html.P("Rates live in versioned sets; existing calculations keep "
                         "their embedded snapshot when a new set goes active.",
                         style={"color": MUTED, "fontSize": "0.85rem"}),
                  _rs_panel()], style=CARD),

        html.Div([html.H4("Sub-categories (Materials & Sub-contracting)",
                          style={"marginTop": 0}),
                  html.P("Each sub-category maps to the element it prefills in the "
                         "editor. Deactivating hides it from new check-ins; existing "
                         "items keep their category.",
                         style={"color": MUTED, "fontSize": "0.85rem"}),
                  html.Div(id="ca-cats", children=_cats_table()),
                  html.Div([
                      dcc.Input(id="ca-cat-name", placeholder="Category name",
                                style={**FIELD, "width": "220px"}),
                      dcc.Dropdown(id="ca-cat-el",
                                   options=[{"label": "Materials", "value": "materials"},
                                            {"label": "Sub-contracting",
                                             "value": "subcontracting"}],
                                   placeholder="Element", style={**DD, "width": "180px"}),
                      html.Button("Save category", id="ca-cat-save", n_clicks=0,
                                  style=BTN),
                  ], style={"marginTop": "10px"}),
                  html.Div(id="ca-cat-status", style={"fontSize": "0.85rem",
                                                      "marginTop": "8px",
                                                      "minHeight": "1.1em"})],
                 style=CARD),

        html.Div([html.H4("Calc roles (read-only)", style={"marginTop": 0}),
                  html.P("user = may create/edit calculations \u00b7 super = moderator "
                         "(libraries, rates, currencies, this page). Assign on "
                         "Admin \u2192 Users & access.",
                         style={"color": MUTED, "fontSize": "0.85rem"}),
                  _roles_table()], style=CARD),

        html.Div([html.H4("Backup", style={"marginTop": 0}),
                  html.P(["Two layers: the raw database (", html.Code("calc.db"),
                          ") and a ZIP with every revision of every calculation as "
                          "a self-contained .qcalc file for the corporate network."],
                         style={"color": MUTED, "fontSize": "0.85rem"}),
                  html.Button("Download calc.db", id="ca-bk-db", n_clicks=0, style=BTN),
                  html.Button("Download .qcalc ZIP", id="ca-bk-zip", n_clicks=0,
                              style=BTN),
                  dcc.Download(id="ca-bk-download")], style=CARD),
    ])


# ------------------------------------------------------------- callbacks ----
@callback(Output("ca-cats", "children"),
          Output("ca-cat-status", "children"),
          Input("ca-cat-save", "n_clicks"),
          Input({"type": "ca-cat-tgl", "name": ALL, "el": ALL, "act": ALL}, "n_clicks"),
          State("ca-cat-name", "value"), State("ca-cat-el", "value"),
          prevent_initial_call=True)
def _cats(n_save, _n_tgl, name, element):
    if not _may():
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
    return _cats_table(), f"Saved '{name.strip().lower()}' \u2192 {element}."


@callback(Output("ca-rs-status", "children"),
          Input("ca-rs-create", "n_clicks"), Input("ca-rs-activate", "n_clicks"),
          Input("ca-mk-set", "n_clicks"),
          State("ca-rs-label", "value"), State("ca-rs-copy", "value"),
          State("ca-rs-sel", "value"),
          State("ca-mk-div", "value"), State("ca-mk-reg", "value"),
          State("ca-mk-ll", "value"), State("ca-mk-le", "value"),
          State("ca-mk-oh", "value"), State("ca-mk-rk", "value"),
          State("ca-mk-pf", "value"), State("ca-mk-mg", "value"),
          prevent_initial_call=True)
def _rates(n_cr, n_act, n_mk, label, copy_from, sel, mk_div, mk_reg,
           ll, le, oh, rk, pf, mg):
    if not _may():
        raise PreventUpdate
    user = auth.current_user()
    trig = ctx.triggered_id
    if trig == "ca-rs-create":
        if not label:
            return "Give the new rate set a label."
        try:
            repo.create_rate_set(label.strip(), user["email"] if user else "admin",
                                 copy_from_id=copy_from)
        except Exception as e:
            return f"Could not create: {e}"
        return f"Draft rate set '{label.strip()}' created. Reload the page to select it."
    if trig == "ca-rs-activate":
        if not sel:
            return "Select the rate set to activate."
        repo.activate_rate_set(sel)
        return "Activated. New calculations now snapshot from this set."
    if trig == "ca-mk-set":
        if not (sel and mk_div and mk_reg):
            return "Select a rate set, division and region."
        repo.set_markups(sel, mk_div, mk_reg, levy_local_pct=ll, levy_expat_pct=le,
                         overhead_pct=oh, risk_pct=rk, profit_pct=pf, margin_pct=mg)
        return f"Markups saved for {mk_div} \u00b7 {mk_reg}."
    raise PreventUpdate


@callback(Output("ca-bk-download", "data"),
          Input("ca-bk-db", "n_clicks"), Input("ca-bk-zip", "n_clicks"),
          prevent_initial_call=True)
def _backup(n_db, n_zip):
    if not _may():
        raise PreventUpdate
    trig = ctx.triggered_id
    if trig == "ca-bk-db" and n_db:
        with open(CALC_DB, "rb") as fh:
            data = fh.read()
        return dcc.send_bytes(lambda f: f.write(data), "calc.db")
    if trig == "ca-bk-zip" and n_zip:
        zb = qcalc_io.backup_zip_bytes()
        return dcc.send_bytes(lambda f: f.write(zb), "calc_backup_qcalc.zip")
    raise PreventUpdate
