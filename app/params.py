"""
Central tunable parameters for the portal (cost/timing assumptions, and whatever
else gets added later), persisted in a SQLite database on the same /data volume
as auth.db so edits survive redeploys.

Design:
- REGISTRY (below) is the single source of truth for *what* parameters exist and
  their metadata (label, unit, category, default, step). Add a line here and the
  parameter automatically appears on the Admin page, seeded with its default, and
  becomes queryable by any page via params.get(key).
- The database stores only key -> value (the current, admin-edited numbers). On
  startup init_db() seeds any registry keys that aren't in the DB yet with their
  defaults, so a fresh volume (or a newly-added parameter) starts from sane values.

Usage:
    from app import params
    rate = params.get("day_rate_single_9man")     # current value (DB or default)
    params.set_many({"bell_transit_min": 20})     # admin save
"""
import os
import sqlite3
import datetime

PARAM_DB = os.getenv("PARAM_DB", "/data/parameter.db")


# --------------------------------------------------------------------------- #
# Parameter registry — the source of truth for what exists. Add new entries
# here (any category) and they show up in Admin and are queryable immediately.
# --------------------------------------------------------------------------- #
REGISTRY = [
    # key                           label                          unit   category          default    step   modules (page paths that use it)
    ("day_rate_single_9man",        "Single bell · 9-man",         "USD/day", "Bell day rates", 150000.0,  1000, ("/diving/bell", "/diving/spare-bell")),
    ("day_rate_single_12man",       "Single bell · 12-man",        "USD/day", "Bell day rates", 160000.0,  1000, ("/diving/bell", "/diving/spare-bell")),
    ("day_rate_twin_12man",         "Twin bell · 12-man",          "USD/day", "Bell day rates", 190000.0,  1000, ("/diving/bell",)),
    ("day_rate_single_twin_9man",   "Single-twin · 9-man",         "USD/day", "Bell day rates", 160000.0,  1000, ("/diving/spare-bell",)),
    ("day_rate_single_twin_12man",  "Single-twin · 12-man",        "USD/day", "Bell day rates", 170000.0,  1000, ("/diving/spare-bell",)),
    ("bell_transit_min",            "Bell to job transit (one way)", "min", "Bell timing",    15.0,      1,    ("/diving/bell", "/diving/spare-bell")),
    ("bell_changeover_h",           "Bell changeover",             "h",    "Bell timing",     1.0,      0.25, ("/diving/bell", "/diving/spare-bell")),
    # Currency conversion. EUR shown on the diving pages = USD rate × this factor.
    # modules empty -> appears in the Admin assumptions card but adds no per-page
    # "edit parameters" checkbox (it's a global figure, not a per-page parameter).
    ("usd_eur_rate",                "USD \u2192 EUR exchange rate", "EUR per USD", "Currency", 0.92, 0.001, ()),
    # Dive planning (Air MG Diving). The timing assumptions are the restrictable
    # parameters on the page; the remaining rows seed the scenario defaults.
    ("dp_descent_rate",       "Descent to worksite",               "m/min",  "Dive planning", 10.0, 1,   ("/air-diving/dive-planning",)),
    ("dp_arrive_min",         "Arrive at worksite",                "min",    "Dive planning", 3.0,  0.5, ("/air-diving/dive-planning",)),
    ("dp_return_min",         "Return from worksite",              "min",    "Dive planning", 3.0,  0.5, ("/air-diving/dive-planning",)),
    ("dp_undress_min",        "Undress",                           "min",    "Dive planning", 3.0,  0.5, ("/air-diving/dive-planning",)),
    ("dp_turnaround_min",     "Turn-around (next diver ready)",    "min",    "Dive planning", 15.0, 1,   ("/air-diving/dive-planning",)),
    ("dp_divers_per_shift",   "Divers per shift (default)",        "divers", "Dive planning", 8.0,  1,   ("/air-diving/dive-planning",)),
    ("dp_repeats_per_diver",  "Repeat dives per diver (default)",  "dives",  "Dive planning", 1.0,  1,   ("/air-diving/dive-planning",)),
    ("dp_start_hour",         "Shift start hour (default)",        "h",      "Dive planning", 6.0,  1,   ("/air-diving/dive-planning",)),
    ("dp_tidal_windows",      "Tidal slack windows / day (default)", "windows", "Dive planning", 4.0, 1, ("/air-diving/dive-planning",)),
    ("dp_tidal_window_min",   "Work window per tide (default)",    "min",    "Dive planning", 90.0, 5,   ("/air-diving/dive-planning",)),
    # Dive-gas breathing rates (atmospheric / surface RMV; multiplied by the
    # absolute pressure at depth to get real consumption). Editable = restrictable.
    ("dp_rmv_working",        "Breathing rate - working diver",    "L/min",  "Dive gas", 40.0, 1, ("/air-diving/dive-planning",)),
    ("dp_rmv_deco",           "Breathing rate - deco diver",       "L/min",  "Dive gas", 30.0, 1, ("/air-diving/dive-planning",)),
    ("dp_quad_residual_bar",  "Residual quad pressure",            "bar",    "Dive gas", 40.0, 5, ("/air-diving/dive-planning",)),
    # Saturation gas — minimum-gas model coefficients (IMCA D050 framework).
    # These are the model constants behind the SAT minimum-gas calculator; the
    # per-job figures (depths, deco time, divers) are entered on the page. All
    # are locked for accounts without the /diving/sat-gas edit-parameters grant.
    # DP fuel — DG SFOC anchors, ELECTRICAL basis (g per kWe·h). Values from the
    # MAN L27/38 project guide Tier II sheet 1689470-5.4, 330 kW/cyl @ 720 rpm
    # (9L27/38 = 2970 kW engine × 0.96 alternator = 2851 kWe = the DG rating),
    # engine g/kWh divided by 0.96. ISO reference, LCV 42.7 MJ/kg, WITHOUT the
    # +5% guarantee tolerance and without attached pumps (electric pumps sit in
    # the hotel consumer). Refine with shop-test/FAT records when available.
    ("dg_sfoc_25",       "DG SFOC @ 25% load",   "g/kWh", "DP fuel", 216.0, 1,    ("/dp/env-planner",)),
    ("dg_sfoc_50",       "DG SFOC @ 50% load",   "g/kWh", "DP fuel", 191.0, 1,    ("/dp/env-planner",)),
    ("dg_sfoc_75",       "DG SFOC @ 75% load",   "g/kWh", "DP fuel", 190.0, 1,    ("/dp/env-planner",)),
    ("dg_sfoc_85",       "DG SFOC @ 85% load",   "g/kWh", "DP fuel", 189.0, 1,    ("/dp/env-planner",)),
    ("dg_sfoc_100",      "DG SFOC @ 100% load",  "g/kWh", "DP fuel", 192.0, 1,    ("/dp/env-planner",)),
    ("dg_fuel_density",  "Fuel density (MGO)",   "kg/l",  "DP fuel", 0.85,  0.005,("/dp/env-planner",)),
    ("sat_dive_rmv",          "Bell breathing rate (per diver)",   "L/min",       "Saturation gas", 40.0,  1,    ("/diving/sat-gas",)),
    ("sat_dive_run_min",      "Bell-run duration (reserve)",       "min",         "Saturation gas", 480.0, 15,   ("/diving/sat-gas",)),
    ("sat_dive_runs",         "Bell runs held in reserve",         "runs",        "Saturation gas", 2.0,   1,    ("/diving/sat-gas",)),
    ("sat_bibs_lpm",          "BIBS flow (per diver)",             "L/min",       "Saturation gas", 20.0,  1,    ("/diving/sat-gas",)),
    ("sat_bibs_hours",        "BIBS duration (per diver)",         "h",           "Saturation gas", 4.0,   0.5,  ("/diving/sat-gas",)),
    ("sat_blowdowns",         "System blowdowns held",             "blowdowns",   "Saturation gas", 1.0,   1,    ("/diving/sat-gas",)),
    ("sat_lineloss_m3_day",   "Line loss",                         "m\u00b3/day", "Saturation gas", 30.0,  1,    ("/diving/sat-gas",)),
    ("sat_lineloss_cycles",   "Decompression cycles (line loss)",  "cycles",      "Saturation gas", 2.0,   1,    ("/diving/sat-gas",)),
    ("sat_therapeutic_lpm",   "Therapeutic flow",                  "L/min",       "Saturation gas", 20.0,  1,    ("/diving/sat-gas",)),
    ("sat_therapeutic_min",   "Therapeutic minutes (per diver)",   "min",         "Saturation gas", 200.0, 10,   ("/diving/sat-gas",)),
    ("sat_o2_metabolic",      "Metabolic O\u2082",                 "m\u00b3/diver/day", "Saturation gas", 0.72, 0.01, ("/diving/sat-gas",)),
    ("sat_o2_deco_coeff",     "Decompression O\u2082 coefficient", "coeff",       "Saturation gas", 0.5,   0.05, ("/diving/sat-gas",)),
    ("sat_o2_ppo2_coeff",     "PPO\u2082 build-up O\u2082 coefficient", "coeff",  "Saturation gas", 0.1,   0.01, ("/diving/sat-gas",)),
    ("sat_o2_reserve",        "O\u2082 reserve",                   "m\u00b3",     "Saturation gas", 90.0,  5,    ("/diving/sat-gas",)),
    # Saturation consumption / cost model coefficients (ported from the Picasso
    # gas workbook). Per-job figures and volumes are entered on the page; these
    # are the assumptions, locked for accounts without the edit grant.
    ("sat_c_o2_resting",      "O\u2082 resting / deco",            "L/min",   "Saturation consumption", 0.8,   0.1,  ("/diving/sat-consumption",)),
    ("sat_c_o2_moderate",     "O\u2082 moderate activity",         "L/min",   "Saturation consumption", 2.5,   0.1,  ("/diving/sat-consumption",)),
    ("sat_c_br_working",      "Heliox breathing rate (working)",   "L/min",   "Saturation consumption", 40.0,  1,    ("/diving/sat-consumption",)),
    ("sat_c_br_bellman",      "Heliox breathing rate (bellman)",   "L/min",   "Saturation consumption", 25.0,  1,    ("/diving/sat-consumption",)),
    ("sat_c_sodasorb_pp_day", "Sodasorb per occupant / day",       "unit/day","Saturation consumption", 0.36,  0.01, ("/diving/sat-consumption",)),
    ("sat_c_loss_chamber",    "General chamber loss",              "frac/day","Saturation consumption", 0.005, 0.001,("/diving/sat-consumption",)),
    ("sat_c_loss_diver",      "General bell / diver loss",         "frac",    "Saturation consumption", 0.01,  0.001,("/diving/sat-consumption",)),
    ("sat_c_reclaim",         "Reclaim efficiency (all)",          "frac",    "Saturation consumption", 0.90,  0.01, ("/diving/sat-consumption",)),
    ("sat_c_blowdown_ppo2",   "Blowdown target PPO\u2082",         "bar",     "Saturation consumption", 0.4,   0.05, ("/diving/sat-consumption",)),
    ("sat_c_mix_a_o2",        "Blowdown mix A O\u2082",            "frac",    "Saturation consumption", 0.20,  0.01, ("/diving/sat-consumption",)),
    ("sat_c_mix_b_o2",        "Blowdown mix B O\u2082",            "frac",    "Saturation consumption", 0.02,  0.01, ("/diving/sat-consumption",)),
    ("sat_c_deco_ppo2",       "Decompression PPO\u2082",           "bar",     "Saturation consumption", 0.5,   0.05, ("/diving/sat-consumption",)),
    ("sat_c_cost_heliox",     "Heliox unit cost",                  "\u20ac/m\u00b3", "Saturation consumption", 25.0, 1, ("/diving/sat-consumption",)),
    ("sat_c_cost_o2",         "Oxygen unit cost",                  "\u20ac/m\u00b3", "Saturation consumption", 6.0,  1, ("/diving/sat-consumption",)),
    ("sat_c_cost_sodasorb",   "Sodasorb unit cost",                "\u20ac/kg",      "Saturation consumption", 11.0, 1, ("/diving/sat-consumption",)),
]

_DEFAULTS = {k: dflt for (k, _l, _u, _c, dflt, _s, _m) in REGISTRY}
_KEYS = [k for (k, *_rest) in REGISTRY]


def definitions():
    """Ordered parameter metadata for the Admin UI."""
    return [
        {"key": k, "label": l, "unit": u, "category": c, "default": d, "step": s, "modules": list(m)}
        for (k, l, u, c, d, s, m) in REGISTRY
    ]


def param_edit_modules():
    """Set of page paths that expose editable parameters (union over the registry).
    The Admin page uses this to decide which modules get an 'edit parameters'
    checkbox; pages use it implicitly via auth.may_edit_params(user, path)."""
    mods = set()
    for (_k, _l, _u, _c, _d, _s, m) in REGISTRY:
        mods.update(m)
    return sorted(mods)


# --------------------------------------------------------------------------- #
# DB plumbing
# --------------------------------------------------------------------------- #
def _now():
    return datetime.datetime.utcnow().isoformat(timespec="seconds")


def _conn():
    parent = os.path.dirname(PARAM_DB)
    if parent:
        os.makedirs(parent, exist_ok=True)
    c = sqlite3.connect(PARAM_DB, timeout=5.0)
    c.row_factory = sqlite3.Row
    # WAL: lets the bell pages read while an admin save writes (2 gunicorn workers).
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    return c


def init_db():
    """Create the table and seed any registry keys that aren't stored yet."""
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS parameters (
                key        TEXT PRIMARY KEY,
                value      REAL NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        have = {r["key"] for r in c.execute("SELECT key FROM parameters").fetchall()}
        now = _now()
        for k in _KEYS:
            if k not in have:
                c.execute("INSERT INTO parameters (key, value, updated_at) VALUES (?,?,?)",
                          (k, float(_DEFAULTS[k]), now))


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #
def get(key, default=None):
    """Current value for key: DB value if present, else the registry default
    (or the supplied default for unknown keys). Returns a float."""
    try:
        with _conn() as c:
            row = c.execute("SELECT value FROM parameters WHERE key=?", (key,)).fetchone()
        if row is not None:
            return float(row["value"])
    except Exception:
        pass
    if key in _DEFAULTS:
        return float(_DEFAULTS[key])
    return default


# convenience alias used by the pages (always numeric)
get_float = get


def get_all():
    """Dict of {key: current value} for every registry key."""
    out = {}
    try:
        with _conn() as c:
            rows = c.execute("SELECT key, value FROM parameters").fetchall()
        stored = {r["key"]: float(r["value"]) for r in rows}
    except Exception:
        stored = {}
    for k in _KEYS:
        out[k] = stored.get(k, float(_DEFAULTS[k]))
    return out


# --------------------------------------------------------------------------- #
# Write (admin)
# --------------------------------------------------------------------------- #
def set_many(values):
    """
    Upsert a {key: value} mapping. Unknown keys are ignored; non-numeric values
    are skipped. Returns (n_saved, message).
    """
    saved = 0
    now = _now()
    with _conn() as c:
        for key, val in (values or {}).items():
            if key not in _DEFAULTS:
                continue
            try:
                v = float(val)
            except (TypeError, ValueError):
                continue
            c.execute(
                "INSERT INTO parameters (key, value, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, v, now),
            )
            saved += 1
    if saved == 0:
        return 0, "Nothing to save."
    return saved, f"Saved {saved} parameter{'s' if saved != 1 else ''}."
