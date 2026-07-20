"""
Authentication & per-module access control.

- Users live in a SQLite database on the persistent volume (/data/auth.db by default).
- Passwords are stored only as werkzeug hashes, never plain text.
- A bootstrap admin is created on first run from ADMIN_EMAIL / ADMIN_PASSWORD env vars.
- register_auth(server) installs a before_request guard plus /login and /logout routes.

Access model: each tool page's URL path is its "module key". A user's record holds
the list of module keys they may access. Admins implicitly access everything.

Cookie security is controlled by the COOKIE_SECURE env var (set "true" once HTTPS is
live); kept "false" by default so login works before the certificate is issued.
"""
import os
import json
import sqlite3
import datetime

import dash
from flask import session, request, redirect, render_template_string
from werkzeug.security import generate_password_hash, check_password_hash

from app import activity

AUTH_DB = os.getenv("AUTH_DB", "/data/auth.db")

# Paths the guard always lets through: the login flow, static assets, and the
# framework's static JS bundles. NOTE: this intentionally does NOT include the
# blanket "/_dash" prefix. The Dash callback endpoint (/_dash-update-component)
# and the layout/dependency endpoints (/_dash-layout, /_dash-dependencies) all
# live under /_dash and MUST require a signed-in session — otherwise anyone can
# invoke callbacks (create users, edit parameters, delete data) without logging
# in. Only the static component-suite bundles are safe to serve publicly.
PUBLIC_PREFIXES = ("/login", "/logout", "/assets",
                   "/_dash-component-suites", "/_reload", "/_favicon", "/favicon")

# Login throttling (per-email rolling window). Configurable via env.
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "8"))
LOGIN_WINDOW_SEC = int(os.getenv("LOGIN_WINDOW_SEC", "900"))


# --------------------------------------------------------------------------- #
# DB helpers
# --------------------------------------------------------------------------- #
def _now():
    return datetime.datetime.utcnow().isoformat(timespec="seconds")


def _conn():
    parent = os.path.dirname(AUTH_DB)
    if parent:
        os.makedirs(parent, exist_ok=True)
    c = sqlite3.connect(AUTH_DB)
    c.row_factory = sqlite3.Row
    return c


def _row_to_user(row):
    if row is None:
        return None
    keys = row.keys()
    return {
        "id": row["id"],
        "email": row["email"],
        "is_admin": bool(row["is_admin"]),
        "modules": json.loads(row["modules"] or "[]"),
        "param_modules": json.loads(row["param_modules"]) if "param_modules" in keys and row["param_modules"] else [],
        "created_at": row["created_at"],
    }


def init_db():
    """Create the table if missing and ensure a bootstrap admin exists."""
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin      INTEGER NOT NULL DEFAULT 0,
                modules       TEXT NOT NULL DEFAULT '[]',
                created_at    TEXT NOT NULL
            )
        """)
        # migrations: add permission columns to pre-existing databases.
        cols = {r["name"] for r in c.execute("PRAGMA table_info(users)").fetchall()}
        if "can_edit_params" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN can_edit_params INTEGER NOT NULL DEFAULT 0")
        if "param_modules" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN param_modules TEXT NOT NULL DEFAULT '[]'")

        # access requests raised by signed-in users wanting more module access.
        c.execute("""
            CREATE TABLE IF NOT EXISTS access_requests (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                email      TEXT NOT NULL,
                modules    TEXT NOT NULL,
                note       TEXT,
                status     TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
        """)

        # failed-login timestamps, used to throttle password brute-forcing.
        c.execute("""
            CREATE TABLE IF NOT EXISTS login_failures (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                ts    TEXT NOT NULL
            )
        """)

    email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    pw = os.getenv("ADMIN_PASSWORD") or ""
    if not (email and pw):
        return

    with _conn() as c:
        n_admins = c.execute("SELECT COUNT(*) AS n FROM users WHERE is_admin=1").fetchone()["n"]
        if n_admins > 0:
            return  # an admin already exists; don't touch anything
        existing = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            c.execute("UPDATE users SET is_admin=1 WHERE email=?", (email,))
        else:
            c.execute(
                "INSERT INTO users (email, password_hash, is_admin, modules, created_at) "
                "VALUES (?,?,?,?,?)",
                (email, generate_password_hash(pw), 1, "[]", _now()),
            )


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
def list_users():
    with _conn() as c:
        rows = c.execute("SELECT * FROM users ORDER BY email").fetchall()
    return [_row_to_user(r) for r in rows]


def get_user(email):
    if not email:
        return None
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
    return _row_to_user(row)


def count_admins():
    with _conn() as c:
        return c.execute("SELECT COUNT(*) AS n FROM users WHERE is_admin=1").fetchone()["n"]


def create_user(email, password, is_admin=False, modules=None, param_modules=None):
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False, "Enter a valid email address."
    if not password or len(password) < 6:
        return False, "Password must be at least 6 characters."
    if get_user(email):
        return False, f"A user with email {email} already exists."
    with _conn() as c:
        c.execute(
            "INSERT INTO users (email, password_hash, is_admin, modules, param_modules, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (email, generate_password_hash(password), 1 if is_admin else 0,
             json.dumps(modules or []), json.dumps(param_modules or []), _now()),
        )
    return True, f"Created user {email}."


def update_user(email, is_admin, modules, param_modules=None):
    email = (email or "").strip().lower()
    u = get_user(email)
    if not u:
        return False, "User not found."
    # don't allow removing the last admin
    if u["is_admin"] and not is_admin and count_admins() <= 1:
        return False, "Can't remove admin rights from the only administrator."
    with _conn() as c:
        c.execute("UPDATE users SET is_admin=?, modules=?, param_modules=? WHERE email=?",
                  (1 if is_admin else 0, json.dumps(modules or []),
                   json.dumps(param_modules or []), email))
    return True, f"Saved changes to {email}."


def delete_user(email):
    email = (email or "").strip().lower()
    u = get_user(email)
    if not u:
        return False, "User not found."
    if u["is_admin"] and count_admins() <= 1:
        return False, "Can't delete the only administrator."
    with _conn() as c:
        c.execute("DELETE FROM users WHERE email=?", (email,))
    return True, f"Deleted user {email}."


def verify_login(email, password):
    u_row = None
    with _conn() as c:
        u_row = c.execute("SELECT * FROM users WHERE email=?",
                          ((email or "").strip().lower(),)).fetchone()
    if u_row and check_password_hash(u_row["password_hash"], password or ""):
        return _row_to_user(u_row)
    return None


# --------------------------------------------------------------------------- #
# Access checks
# --------------------------------------------------------------------------- #
def module_keys():
    """All tool module keys (page paths), excluding home, admin pages, and the
    request-access page (which every signed-in user may reach)."""
    return {p["path"] for p in dash.page_registry.values()
            if not p["path"].startswith("/admin")
            and p["path"] not in ("/", "/request-access")}


def list_modules():
    """Tool modules for the admin checkboxes: [{path, name, category}], sorted."""
    out = []
    for p in dash.page_registry.values():
        if p["path"].startswith("/admin") or p["path"] in ("/", "/request-access"):
            continue
        out.append({"path": p["path"], "name": p["name"], "category": p.get("category") or "Other"})
    out.sort(key=lambda m: (m["category"], m["name"]))
    return out


def can_access(user, module_key):
    if not user:
        return False
    if user.get("is_admin"):
        return True
    return module_key in (user.get("modules") or [])


def may_edit_params(user, module_key):
    """Whether a user may edit the parameters on a specific tool page. Admins
    always may; others need that page in their param_modules grant."""
    if not user:
        return False
    if user.get("is_admin"):
        return True
    return module_key in (user.get("param_modules") or [])


def current_user():
    return get_user(session.get("user_email"))


def is_admin_request():
    """True only if the *current request* carries a valid, signed-in admin session.

    Call this at the top of every admin-only callback. The before_request guard
    protects page navigation, but Dash callbacks POST to /_dash-update-component
    and are therefore NOT covered by the page-level admin/module checks — each
    state-changing or data-disclosing admin callback must re-verify here itself.
    """
    u = current_user()
    return bool(u and u.get("is_admin"))


# --------------------------------------------------------------------------- #
# Login throttling
# --------------------------------------------------------------------------- #
def _prune_login_failures(c):
    cutoff = (datetime.datetime.utcnow()
              - datetime.timedelta(seconds=LOGIN_WINDOW_SEC)).isoformat(timespec="seconds")
    c.execute("DELETE FROM login_failures WHERE ts < ?", (cutoff,))


def record_login_failure(email):
    email = (email or "").strip().lower()
    if not email:
        return
    with _conn() as c:
        _prune_login_failures(c)
        c.execute("INSERT INTO login_failures (email, ts) VALUES (?,?)", (email, _now()))


def clear_login_failures(email):
    email = (email or "").strip().lower()
    if not email:
        return
    with _conn() as c:
        c.execute("DELETE FROM login_failures WHERE email=?", (email,))


def login_locked(email):
    """(locked, seconds_remaining) for this email, based on recent failures in
    the rolling window. Shared across gunicorn workers via the database."""
    email = (email or "").strip().lower()
    if not email:
        return False, 0
    with _conn() as c:
        _prune_login_failures(c)
        rows = c.execute("SELECT ts FROM login_failures WHERE email=? ORDER BY ts",
                         (email,)).fetchall()
    if len(rows) < LOGIN_MAX_FAILURES:
        return False, 0
    try:
        oldest = datetime.datetime.fromisoformat(rows[0]["ts"])
    except Exception:
        return True, LOGIN_WINDOW_SEC
    remaining = LOGIN_WINDOW_SEC - (datetime.datetime.utcnow() - oldest).total_seconds()
    if remaining <= 0:
        return False, 0
    return True, int(remaining)


# --------------------------------------------------------------------------- #
# Access requests + admin notification recipients
# --------------------------------------------------------------------------- #
def admin_emails():
    """Email addresses of all administrators (recipients for access requests).
    Falls back to the ADMIN_EMAIL env var if, somehow, no admin exists."""
    emails = [u["email"] for u in list_users() if u["is_admin"]]
    if not emails:
        env = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
        if env:
            emails = [env]
    return emails


def create_access_request(email, modules, note=None):
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False, "Enter a valid email address."
    modules = [m for m in (modules or []) if m]
    if not modules:
        return False, "Select at least one tool to request."
    with _conn() as c:
        c.execute(
            "INSERT INTO access_requests (email, modules, note, status, created_at) "
            "VALUES (?,?,?,?,?)",
            (email, json.dumps(modules), (note or "").strip() or None, "pending", _now()),
        )
    return True, "Request submitted."


def list_access_requests(status="pending"):
    with _conn() as c:
        if status:
            rows = c.execute("SELECT * FROM access_requests WHERE status=? ORDER BY created_at DESC",
                             (status,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM access_requests ORDER BY created_at DESC").fetchall()
    return [{"id": r["id"], "email": r["email"], "modules": json.loads(r["modules"] or "[]"),
             "note": r["note"], "status": r["status"], "created_at": r["created_at"]} for r in rows]


def count_pending_requests():
    with _conn() as c:
        return c.execute("SELECT COUNT(*) AS n FROM access_requests WHERE status='pending'").fetchone()["n"]


def mark_request_handled(req_id):
    with _conn() as c:
        c.execute("UPDATE access_requests SET status='handled' WHERE id=?", (int(req_id),))
    return True


# --------------------------------------------------------------------------- #
# Routes + guard
# --------------------------------------------------------------------------- #
_LOGIN_HTML = """
<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in - DSV Picasso Portal</title>
<style>
 body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
      background:#f3f4f6;display:flex;min-height:100vh;align-items:center;justify-content:center;color:#1f2937}
 .card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:28px;width:320px;
       box-shadow:0 4px 16px rgba(0,0,0,.06)}
 h1{font-size:1.15rem;margin:0 0 2px} .sub{color:#6b7280;font-size:.85rem;margin-bottom:18px}
 label{display:block;font-size:.8rem;font-weight:600;margin:10px 0 4px}
 input{width:100%;padding:9px 10px;border:1px solid #d1d5db;border-radius:8px;box-sizing:border-box}
 button{width:100%;margin-top:16px;padding:10px;border:none;border-radius:8px;background:#0f766e;
        color:#fff;font-weight:600;cursor:pointer}
 button:hover{background:#0d655e}
 .err{background:#fef2f2;border:1px solid #fecaca;color:#b91c1c;font-size:.82rem;
      padding:8px 10px;border-radius:8px;margin-top:14px}
</style></head><body>
 <form class="card" method="post" action="/login{{ nextq }}">
   <h1>DSV Picasso Portal</h1>
   <div class="sub">DCN Diving - sign in to continue</div>
   <label>Email</label>
   <input type="email" name="email" autocomplete="username" autofocus>
   <label>Password</label>
   <input type="password" name="password" autocomplete="current-password">
   <button type="submit">Sign in</button>
   {% if error %}<div class="err">{{ error }}</div>{% endif %}
 </form>
</body></html>
"""


def _render_login(error=None, nxt=None):
    nextq = f"?next={nxt}" if nxt else ""
    return render_template_string(_LOGIN_HTML, error=error, nextq=nextq)


def register_auth(server):
    @server.before_request
    def _guard():
        p = request.path
        if any(p.startswith(pre) for pre in PUBLIC_PREFIXES):
            return None
        user = current_user()
        if not user:
            return redirect("/login?next=" + p)
        path = p.rstrip("/") or "/"
        if path.startswith("/admin") and not user["is_admin"]:
            return redirect("/")
        if path in module_keys() and not can_access(user, path):
            return redirect("/")
        return None

    @server.route("/login", methods=["GET", "POST"])
    def login():
        nxt = request.args.get("next") or "/"
        if request.method == "POST":
            email = request.form.get("email", "")
            locked, wait = login_locked(email)
            if locked:
                mins = max(1, (wait + 59) // 60)
                return _render_login(
                    error=f"Too many failed attempts. Try again in about {mins} minute(s).",
                    nxt=nxt if nxt != "/" else None)
            user = verify_login(email, request.form.get("password", ""))
            if user:
                clear_login_failures(email)
                session["user_email"] = user["email"]
                session.permanent = True
                try:
                    activity.on_login(user["email"])
                except Exception:
                    pass
                return redirect(nxt if nxt.startswith("/") else "/")
            record_login_failure(email)
            return _render_login(error="Invalid email or password.", nxt=nxt if nxt != "/" else None)
        if current_user():
            return redirect("/")
        return _render_login(nxt=nxt if nxt != "/" else None)

    @server.route("/logout")
    def logout():
        try:
            activity.on_logout()
        except Exception:
            pass
        session.clear()
        return redirect("/login")
