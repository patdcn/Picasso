"""
Shared persistence root for the portal's small config stores.

Historically each concern declared its own "/data/<name>.db" literal (auth.db,
parameter.db, activity.db) and volume.py kept its own DATA_ROOT. The convention
was consistent (a per-concern SQLite database on the /data volume, each with an
env override) but the *location* of the volume root was redeclared in every
module. This module gives a single source of truth for that root, plus a tiny
SQLite-backed JSON document store, so new structured config (e.g. the SAT system
definitions) reuses one mechanism instead of scattering another path literal.

- DATA_ROOT resolves once here (env DATA_ROOT, default /data).
- data_path(name) builds a path under it.
- JSONStore persists id -> JSON document with WAL journalling, so one gunicorn
  worker can read while another writes (same reason params.py uses WAL).

The existing auth/parameter/activity databases keep their own module-level paths
and are untouched; they can migrate to data_path() later if desired.
"""
import os
import json
import sqlite3
import datetime

# Single source of truth for the persistent data volume root.
DATA_ROOT = os.path.realpath(os.getenv("DATA_ROOT", "/data"))


def data_path(name):
    """Absolute path to <name> on the data volume."""
    return os.path.join(DATA_ROOT, name)


def _now():
    return datetime.datetime.utcnow().isoformat(timespec="seconds")


class JSONStore:
    """
    Minimal id -> JSON document store on the data volume.

    Each row is (id TEXT PK, data TEXT json, updated_at TEXT). Documents are
    plain dicts; `id` and `updated_at` are managed by the store and merged into
    the dict on read (and stripped on write).
    """

    def __init__(self, filename, env_var=None):
        default = data_path(filename)
        self.path = os.getenv(env_var, default) if env_var else default

    def _conn(self):
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        c = sqlite3.connect(self.path, timeout=5.0)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=5000")
        return c

    def init_db(self):
        with self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id         TEXT PRIMARY KEY,
                    data       TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _hydrate(self, row):
        try:
            d = json.loads(row["data"])
        except Exception:
            d = {}
        d["id"] = row["id"]
        d["updated_at"] = row["updated_at"]
        return d

    def list_ids(self):
        with self._conn() as c:
            rows = c.execute("SELECT id FROM documents ORDER BY id").fetchall()
        return [r["id"] for r in rows]

    def list(self):
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, data, updated_at FROM documents ORDER BY id"
            ).fetchall()
        return [self._hydrate(r) for r in rows]

    def get(self, id_):
        with self._conn() as c:
            r = c.execute(
                "SELECT id, data, updated_at FROM documents WHERE id=?", (id_,)
            ).fetchone()
        return self._hydrate(r) if r else None

    def put(self, id_, data):
        payload = {k: v for k, v in (data or {}).items()
                   if k not in ("id", "updated_at")}
        with self._conn() as c:
            c.execute(
                "INSERT INTO documents (id, data, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET data=excluded.data, "
                "updated_at=excluded.updated_at",
                (id_, json.dumps(payload), _now()),
            )
        return self.get(id_)

    def delete(self, id_):
        with self._conn() as c:
            c.execute("DELETE FROM documents WHERE id=?", (id_,))
