"""
Request access — any signed-in user can ask an administrator for access to tools
they don't yet have. Each request is stored in the database (so admins always see
it under Admin) and, if SMTP is configured, also emailed to the administrators.

This page is reachable by every signed-in user: its path is excluded from the
per-module access gate in app/auth.py.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ALL
from dash.exceptions import PreventUpdate

from app import auth, mailer

dash.register_page(__name__, path="/request-access", name="Request access")  # no category -> not in nav groups

INK = "#1f2937"
MUTED = "#6b7280"
ACCENT = "#0f766e"
GRID = "#e5e7eb"


def _module_rows(user):
    have = set((user.get("modules") if user else []) or [])
    rows = []
    for m in auth.list_modules():
        already = m["path"] in have
        label = f' {m["category"]} \u00b7 {m["name"]}' + ("   (you already have access)" if already else "")
        rows.append(html.Div(
            dcc.Checklist(
                id={"type": "req-app", "path": m["path"]},
                options=[{"label": label, "value": m["path"], "disabled": already}],
                value=[], inputStyle={"marginRight": "8px"},
                style={"color": MUTED if already else INK}),
            style={"padding": "4px 0", "borderBottom": f"1px solid #f1f5f9"}))
    return rows


def layout():
    user = auth.current_user()
    email = user["email"] if user else ""
    return html.Div([
        html.H3("Request access"),
        html.P("Select the tools you'd like access to and submit. An administrator "
               "will be notified and can grant access.",
               style={"color": MUTED, "maxWidth": "640px"}),
        html.Div([
            html.Label("Your email", style={"fontSize": "0.8rem", "fontWeight": 600}),
            dcc.Input(id="req-email", type="email", value=email, placeholder="you@dcndiving.com",
                      style={"width": "100%", "padding": "8px 10px", "borderRadius": "8px",
                             "border": f"1px solid {GRID}", "marginBottom": "14px",
                             "boxSizing": "border-box"}),

            html.Label("Tools", style={"fontSize": "0.8rem", "fontWeight": 600}),
            html.Div(_module_rows(user), style={"margin": "6px 0 14px"}),

            html.Label("Note (optional)", style={"fontSize": "0.8rem", "fontWeight": 600}),
            dcc.Textarea(id="req-note", placeholder="Anything the admin should know (project, reason, deadline)\u2026",
                         style={"width": "100%", "minHeight": "70px", "padding": "8px 10px",
                                "borderRadius": "8px", "border": f"1px solid {GRID}",
                                "marginBottom": "14px", "boxSizing": "border-box",
                                "fontFamily": "inherit"}),

            html.Button("Submit request", id="req-submit", n_clicks=0, style={
                "padding": "9px 16px", "borderRadius": "8px", "border": "none",
                "background": ACCENT, "color": "#fff", "fontWeight": 600, "cursor": "pointer"}),
            html.Div(id="req-status", style={"fontSize": "0.9rem", "marginTop": "12px", "minHeight": "1.2em"}),
        ], style={"background": "#fff", "border": f"1px solid {GRID}", "borderRadius": "12px",
                  "padding": "18px", "maxWidth": "640px"}),
    ], style={"maxWidth": "680px"})


@callback(
    Output("req-status", "children"),
    Output("req-submit", "n_clicks"),
    Input("req-submit", "n_clicks"),
    State("req-email", "value"),
    State({"type": "req-app", "path": ALL}, "value"),
    State("req-note", "value"),
    prevent_initial_call=True,
)
def _submit(_n, email, app_values, note):
    user = auth.current_user()
    if not user:
        raise PreventUpdate
    email = user["email"]  # bind to the signed-in user; ignore any client-supplied value
    requested = [v[0] for v in (app_values or []) if v]
    ok, msg = auth.create_access_request(email, requested, note)
    if not ok:
        return html.Span(msg, style={"color": "#b91c1c"}), no_update

    # Notify admins by email if SMTP is configured (best-effort; the DB record is
    # the source of truth, so the request is never lost if email isn't set up).
    names = {m["path"]: f'{m["category"]} \u00b7 {m["name"]}' for m in auth.list_modules()}
    lines = "\n".join(f"  - {names.get(p, p)}" for p in requested)
    body = (f"{email} has requested access to the following Picasso tools:\n\n{lines}\n"
            + (f"\nNote from requester:\n{note.strip()}\n" if (note or '').strip() else "")
            + "\nReview and grant under Admin \u2192 Manage access.\n")
    mailer.send_email(f"Picasso access request from {email}", body,
                      auth.admin_emails(), reply_to=email)

    return (html.Span("Your request has been submitted. An administrator will review it.",
                      style={"color": ACCENT}), 0)
