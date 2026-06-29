"""
Admin — user administration (admins only; gated by the before_request guard).

Two cards: "Add user" and "Manage access". Manage access lets you pick a user, tick
the individual modules they may use (per-module checkboxes), toggle admin, then save
or delete. Module list is built from the page registry, so new tools appear here
automatically.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ALL

from app import auth
from app import params

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


def _module_rows(allowed, param_allowed):
    """One row per tool module: an access checkbox, plus an 'edit parameters'
    checkbox for modules that expose editable parameters. Built from the page
    registry + params registry, so new tools/params appear here automatically."""
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


def _param_field(p, value):
    return html.Div([
        html.Label(p["label"] + (f"  [{p['unit']}]" if p["unit"] else ""),
                   style={"fontSize": "0.8rem", "fontWeight": 600, "color": INK}),
        dcc.Input(id={"type": "param-input", "key": p["key"]}, type="number",
                  value=value, step=p["step"], debounce=True, style={
                      "width": "100%", "padding": "8px 10px", "borderRadius": "8px",
                      "border": "1px solid #d1d5db", "marginBottom": "4px",
                      "boxSizing": "border-box", "fontFamily": "ui-monospace,monospace"}),
    ], style={"marginBottom": "8px"})


def _params_card():
    """Editable cost & timing assumptions, grouped by category. Built from the
    params registry so new parameters appear here automatically."""
    current = params.get_all()
    sections = []
    last_cat = None
    for p in params.definitions():
        if p["category"] != last_cat:
            sections.append(html.Div(p["category"], style={
                "fontWeight": 700, "fontSize": "0.85rem", "color": MUTED,
                "margin": "10px 0 6px", "textTransform": "uppercase",
                "letterSpacing": "0.03em"}))
            last_cat = p["category"]
        sections.append(_param_field(p, current[p["key"]]))
    return _card([
        html.H4("Cost & timing assumptions", style={"marginTop": 0}),
        html.P("These values are used by the Single-vs-twin-bell and "
               "Single-vs-single-twin tools. Edit and save; both pages pick up "
               "the new values on their next load.",
               style={"color": MUTED, "fontSize": "0.85rem", "marginTop": 0}),
        *sections,
        html.Div(style={"height": "6px"}),
        _btn("Save assumptions", "adm-param-save"),
        _status("adm-param-status"),
    ])


def layout():
    return html.Div([
        html.H3("Administration"),
        html.P("Add users and grant access to individual tools, and set the shared "
               "cost & timing assumptions. Admins can access everything automatically.",
               style={"color": MUTED, "maxWidth": "640px"}),

        _params_card(),
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
            html.Div("Tick to grant access. Where a tool has editable parameters, tick "
                     "\u201cedit parameters\u201d to let that user change them on that page.",
                     style={"fontSize": "0.74rem", "color": MUTED, "margin": "2px 0 8px"}),
            html.Div(id="adm-module-rows", children=_module_rows([], []),
                     style={"margin": "6px 0 14px"}),
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
    Output("adm-module-rows", "children"),
    Output("adm-is-admin", "value"),
    Output("adm-user-status", "children"),
    Input("adm-user-dd", "value"),
    prevent_initial_call=True,
)
def _select(email):
    u = auth.get_user(email)
    if not u:
        return _module_rows([], []), [], ""
    return (_module_rows(u["modules"], u["param_modules"]),
            (["admin"] if u["is_admin"] else []), "")


# --- save changes ---
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
    if not email:
        return html.Span("Select a user first.", style={"color": "#b91c1c"})
    modules = [v[0] for v in (acc_values or []) if v]
    param_modules = [v[0] for v in (par_values or []) if v]
    ok, msg = auth.update_user(email, is_admin=("admin" in (admin or [])),
                               modules=modules, param_modules=param_modules)
    return html.Span(msg, style={"color": ACCENT if ok else "#b91c1c"})


# --- delete user ---
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
    if not email:
        return (html.Span("Select a user first.", style={"color": "#b91c1c"}),
                no_update, no_update, no_update, no_update)
    ok, msg = auth.delete_user(email)
    if ok:
        return (html.Span(msg, style={"color": ACCENT}), _user_options(), None,
                _module_rows([], []), [])
    return (html.Span(msg, style={"color": "#b91c1c"}), no_update, no_update, no_update, no_update)


# --- save cost & timing assumptions ---
@callback(
    Output("adm-param-status", "children"),
    Input("adm-param-save", "n_clicks"),
    State({"type": "param-input", "key": ALL}, "value"),
    State({"type": "param-input", "key": ALL}, "id"),
    prevent_initial_call=True,
)
def _save_params(_n, values, ids):
    mapping = {i["key"]: v for i, v in zip(ids or [], values or [])}
    n, msg = params.set_many(mapping)
    return html.Span(msg, style={"color": ACCENT if n else "#b91c1c"})
