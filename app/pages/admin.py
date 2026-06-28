"""
Admin — user administration (admins only; gated by the before_request guard).

Two cards: "Add user" and "Manage access". Manage access lets you pick a user, tick
the individual modules they may use (per-module checkboxes), toggle admin, then save
or delete. Module list is built from the page registry, so new tools appear here
automatically.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, no_update

from app import auth

dash.register_page(__name__, path="/admin", name="Admin")  # no category -> not in nav groups

INK = "#1f2937"
MUTED = "#6b7280"
ACCENT = "#0f766e"


def _card(children):
    return html.Div(children, style={
        "background": "#fff", "border": "1px solid #e5e7eb", "borderRadius": "12px",
        "padding": "18px", "marginBottom": "18px", "maxWidth": "640px"})


def _input(id_, ph, type_="text"):
    return dcc.Input(id=id_, type=type_, placeholder=ph, style={
        "width": "100%", "padding": "8px 10px", "borderRadius": "8px",
        "border": "1px solid #d1d5db", "marginBottom": "8px", "boxSizing": "border-box"})


def _user_options():
    return [{"label": u["email"] + ("  (admin)" if u["is_admin"] else ""), "value": u["email"]}
            for u in auth.list_users()]


def _module_options():
    return [{"label": f'{m["category"]} \u00b7 {m["name"]}', "value": m["path"]}
            for m in auth.list_modules()]


def _btn(label, id_, primary=True):
    bg = ACCENT if primary else "#fff"
    fg = "#fff" if primary else "#b91c1c"
    border = "none" if primary else "1px solid #fecaca"
    return html.Button(label, id=id_, n_clicks=0, style={
        "padding": "9px 16px", "borderRadius": "8px", "border": border,
        "background": bg, "color": fg, "fontWeight": 600, "cursor": "pointer",
        "marginRight": "8px"})


def _status(id_):
    return html.Div(id=id_, style={"fontSize": "0.85rem", "marginTop": "10px", "minHeight": "1.1em"})


def layout():
    return html.Div([
        html.H3("User administration"),
        html.P("Add users and grant access to individual tools. Admins can access "
               "everything automatically.", style={"color": MUTED, "maxWidth": "640px"}),

        _card([
            html.H4("Add user", style={"marginTop": 0}),
            _input("adm-new-email", "email address", "email"),
            _input("adm-new-pw", "initial password (share manually)", "text"),
            dcc.Checklist(id="adm-new-admin",
                          options=[{"label": " Administrator (full access)", "value": "admin"}],
                          value=[], style={"margin": "4px 0 12px"}),
            _btn("Create user", "adm-create"),
            _status("adm-create-status"),
        ]),

        _card([
            html.H4("Manage access", style={"marginTop": 0}),
            html.Label("User", style={"fontSize": "0.8rem", "fontWeight": 600}),
            dcc.Dropdown(id="adm-user-dd", options=_user_options(), placeholder="Select a user",
                         style={"marginBottom": "12px"}),
            dcc.Checklist(id="adm-is-admin",
                          options=[{"label": " Administrator (full access)", "value": "admin"}],
                          value=[], style={"marginBottom": "12px"}),
            html.Label("Module access", style={"fontSize": "0.8rem", "fontWeight": 600}),
            dcc.Checklist(id="adm-modules", options=_module_options(), value=[],
                          style={"margin": "6px 0 14px", "display": "flex",
                                 "flexDirection": "column", "gap": "4px"},
                          inputStyle={"marginRight": "8px"}),
            _btn("Save changes", "adm-save"),
            _btn("Delete user", "adm-delete", primary=False),
            _status("adm-user-status"),
        ]),
    ], style={"maxWidth": "680px"})


# --- create user ---
@callback(
    Output("adm-create-status", "children"),
    Output("adm-user-dd", "options"),
    Output("adm-new-email", "value"),
    Output("adm-new-pw", "value"),
    Output("adm-new-admin", "value"),
    Input("adm-create", "n_clicks"),
    State("adm-new-email", "value"),
    State("adm-new-pw", "value"),
    State("adm-new-admin", "value"),
    prevent_initial_call=True,
)
def _create(_n, email, pw, admin):
    ok, msg = auth.create_user(email, pw, is_admin=("admin" in (admin or [])))
    if ok:
        return (html.Span(msg, style={"color": ACCENT}), _user_options(), "", "", [])
    return (html.Span(msg, style={"color": "#b91c1c"}), no_update, no_update, no_update, no_update)


# --- load a user's current access when selected ---
@callback(
    Output("adm-modules", "value"),
    Output("adm-is-admin", "value"),
    Output("adm-user-status", "children"),
    Input("adm-user-dd", "value"),
    prevent_initial_call=True,
)
def _select(email):
    u = auth.get_user(email)
    if not u:
        return [], [], ""
    return (u["modules"], (["admin"] if u["is_admin"] else []), "")


# --- save changes ---
@callback(
    Output("adm-user-status", "children", allow_duplicate=True),
    Input("adm-save", "n_clicks"),
    State("adm-user-dd", "value"),
    State("adm-modules", "value"),
    State("adm-is-admin", "value"),
    prevent_initial_call=True,
)
def _save(_n, email, modules, admin):
    if not email:
        return html.Span("Select a user first.", style={"color": "#b91c1c"})
    ok, msg = auth.update_user(email, is_admin=("admin" in (admin or [])), modules=modules or [])
    return html.Span(msg, style={"color": ACCENT if ok else "#b91c1c"})


# --- delete user ---
@callback(
    Output("adm-user-status", "children", allow_duplicate=True),
    Output("adm-user-dd", "options", allow_duplicate=True),
    Output("adm-user-dd", "value"),
    Output("adm-modules", "value", allow_duplicate=True),
    Output("adm-is-admin", "value", allow_duplicate=True),
    Input("adm-delete", "n_clicks"),
    State("adm-user-dd", "value"),
    prevent_initial_call=True,
)
def _delete(_n, email):
    if not email:
        return (html.Span("Select a user first.", style={"color": "#b91c1c"}),
                no_update, no_update, no_update, no_update)
    ok, msg = auth.delete_user(email)
    if ok:
        return (html.Span(msg, style={"color": ACCENT}), _user_options(), None, [], [])
    return (html.Span(msg, style={"color": "#b91c1c"}), no_update, no_update, no_update, no_update)
