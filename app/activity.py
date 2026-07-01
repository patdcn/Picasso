"""
Activity log — who signed in, for how long, and which tools they used.

Stored in its own SQLite database (ACTIVITY_DB, default /data/activity.db) so it
can be reviewed or cleared from the Admin area without touching the users DB.

Two tables:
  sessions  one row per login: login time, a rolling "last seen" (updated on every
            page view and by a 60 s heartbeat while a tab is open) and an explicit
            logout time when the user signs out. Session length is measured from
            login to logout, or to last-seen when the tab was simply closed.
  events    one row per page view: which tool (path + name), when, and the session.

Recording is best-effort: callers wrap calls so a logging hiccup never breaks a
page. The Flask session carries a random `activity_sid` that ties a browser
session to its DB row.
"""
import os
import uuid
import sqlite3
import datetime

from flask import session

ACTIVITY_DB = os.getenv("ACTIVITY_DB", "/data/activity.db")


def _now():
    return datetime.datetime.utcnow().isoformat(timespec="seconds")


def _conn():
    parent = os.path.dirname(ACTIVITY_DB)
    if parent:
        os.makedirs(parent, exist_ok=True)
    c = sqlite3.connect(ACTIVITY_DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                sid          TEXT UNIQUE NOT NULL,
                email        TEXT NOT NULL,
                login_at     TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                logout_at    TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                sid   TEXT,
                email TEXT NOT NULL,
                path  TEXT NOT NULL,
                name  TEXT,
                ts    TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS ix_sess_email ON sessions(email)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_sess_login ON sessions(login_at)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_evt_email ON events(email)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_evt_ts ON events(ts)")


# --------------------------------------------------------------------------- #
# Recording (best-effort; callers guard with try/except)
# --------------------------------------------------------------------------- #
def on_login(email):
    """Open a new session row at sign-in and remember its id in the cookie."""
    sid = uuid.uuid4().hex
    now = _now()
    with _conn() as c:
        c.execute("INSERT INTO sessions (sid, email, login_at, last_seen_at) "
                  "VALUES (?,?,?,?)", (sid, email, now, now))
    session["activity_sid"] = sid


def _ensure_sid(email):
    """Return the current session's sid, lazily creating one (e.g. for sessions
    that predate this feature or lost the cookie key)."""
    sid = session.get("activity_sid")
    with _conn() as c:
        if sid and c.execute("SELECT 1 FROM sessions WHERE sid=?", (sid,)).fetchone():
            return sid
        sid = uuid.uuid4().hex
        now = _now()
        c.execute("INSERT INTO sessions (sid, email, login_at, last_seen_at) "
                  "VALUES (?,?,?,?)", (sid, email, now, now))
    session["activity_sid"] = sid
    return sid


def record_page(email, path, name=None):
    if not email or not path:
        return
    sid = _ensure_sid(email)
    now = _now()
    with _conn() as c:
        c.execute("UPDATE sessions SET last_seen_at=? WHERE sid=?", (now, sid))
        c.execute("INSERT INTO events (sid, email, path, name, ts) VALUES (?,?,?,?,?)",
                  (sid, email, path, name, now))


def heartbeat(email):
    if not email:
        return
    sid = _ensure_sid(email)
    with _conn() as c:
        c.execute("UPDATE sessions SET last_seen_at=? WHERE sid=?", (_now(), sid))


def on_logout():
    sid = session.get("activity_sid")
    if sid:
        now = _now()
        with _conn() as c:
            c.execute("UPDATE sessions SET logout_at=?, last_seen_at=? WHERE sid=?",
                      (now, now, sid))
    session.pop("activity_sid", None)


# --------------------------------------------------------------------------- #
# Querying (for the admin review page)
# --------------------------------------------------------------------------- #
def known_emails():
    with _conn() as c:
        return [r["email"] for r in
                c.execute("SELECT DISTINCT email FROM sessions ORDER BY email")]


def known_paths():
    with _conn() as c:
        return [(r["path"], r["name"]) for r in c.execute(
            "SELECT path, MAX(name) AS name FROM events GROUP BY path ORDER BY path")]


def query_sessions(email=None, date_from=None, date_to=None, limit=2000):
    q = ("SELECT s.*, (SELECT COUNT(*) FROM events e WHERE e.sid=s.sid) AS views "
         "FROM sessions s WHERE 1=1")
    args = []
    if email:
        q += " AND s.email=?"; args.append(email)
    if date_from:
        q += " AND s.login_at>=?"; args.append(date_from)
    if date_to:
        q += " AND s.login_at<=?"; args.append(date_to + "T23:59:59")
    q += " ORDER BY s.login_at DESC LIMIT ?"; args.append(limit)
    with _conn() as c:
        rows = c.execute(q, args).fetchall()
    return [dict(r) for r in rows]


def query_events(email=None, path=None, date_from=None, date_to=None, limit=3000):
    q = "SELECT * FROM events WHERE 1=1"
    args = []
    if email:
        q += " AND email=?"; args.append(email)
    if path:
        q += " AND path=?"; args.append(path)
    if date_from:
        q += " AND ts>=?"; args.append(date_from)
    if date_to:
        q += " AND ts<=?"; args.append(date_to + "T23:59:59")
    q += " ORDER BY ts DESC LIMIT ?"; args.append(limit)
    with _conn() as c:
        rows = c.execute(q, args).fetchall()
    return [dict(r) for r in rows]


def clear(before=None):
    """Delete activity. With `before` (YYYY-MM-DD) removes events before that date
    and sessions last seen before it; otherwise wipes everything. Returns count."""
    with _conn() as c:
        if before:
            n = c.execute("DELETE FROM events WHERE ts < ?", (before,)).rowcount
            n += c.execute("DELETE FROM sessions WHERE last_seen_at < ?", (before,)).rowcount
        else:
            n = c.execute("DELETE FROM events").rowcount
            n += c.execute("DELETE FROM sessions").rowcount
    # reclaim file space — VACUUM must run outside a transaction
    try:
        v = sqlite3.connect(ACTIVITY_DB, isolation_level=None)
        v.execute("VACUUM")
        v.close()
    except Exception:
        pass
    return n
