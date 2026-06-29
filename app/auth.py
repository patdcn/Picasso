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

AUTH_DB = os.getenv("AUTH_DB", "/data/auth.db")

# Paths the guard always lets through (Dash internals, static assets, the login flow).
PUBLIC_PREFIXES = ("/login", "/logout", "/assets", "/_dash", "/_reload", "/_favicon", "/favicon")


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
    """All tool module keys (page paths), excluding home and admin."""
    return {p["path"] for p in dash.page_registry.values()} - {"/", "/admin"}


def list_modules():
    """Tool modules for the admin checkboxes: [{path, name, category}], sorted."""
    out = []
    for p in dash.page_registry.values():
        if p["path"] in ("/", "/admin"):
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
        if path == "/admin" and not user["is_admin"]:
            return redirect("/")
        if path in module_keys() and not can_access(user, path):
            return redirect("/")
        return None

    @server.route("/login", methods=["GET", "POST"])
    def login():
        nxt = request.args.get("next") or "/"
        if request.method == "POST":
            user = verify_login(request.form.get("email", ""), request.form.get("password", ""))
            if user:
                session["user_email"] = user["email"]
                session.permanent = True
                return redirect(nxt if nxt.startswith("/") else "/")
            return _render_login(error="Invalid email or password.", nxt=nxt if nxt != "/" else None)
        if current_user():
            return redirect("/")
        return _render_login(nxt=nxt if nxt != "/" else None)

    @server.route("/logout")
    def logout():
        session.clear()
        return redirect("/login")
