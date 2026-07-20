"""
DCN Diving Engineering Portal — application entrypoint.

Portal shell: persistent header + collapsible grouped sidebar + page content area.
Tools live in app/pages/ and self-register (Dash Pages). The sidebar is generated
from the page registry, grouped per app/nav.py, and filtered by the logged-in user's
module permissions. Authentication and per-module access live in app/auth.py.
"""
import os
import dash
from dash import Dash, html, dcc, Input, Output, State

app = Dash(__name__, use_pages=True, title="DCN Diving Engineering Portal",
           suppress_callback_exceptions=True)
server = app.server  # gunicorn target

# ---- reverse-proxy trust (opt-in) ----
# Set TRUST_PROXY=true once the app is served ONLY through Dokploy's Traefik
# proxy, so request.remote_addr / request.is_secure reflect the real client and
# original scheme (via X-Forwarded-*). Leave it false while the container port
# is reachable directly, or clients could spoof those headers.
if os.getenv("TRUST_PROXY", "false").lower() == "true":
    from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: E402
    server.wsgi_app = ProxyFix(server.wsgi_app, x_for=1, x_proto=1, x_host=1)

# ---- session / cookie security ----
# No insecure fallback: fail closed rather than run with a publicly-known key
# (which would let anyone forge a signed admin session cookie). Ensure SECRET_KEY
# is set in the deployment environment before deploying.
_secret_key = os.getenv("SECRET_KEY")
if not _secret_key:
    raise RuntimeError(
        "SECRET_KEY is not set. Refusing to start with an insecure default. "
        "Set a long random SECRET_KEY in the deployment environment (Dokploy)."
    )
server.secret_key = _secret_key
server.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Flip COOKIE_SECURE=true once HTTPS (the Let's Encrypt cert) is live.
    SESSION_COOKIE_SECURE=(os.getenv("COOKIE_SECURE", "false").lower() == "true"),
)

# ---- auth: create DB + bootstrap admin, then install guard + login/logout ----
from app import auth  # noqa: E402
auth.init_db()
auth.register_auth(server)

from app import params  # noqa: E402
params.init_db()

from app import activity  # noqa: E402
activity.init_db()

from app import dp_consumers  # noqa: E402
dp_consumers.init_db()

from app import sat_system  # noqa: E402
sat_system.init_db()

from app.nav import build_nav  # noqa: E402

# ---- serve GA reference files from the data volume (read-only, safe filenames) ----
import os as _os
from flask import send_from_directory, abort  # noqa: E402

_GA_DIR = _os.getenv("GA_DATA_DIR", "/data/docs/crane")


@server.route("/ga-file/<path:name>")
def _ga_file(name):
    # require a signed-in user with access to the GA reference page (admins pass).
    user = auth.current_user()
    if not user or not auth.can_access(user, "/reference/ga"):
        abort(403)
    # only allow simple filenames within the GA dir
    if "/" in name or "\\" in name or ".." in name:
        abort(404)
    if not _os.path.isdir(_GA_DIR) or not _os.path.exists(_os.path.join(_GA_DIR, name)):
        abort(404)
    return send_from_directory(_GA_DIR, name)


# ---- serve Picasso DP reference documents from the data volume ----
_DP_DOCS_DIR = _os.getenv("DP_DOCS_DIR", "/data/docs/dp")


@server.route("/dp-doc/<path:name>")
def _dp_doc(name):
    # require a signed-in user with access to the Picasso DP reference page (admins pass).
    user = auth.current_user()
    if not user or not auth.can_access(user, "/reference/picasso-dp"):
        abort(403)
    if "/" in name or "\\" in name or ".." in name:
        abort(404)
    if (not _os.path.isdir(_DP_DOCS_DIR)
            or not _os.path.exists(_os.path.join(_DP_DOCS_DIR, name))):
        abort(404)
    return send_from_directory(_DP_DOCS_DIR, name)

# ---- Header (toggle + title + user area) ----
header = html.Header(
    [
        html.Button("\u2630", id="nav-toggle", className="nav-toggle", n_clicks=0,
                    title="Show/hide menu"),
        html.H2("DCN Diving Engineering Portal", className="app-title"),
        html.Div(id="user-area", className="user-area"),
    ],
    className="app-header",
)

# ---- Shell: sidebar + content ----
app.layout = html.Div(
    [
        dcc.Location(id="url"),
        dcc.Store(id="nav-open", data=True),
        dcc.Interval(id="activity-hb", interval=60_000, n_intervals=0),
        html.Div(id="activity-sink", style={"display": "none"}),
        html.Div(id="activity-hb-sink", style={"display": "none"}),
        header,
        html.Div(
            [
                html.Nav(id="sidebar", className="sidebar"),
                html.Main(dash.page_container, className="content"),
            ],
            id="app-shell",
            className="app-shell",
        ),
    ]
)


@app.callback(Output("sidebar", "children"), Input("url", "pathname"))
def _render_nav(pathname):
    return build_nav(pathname, auth.current_user())


@app.callback(Output("user-area", "children"), Input("url", "pathname"))
def _render_user_area(_pathname):
    user = auth.current_user()
    if not user:
        return ""
    children = [html.Span(user["email"], className="user-email")]
    if user["is_admin"]:
        children.append(dcc.Link("Admin", href="/admin", className="user-link"))
        children.append(dcc.Link("Activity", href="/admin/activity", className="user-link"))
    children.append(html.A("Sign out", href="/logout", className="user-link"))
    return children


def _page_name(pathname):
    for p in dash.page_registry.values():
        if p["path"] == pathname:
            return p["name"]
    return "Home" if pathname == "/" else pathname


@app.callback(Output("activity-sink", "children"), Input("url", "pathname"))
def _log_pageview(pathname):
    try:
        user = auth.current_user()
        if user and pathname:
            activity.record_page(user["email"], pathname, _page_name(pathname))
    except Exception:
        pass
    return ""


@app.callback(Output("activity-hb-sink", "children"), Input("activity-hb", "n_intervals"))
def _log_heartbeat(_n):
    try:
        user = auth.current_user()
        if user:
            activity.heartbeat(user["email"])
    except Exception:
        pass
    return ""


@app.callback(
    Output("app-shell", "className"),
    Output("nav-open", "data"),
    Input("nav-toggle", "n_clicks"),
    State("nav-open", "data"),
    prevent_initial_call=True,
)
def _toggle_nav(_clicks, is_open):
    is_open = not is_open
    return ("app-shell" if is_open else "app-shell collapsed"), is_open


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8050")), debug=True)
