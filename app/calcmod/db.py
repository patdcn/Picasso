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

SCHEMA_REV = 2
_SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "schema.sql")

SEED_DIVISIONS = [("CIV", "Civil"), ("OFF", "Offshore"), ("HYD", "Hydropower")]
SEED_REGIONS = [("EUR", "Europe"), ("WAF", "West Africa"),
                ("UAE", "United Arab Emirates"), ("SEA", "South East Asia"),
                ("ALL", "All regions (rate fallback)")]
SEED_CURRENCIES = [("USD", "US Dollar", "$"), ("EUR", "Euro", "\u20ac"),
                   ("GBP", "Pound Sterling", "\u00a3"),
                   ("AED", "UAE Dirham", "AED"), ("SGD", "Singapore Dollar", "S$")]

# Four elements, aligned with IBIS and Business Central so a future export
# maps one-to-one. Internal/external is a refinement WITHIN labor and
# equipment (line-level ownership), not a separate element.
ELEMENTS = ["labor", "subcontracting", "materials", "equipment"]
ELEMENT_LABELS = {"labor": "Labor", "subcontracting": "Sub-contracting",
                  "materials": "Materials", "equipment": "Equipment"}
LABOR_ELEMENTS = ("labor",)
SPLIT_ELEMENTS = ("labor", "equipment")      # carry an internal/external split

# Misc sub-categories seeded on first boot; admin-extensible on
# Admin -> Calculation module. Each maps to the element it prefills.
SEED_MISC_CATEGORIES = [
    ("materials", "materials"), ("fuel", "materials"), ("gas", "materials"),
    ("consumables", "materials"),
    ("flights", "subcontracting"), ("accommodation", "subcontracting"),
    ("engineering service", "subcontracting"), ("fabrication", "subcontracting"),
    ("freight", "subcontracting"),
]


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


_MODULE_TABLES = [
    "calc_grants", "locks", "edit_journal", "block_refs", "block_lines", "blocks",
    "snap_items", "snap_markups", "snap_fx", "revisions", "calculations",
    "library_requests", "block_templates", "markup_sets", "misc_rates", "misc_items",
    "misc_categories", "personnel_rates", "personnel_items", "equipment_rates",
    "equipment_items", "exchange_rates", "rate_sets", "currencies", "regions",
    "divisions",
]


def init_db():
    """Create schema if missing, seed dimensions, stamp schema revision.
    Idempotent - safe to call on every boot (portal convention).

    Development phase: a pre-Rev-2 database is dropped and recreated clean
    (agreed with Patrick - library/calc entries are expendable until the
    structure settles). Once real data exists, this block is replaced by an
    in-place migration keyed on user_version."""
    c = conn()
    try:
        cur = c.execute("PRAGMA user_version").fetchone()[0]
        has_tables = bool(c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='revisions'"
        ).fetchone())
        if has_tables and cur < SCHEMA_REV:
            for t in _MODULE_TABLES:
                c.execute(f"DROP TABLE IF EXISTS {t}")
            c.execute("DROP TRIGGER IF EXISTS trg_revision_issued_lock")
            c.commit()
        with open(_SCHEMA_FILE, encoding="utf-8") as fh:
            c.executescript(fh.read())
        for code, name in SEED_DIVISIONS:
            c.execute("INSERT OR IGNORE INTO divisions VALUES (?,?)", (code, name))
        for code, name in SEED_REGIONS:
            c.execute("INSERT OR IGNORE INTO regions VALUES (?,?)", (code, name))
        for code, name, sym in SEED_CURRENCIES:
            c.execute("INSERT OR IGNORE INTO currencies VALUES (?,?,?)",
                      (code, name, sym))
        for name, element in SEED_MISC_CATEGORIES:
            c.execute("INSERT OR IGNORE INTO misc_categories (name, element) "
                      "VALUES (?,?)", (name, element))
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
