"""
DCN Calculation Module - database layer.

calc.db lives on the persistent /data volume (same pattern as auth.db /
parameter.db). WAL mode is enabled so many read-only viewers can poll the
edit journal while one estimator writes. PRAGMA user_version carries the
schema revision so future upgrades can migrate in place.

The repository layer (repo.py) is the only intended consumer of conn();
pages never touch SQL directly. Keeping every query in repo.py is what
keeps a later SQLite -> Postgres migration a config change, not a rewrite.
"""
import os
import sqlite3
import uuid as _uuid

CALC_DB = os.getenv("CALC_DB", "/data/calc.db")

SCHEMA_REV = 1
_SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "schema.sql")

SEED_DIVISIONS = [("CIV", "Civil"), ("OFF", "Offshore"), ("HYD", "Hydropower")]
SEED_REGIONS = [("EUR", "Europe"), ("WAF", "West Africa"),
                ("UAE", "United Arab Emirates"), ("SEA", "South East Asia")]
SEED_CURRENCIES = [("USD", "US Dollar", "$"), ("EUR", "Euro", "\u20ac"),
                   ("GBP", "Pound Sterling", "\u00a3"),
                   ("AED", "UAE Dirham", "AED"), ("SGD", "Singapore Dollar", "S$")]

ELEMENTS = ["internal_labor", "external_labor", "subcontracting", "materials",
            "internal_equipment", "external_equipment", "services"]
ELEMENT_LABELS = {
    "internal_labor": "Internal labor", "external_labor": "External labor",
    "subcontracting": "Sub-contracting", "materials": "Materials",
    "internal_equipment": "Internal equipment",
    "external_equipment": "External equipment", "services": "Services",
}
LABOR_ELEMENTS = ("internal_labor", "external_labor")


def new_uuid():
    return str(_uuid.uuid4())


def conn():
    parent = os.path.dirname(CALC_DB)
    if parent:
        os.makedirs(parent, exist_ok=True)
    c = sqlite3.connect(CALC_DB, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA journal_mode = WAL")
    return c


def init_db():
    """Create schema if missing, seed dimensions, stamp schema revision.
    Idempotent - safe to call on every boot (portal convention)."""
    c = conn()
    try:
        with open(_SCHEMA_FILE, encoding="utf-8") as fh:
            c.executescript(fh.read())
        cur = c.execute("PRAGMA user_version").fetchone()[0]
        if cur < SCHEMA_REV:
            # migration hook for future schema revisions
            c.execute(f"PRAGMA user_version = {SCHEMA_REV}")
        for code, name in SEED_DIVISIONS:
            c.execute("INSERT OR IGNORE INTO divisions VALUES (?,?)", (code, name))
        for code, name in SEED_REGIONS:
            c.execute("INSERT OR IGNORE INTO regions VALUES (?,?)", (code, name))
        for code, name, sym in SEED_CURRENCIES:
            c.execute("INSERT OR IGNORE INTO currencies VALUES (?,?,?)",
                      (code, name, sym))
        # a fresh install gets one draft rate set so the admin page has a hook
        if not c.execute("SELECT 1 FROM rate_sets LIMIT 1").fetchone():
            c.execute("INSERT INTO rate_sets (label, status, created_by) "
                      "VALUES ('Initial', 'active', 'system')")
            rs = c.execute("SELECT id FROM rate_sets WHERE label='Initial'"
                           ).fetchone()["id"]
            c.execute("INSERT OR IGNORE INTO exchange_rates "
                      "(rate_set_id, currency, rate_to_usd) VALUES (?,?,1.0)",
                      (rs, "USD"))
        c.commit()
    finally:
        c.close()
