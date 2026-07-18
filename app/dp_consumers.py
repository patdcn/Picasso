"""
DP power-consumer registry — named non-thruster consumers for the DP
Capability & Ops Check power panel.

Each consumer carries a planning kW figure (UPPER BOUND for duty consumers —
under-budgeting generation is the expensive mistake), a bus assignment, and a
provenance note. Selected consumers on the DP page sum to per-bus auxiliary
load which PREFILLS the (still editable) aux fields feeding the per-DG loading
logic.

Storage: a table in the same SQLite parameter database as app.params
(/data volume, survives redeploys), admin-edited via /admin/dp-consumers.
These are DCN operational figures (DPR observations, Lexmar ELA totals,
budgetary estimates) — not Thrustmaster copyright — so both the schema and the
seed values are repo-committable.

Bus assignment
--------------
'bus1' / 'bus2' / 'bus3' pin the consumer to one 690 V bus; 'split'
distributes it across the buses that are energised in the selected DP mode,
weighted by the number of DGs running on each bus (equal per-generator share).
Seed assignments follow the as-built feeding arrangement per the Hareid
El. Load Balance Calc. 2245-880-201 Rev 6: SAT diving (T1/T2), ROV (T3/T4),
the 140T crane (supply 1/2) and the bulk of hotel load (T5–T8) are fed
PS/SB from Bus 1 and Bus 3 only ('bus13'); the 40T crane hangs on Bus 2; air
diving feeds via the 450 V PS side on Bus 1. 'bus13' splits over Bus 1+3
weighted by their running DGs and never touches Bus 2. A consumer pinned to a bus that
is offline in the selected mode (e.g. Bus 2 in 2-split) is redistributed over
the live buses and flagged, so load is never silently dropped.
"""
import datetime
import sqlite3

from app import params  # reuse PARAM_DB path + connection conventions

BUS_CHOICES = ("split", "bus13", "bus1", "bus2", "bus3")
BUS_LABELS = {"split": "Split over live buses", "bus13": "Bus 1+3 (PS/SB pair)",
              "bus1": "Bus 1", "bus2": "Bus 2", "bus3": "Bus 3"}

# Seeded only into an empty table; afterwards the DB (admin-edited) leads.
# (name, kw, bus, category, source, default_on, sort_order)
SEED = [
    ("Hotel & machinery (continuous)", 780.0, "bus13", "Hotel / machinery",
     "Master's DPR machinery list \u2014 sum of continuous consumers (excl. "
     "cranes and the standby service air compressor). Fed PS/SB via "
     "T5\u2013T8 per 2245-880-201.", 1, 10),
    ("140T crane \u2014 operating", 700.0, "bus13", "Cranes",
     "DPR good-weather observations 500\u2013700 kW; upper bound stored. "
     "Dual supply Bus 1+3 per 2245-880-201 (design booking 1,415 kW in the "
     "crane scenario \u2014 yard factors, conservative).", 0, 20),
    ("40T crane \u2014 operating", 400.0, "bus2", "Cranes",
     "DPR good-weather observations 200\u2013400 kW; upper bound stored. "
     "Fed from Busbar 2 per 2245-880-201.", 0, 30),
    ("SAT diving spread \u2014 normal ops", 990.0, "bus13", "Diving",
     "Lexmar ELA 05313-00-006 Rev F: essential 949.6 kW @ 440 V + 41.8 kW "
     "@ 230 V. Cross-check: 2245-880-201 books T1+T2 = 956 kW in the dive "
     "scenario. Fed via T1 (Bus 1) / T2 (Bus 3).", 0, 40),
    ("SAT diving spread \u2014 100% duty ceiling", 1637.0, "bus13", "Diving",
     "Lexmar ELA connected load 1595.5 kW @ 440 V + 41.8 kW @ 230 V \u2014 "
     "a ceiling, not an expectation.", 0, 50),
    ("Work-class ROV spread", 265.0, "bus13", "ROV",
     "Budgetary: 400 A \u00d7 480 V 3-ph, PF 0.8 assumed \u2014 confirm "
     "from spread datasheet. Fed via T3 (Bus 1) / T4 (Bus 3) per "
     "2245-880-201.", 0, 60),
    ("Observation-class ROV", 65.0, "bus13", "ROV",
     "Budgetary: 100 A \u00d7 480 V 3-ph, PF 0.8 assumed \u2014 confirm "
     "from spread datasheet. Fed via T3/T4 (Bus 1/3).", 0, 70),
    ("Air dive spread", 40.0, "bus1", "Diving",
     "2245-880-201: AIR DIVING 50 kW rated, LF 0.8 in dive mode "
     "(\u2248 36\u201345 kW); fed via 450 V PS side \u2192 Bus 1.", 0, 80),
]


def _now():
    return datetime.datetime.utcnow().isoformat(timespec="seconds")


def _conn():
    c = sqlite3.connect(params.PARAM_DB, timeout=5.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    return c


def init_db():
    """Create the table if missing; seed the registry only when empty."""
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS dp_consumers (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                kw         REAL NOT NULL,
                bus        TEXT NOT NULL DEFAULT 'split',
                category   TEXT NOT NULL DEFAULT '',
                source     TEXT NOT NULL DEFAULT '',
                default_on INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
        """)
        n = c.execute("SELECT COUNT(*) AS n FROM dp_consumers").fetchone()["n"]
        if n == 0:
            now = _now()
            for (name, kw, bus, cat, src, don, order) in SEED:
                c.execute(
                    "INSERT INTO dp_consumers "
                    "(name, kw, bus, category, source, default_on, sort_order, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (name, kw, bus, cat, src, don, order, now))


def rows():
    """All consumers, ordered. Each row: dict(id, name, kw, bus, category,
    source, default_on, sort_order)."""
    try:
        with _conn() as c:
            rs = c.execute(
                "SELECT * FROM dp_consumers ORDER BY sort_order, name").fetchall()
        return [dict(r) for r in rs]
    except sqlite3.Error:
        return []


def by_id():
    return {r["id"]: r for r in rows()}


def add(name, kw, bus="split", category="", source="", default_on=0,
        sort_order=None):
    name = (name or "").strip()
    if not name:
        return False, "Name is required."
    try:
        kw = float(kw)
    except (TypeError, ValueError):
        return False, "kW must be a number."
    if kw < 0:
        return False, "kW must be \u2265 0."
    if bus not in BUS_CHOICES:
        bus = "split"
    with _conn() as c:
        if sort_order is None:
            m = c.execute("SELECT COALESCE(MAX(sort_order),0) AS m "
                          "FROM dp_consumers").fetchone()["m"]
            sort_order = int(m) + 10
        c.execute(
            "INSERT INTO dp_consumers "
            "(name, kw, bus, category, source, default_on, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (name, kw, bus, category or "", source or "",
             1 if default_on else 0, int(sort_order), _now()))
    return True, f"Added \u201c{name}\u201d."


def update_many(updates):
    """updates: {id: {'name','kw','bus','category','source','default_on'}}.
    Invalid numbers / unknown buses on a row skip that field, not the save."""
    saved = 0
    now = _now()
    with _conn() as c:
        for cid, u in (updates or {}).items():
            row = c.execute("SELECT * FROM dp_consumers WHERE id=?",
                            (cid,)).fetchone()
            if row is None:
                continue
            name = (u.get("name") or row["name"]).strip() or row["name"]
            try:
                kw = float(u.get("kw"))
                if kw < 0:
                    kw = row["kw"]
            except (TypeError, ValueError):
                kw = row["kw"]
            bus = u.get("bus") if u.get("bus") in BUS_CHOICES else row["bus"]
            cat = u.get("category", row["category"]) or ""
            src = u.get("source", row["source"]) or ""
            don = 1 if u.get("default_on") else 0
            c.execute(
                "UPDATE dp_consumers SET name=?, kw=?, bus=?, category=?, "
                "source=?, default_on=?, updated_at=? WHERE id=?",
                (name, kw, bus, cat, src, don, now, cid))
            saved += 1
    return saved, (f"Saved {saved} consumer{'s' if saved != 1 else ''}."
                   if saved else "Nothing to save.")


def delete(cid):
    with _conn() as c:
        c.execute("DELETE FROM dp_consumers WHERE id=?", (cid,))
    return True, "Deleted."


# ------------------------------------------------------------- distribution

def bus_loads(selected_ids, dgs_per_bus):
    """Distribute the selected consumers over the 690 V buses.

    dgs_per_bus: {'bus1': n, 'bus2': n, 'bus3': n} for the selected DP mode
    (n == 0 -> bus offline). Pinned consumers land on their bus; 'split' and
    consumers pinned to an OFFLINE bus are shared over the live buses weighted
    by running-DG count (equal per-generator share).

    Returns ({'bus1': kW, 'bus2': kW, 'bus3': kW}, warnings, total_kw).
    """
    dgs = {b: int((dgs_per_bus or {}).get(b, 0)) for b in ("bus1", "bus2", "bus3")}
    live = [b for b in ("bus1", "bus2", "bus3") if dgs[b] > 0]
    n_live_dg = sum(dgs[b] for b in live)
    out = {"bus1": 0.0, "bus2": 0.0, "bus3": 0.0}
    warnings = []
    total = 0.0
    if not live:
        return out, ["No bus energised in the selected mode."], 0.0

    reg = by_id()
    for cid in (selected_ids or []):
        r = reg.get(cid)
        if r is None:
            continue
        kw = float(r["kw"])
        total += kw
        bus = r["bus"]
        if bus == "bus13":
            side = [b for b in ("bus1", "bus3") if dgs[b] > 0]
            n_side = sum(dgs[b] for b in side)
            if side:
                for b in side:
                    out[b] += kw * dgs[b] / n_side
                continue
            warnings.append(
                f"\u201c{r['name']}\u201d is fed from Bus 1+3, both offline "
                "in this mode — redistributed over the live buses.")
        elif bus in out and dgs.get(bus, 0) > 0:
            out[bus] += kw
            continue
        elif bus in out and dgs.get(bus, 0) == 0:
            warnings.append(
                f"\u201c{r['name']}\u201d is assigned to "
                f"{BUS_LABELS[bus]}, which is offline in this mode — "
                "redistributed over the live buses.")
        for b in live:
            out[b] += kw * dgs[b] / n_live_dg
    return out, warnings, total
