"""
Admin - Users & access (admins only; guarded by /admin).

Add users, grant access to individual tool modules (and, where a tool exposes
editable parameters, the right to edit them), toggle administrator, and review
pending tool-access requests. The module list is built from the page registry,
so new tools appear here automatically.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ALL
from dash.exceptions import PreventUpdate

from app import auth
from app import params
from app.adminui import (card, input_field, btn, status, back_link,
                         is_admin, denied, INK, MUTED, ACCENT)

dash.register_page(__name__, path="/admin/users", name="Users & access")


def _user_options():
    return [{"label": u["email"] + ("  (admin)" if u["is_admin"] else ""), "value": u["email"]}
            for u in auth.list_users()]


def _module_rows(allowed, param_allowed):
    pmods = set(params.param_edit_modules())
    allowed = set(allowed or [])
    param_allowed = set(param_allowed or [])
    rows = []
    for m in auth.list_modules():
        path = m["path"]
        access = dcc.Checklist(
            id={"type": "adm-acc", "path": path},
            options=[{"label": f' {m["category"]} \u00b7 {m["name"]}', "value": path}],
            value=[path] if path in allowed else [],
            inputStyle={"marginRight": "8px"})
        right = None
        if path in pmods:
            right = dcc.Checklist(
                id={"type": "adm-par", "path": path},
                options=[{"label": " edit parameters", "value": path}],
                value=[path] if path in param_allowed else [],
                inputStyle={"marginRight": "6px"},
                style={"fontSize": "0.82rem", "color": ACCENT, "whiteSpace": "nowrap"})
        rows.append(html.Div(
            [html.Div(access, style={"flex": "1 1 auto"}),
             html.Div(right, style={"flex": "0 0 auto"}) if right is not None else None],
            style={"display": "flex", "alignItems": "center", "gap": "10px",
                   "padding": "4px 0", "borderBottom": "1px solid #f1f5f9"}))
    return rows


def _requests_list():
    reqs = auth.list_access_requests("pending")
    if not reqs:
        return [html.Div("No pending requests.", style={"color": MUTED, "fontSize": "0.88rem"})]
    names = {m["path"]: f'{m["category"]} \u00b7 {m["name"]}' for m in auth.list_modules()}
    rows = []
    for r in reqs:
        mods = ", ".join(names.get(p, p) for p in r["modules"])
        rows.append(html.Div([
            html.Div([
                html.Span(r["email"], style={"fontWeight": 700}),
                html.Span(f"   {r['created_at']}Z", style={"color": MUTED, "fontSize": "0.76rem"}),
            ]),
            html.Div(mods, style={"fontSize": "0.85rem", "margin": "3px 0"}),
            html.Div("\u201c" + r["note"] + "\u201d",
                     style={"fontSize": "0.8rem", "color": MUTED, "fontStyle": "italic"}) if r["note"] else None,
            html.Button("Mark handled", id={"type": "req-dismiss", "id": r["id"]}, n_clicks=0, style={
                "marginTop": "6px", "padding": "5px 12px", "borderRadius": "7px",
                "border": "1px solid #e5e7eb", "background": "#fff", "color": ACCENT,
                "fontWeight": 600, "cursor": "pointer", "fontSize": "0.8rem"}),
        ], style={"padding": "10px 0", "borderBottom": "1px solid #f1f5f9"}))
    return rows


def layout():
    if not is_admin():
        return denied()
    n = auth.count_pending_requests()
    return html.Div([
        back_link(),
        html.H3("Users & access"),
        html.P("Add users, grant access to individual tools, and handle access requests. "
               "Admins can access everything automatically.",
               style={"color": MUTED, "maxWidth": "640px"}),

        card([
            html.H4("Pending access requests" + (f"  ({n})" if n else ""), style={"marginTop": 0}),
            html.P("Tool-access requests from users. Grant them under \u201cManage access\u201d "
                   "below, then mark the request handled.",
                   style={"color": MUTED, "fontSize": "0.85rem", "marginTop": 0}),
            html.Div(id="adm-requests-list", children=_requests_list()),
        ]),

        card([
            html.H4("Add user", style={"marginTop": 0}),
            input_field("adm-new-email", "email address", "email"),
            input_field("adm-new-pw", "initial password (share manually)", "text"),
            dcc.Checklist(id="adm-new-admin",
                          options=[{"label": " Administrator (full access)", "value": "admin"}],
                          value=[], style={"margin": "4px 0 12px"}),
            btn("Create user", "adm-create"),
            status("adm-create-status"),
        ]),

        card([
            html.H4("Manage access", style={"marginTop": 0}),
            html.Label("User", style={"fontSize": "0.8rem", "fontWeight": 600}),
            dcc.Dropdown(id="adm-user-dd", options=_user_options(), placeholder="Select a user",
                         style={"marginBottom": "12px"}),
            dcc.Checklist(id="adm-is-admin",
                          options=[{"label": " Administrator (full access)", "value": "admin"}],
                          value=[], style={"marginBottom": "12px"}),
            html.Label("Module access", style={"fontSize": "0.8rem", "fontWeight": 600}),
            html.Div("Tick to grant access. Where a tool has editable parameters, tick "
                     "\u201cedit parameters\u201d to let that user change them on that page.",
                     style={"fontSize": "0.74rem", "color": MUTED, "margin": "2px 0 8px"}),
            html.Div(id="adm-module-rows", children=_module_rows([], []),
                     style={"margin": "6px 0 14px"}),
            btn("Save changes", "adm-save"),
            btn("Delete user", "adm-delete", primary=False),
            status("adm-user-status"),
        ]),

        card([
            html.H4("Reset password", style={"marginTop": 0}),
            html.P("Set a new password for the user selected above, then share it "
                   "with them manually. This is the only way to change a password "
                   "\u2014 the ADMIN_PASSWORD environment variable only seeds the very "
                   "first admin and is ignored afterwards.",
                   style={"color": MUTED, "fontSize": "0.85rem", "marginTop": 0}),
            input_field("adm-reset-pw", "new password (min 6 characters)", "text"),
            btn("Reset password", "adm-reset"),
            status("adm-reset-status"),
        ]),
    ], style={"maxWidth": "680px"})


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
    if not is_admin():
        raise PreventUpdate
    ok, msg = auth.create_user(email, pw, is_admin=("admin" in (admin or [])))
    if ok:
        return (html.Span(msg, style={"color": ACCENT}), _user_options(), "", "", [])
    return (html.Span(msg, style={"color": "#b91c1c"}), no_update, no_update, no_update, no_update)


@callback(
    Output("adm-module-rows", "children"),
    Output("adm-is-admin", "value"),
    Output("adm-user-status", "children"),
    Input("adm-user-dd", "value"),
    prevent_initial_call=True,
)
def _select(email):
    if not is_admin():
        raise PreventUpdate
    u = auth.get_user(email)
    if not u:
        return _module_rows([], []), [], ""
    return (_module_rows(u["modules"], u["param_modules"]),
            (["admin"] if u["is_admin"] else []), "")


@callback(
    Output("adm-user-status", "children", allow_duplicate=True),
    Input("adm-save", "n_clicks"),
    State("adm-user-dd", "value"),
    State({"type": "adm-acc", "path": ALL}, "value"),
    State({"type": "adm-par", "path": ALL}, "value"),
    State("adm-is-admin", "value"),
    prevent_initial_call=True,
)
def _save(_n, email, acc_values, par_values, admin):
    if not is_admin():
        raise PreventUpdate
    if not email:
        return html.Span("Select a user first.", style={"color": "#b91c1c"})
    modules = [v[0] for v in (acc_values or []) if v]
    param_modules = [v[0] for v in (par_values or []) if v]
    ok, msg = auth.update_user(email, is_admin=("admin" in (admin or [])),
                               modules=modules, param_modules=param_modules)
    return html.Span(msg, style={"color": ACCENT if ok else "#b91c1c"})


@callback(
    Output("adm-reset-status", "children"),
    Output("adm-reset-pw", "value"),
    Input("adm-reset", "n_clicks"),
    State("adm-user-dd", "value"),
    State("adm-reset-pw", "value"),
    prevent_initial_call=True,
)
def _reset_pw(_n, email, new_pw):
    if not is_admin():
        raise PreventUpdate
    if not email:
        return html.Span("Select a user above first.", style={"color": "#b91c1c"}), no_update
    ok, msg = auth.set_password(email, new_pw)
    if ok:
        # a fresh password should also lift any brute-force lockout on that account
        auth.clear_login_failures(email)
        return html.Span(msg, style={"color": ACCENT}), ""
    return html.Span(msg, style={"color": "#b91c1c"}), no_update


@callback(
    Output("adm-user-status", "children", allow_duplicate=True),
    Output("adm-user-dd", "options", allow_duplicate=True),
    Output("adm-user-dd", "value"),
    Output("adm-module-rows", "children", allow_duplicate=True),
    Output("adm-is-admin", "value", allow_duplicate=True),
    Input("adm-delete", "n_clicks"),
    State("adm-user-dd", "value"),
    prevent_initial_call=True,
)
def _delete(_n, email):
    if not is_admin():
        raise PreventUpdate
    if not email:
        return (html.Span("Select a user first.", style={"color": "#b91c1c"}),
                no_update, no_update, no_update, no_update)
    ok, msg = auth.delete_user(email)
    if ok:
        return (html.Span(msg, style={"color": ACCENT}), _user_options(), None,
                _module_rows([], []), [])
    return (html.Span(msg, style={"color": "#b91c1c"}), no_update, no_update, no_update, no_update)


@callback(
    Output("adm-requests-list", "children"),
    Input({"type": "req-dismiss", "id": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _dismiss_request(clicks):
    if not is_admin():
        raise PreventUpdate
    trig = dash.callback_context.triggered_id
    if not trig or not any(c for c in (clicks or []) if c):
        return no_update
    auth.mark_request_handled(trig["id"])
    return _requests_list()
