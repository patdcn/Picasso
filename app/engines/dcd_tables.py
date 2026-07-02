"""
Decompression-table store — DCD / revised NDC (and, later, USN / DCIEM / GERS).

This is the *storage + query* layer behind the DCD Tables page. It is deliberately
multi-standard from day one so the eventual comparison view ("plot the 30 m deco
profile for DCD vs USN vs DCIEM") is a query, not a rebuild.

Design (agreed hybrid model)
----------------------------
Three levels of reference metadata plus one fact table:

    dive_standard   one row per publisher/model (DCD, USN Rev7, DCIEM, GERS...)
    table_family    one row per named table code (SIL15, H4SIL15, SOX15...)
    schedule        one row per (family, table depth, bottom time)

Every schedule row carries the whole decompression profile as JSON
(`profile_json`) rather than a normalised child table. The planner and the plot
always want the *entire* profile for one (depth, time) pair, so a single-row
fetch beats a join; the JSON is trivial to render and to overlay. Scalar outputs
(TTS, total deco, repetitive group, OTU) are also columns so they're queryable
without parsing JSON.

Units follow the sat_deco convention: the *native* unit of the source is stored
verbatim (`depth_native` + `depth_unit`) AND a canonical metres value
(`table_depth_m`) is stored for cross-standard alignment. DCD is metric so the two
match; USN is fsw and will differ. Repetitive-group letters are standard-specific
and must never be compared across standards.

Data / copyright
----------------
The *numbers* are copyrighted (DCD, DCIEM, GERS) and never live in the repo. The
loader reads a source-of-truth JSON from the /data volume
(DCD_SOURCE_DIR, default /data/tools/dcd/) and builds the SQLite DB
(DCD_DB, default /data/dcd_tables.db). Only this code and a synthetic example
source ship in git. USN tables are US-Government public domain and may be shipped.

Every row is loaded `verified=0`. A human signs off page-by-page against the
source image via build_qa_report(); nothing is trusted until verified=1.
"""
import os
import json
import sqlite3
import datetime

DCD_DB = os.getenv("DCD_DB", "/data/dcd_tables.db")
DCD_SOURCE_DIR = os.getenv("DCD_SOURCE_DIR", "/data/tools/dcd")

# Ascent-speed and policy constants that belong to the DCD tables themselves.
# (Vessel-tunable policy limits — PO2 max, OTU caps, 8h/24h — live in params.py.)
DEFAULT_ASCENT_MAX_MPM = 10.0
DEFAULT_ASCENT_MIN_MPM = 5.0

# Canonical vocabulary — shared across standards so comparisons don't fracture.
GASES = {"air", "o2", "nitrox_40_60", "nitrox_35_65", "heliox", "trimix"}
MODES = {"inwater", "surfaceox", "bell", "nostop", "treatment"}


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS dive_standard (
    code          TEXT PRIMARY KEY,       -- 'DCD','USN','DCIEM','GERS'
    name          TEXT NOT NULL,
    publisher     TEXT,
    edition       TEXT,
    model         TEXT,                   -- decompression model / origin
    units_native  TEXT,                   -- 'm' or 'fsw'
    license       TEXT,
    public        INTEGER DEFAULT 0,      -- may this data be shown/exported publicly?
    source_ref    TEXT
);

CREATE TABLE IF NOT EXISTS table_family (
    code             TEXT PRIMARY KEY,    -- 'SIL15','H4SIL15','SOX15',...
    standard_code    TEXT NOT NULL REFERENCES dive_standard(code),
    gas              TEXT NOT NULL,
    mode             TEXT NOT NULL,
    repeat_interval_h INTEGER,            -- 12 / 4 / 2 ; NULL if n/a
    o2_used          INTEGER DEFAULT 0,
    is_backup        INTEGER DEFAULT 0,   -- SAB / BAB air back-up family
    revision         TEXT,
    ascent_max_mpm   REAL,
    ascent_min_mpm   REAL,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS schedule (
    id                INTEGER PRIMARY KEY,
    family_code       TEXT NOT NULL REFERENCES table_family(code),
    table_depth_m     REAL NOT NULL,      -- canonical metres (for cross-standard)
    depth_native      REAL,               -- as printed in source
    depth_unit        TEXT,               -- 'm' / 'fsw'
    bottom_time_min   INTEGER NOT NULL,
    till_first_stop_min REAL,             -- 'till 1st stop' column
    tts_min           REAL,               -- time to surface
    total_deco_min    REAL,
    sum_stops_min     REAL,               -- derived: sum of stop minutes (QA checksum)
    rep_group         TEXT,               -- STANDARD-SPECIFIC; never cross-compare
    otu               REAL,
    o2_periods        INTEGER,            -- SurD / bell only
    surface_interval_max_min REAL,        -- SurD only
    below_bold_line   INTEGER DEFAULT 0,  -- air back-up region (air deco > 30 min)
    profile_json      TEXT,               -- ordered [{depth_m,gas,minutes,...}]
    qa_flags          TEXT,               -- JSON list of validation issues (empty = clean)
    source_page       INTEGER,            -- PDF page for QA
    verified          INTEGER DEFAULT 0,
    UNIQUE(family_code, table_depth_m, bottom_time_min)
);
CREATE INDEX IF NOT EXISTS ix_sched_lookup
    ON schedule(family_code, table_depth_m, bottom_time_min);

-- Reference / limit tables (feed the planner's rule engine). Multi-standard.
CREATE TABLE IF NOT EXISTS nostop_limit (
    standard_code    TEXT NOT NULL REFERENCES dive_standard(code),
    table_depth_m    REAL NOT NULL,
    depth_native     REAL,
    depth_unit       TEXT,
    repeat_interval_h INTEGER,
    no_stop_min      REAL,
    is_extended      INTEGER DEFAULT 0,   -- LND15 extended limits
    source_page      INTEGER,
    PRIMARY KEY (standard_code, table_depth_m, repeat_interval_h, is_extended)
);

CREATE TABLE IF NOT EXISTS po2_limit (        -- NOAA CNS limits (standard-neutral)
    po2_bar          REAL PRIMARY KEY,
    max_single_min   REAL,
    max_24h_min      REAL
);

CREATE TABLE IF NOT EXISTS otu_per_depth (    -- 100% O2, DCD sec 5.4
    depth_m          REAL PRIMARY KEY,
    otu_per_10min    REAL,
    otu_per_20min    REAL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY, value TEXT
);
"""


# --------------------------------------------------------------------------- #
# Build (load source-of-truth JSON -> SQLite)
# --------------------------------------------------------------------------- #
class LoadError(ValueError):
    pass


def _connect(db_path=None):
    path = db_path or DCD_DB
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _expand_profile(stops, stop_depths, gas_default):
    """Turn a {stop_depth: minutes | {"min":m,"gas":g,...}} dict into an ordered
    deepest->shallowest profile list, validating stop depths."""
    profile = []
    total = 0.0
    for d in sorted((float(k) for k in stops), reverse=True):
        raw = stops[str(int(d)) if float(int(d)) == d else str(d)] if str(d) not in stops else stops[str(d)]
        # accept int/float minutes or a dict for O2 periods / air breaks
        if isinstance(raw, dict):
            minutes = float(raw.get("min", 0))
            gas = raw.get("gas", gas_default)
            entry = {"depth_m": d, "gas": gas, "minutes": minutes}
            for opt in ("periods", "air_break_min"):
                if opt in raw:
                    entry[opt] = raw[opt]
        else:
            minutes = float(raw)
            entry = {"depth_m": d, "gas": gas_default, "minutes": minutes}
        if stop_depths and d not in stop_depths:
            raise LoadError(f"stop depth {d} m not in declared stop_depths {stop_depths}")
        profile.append(entry)
        total += minutes
    return profile, total


def validate_surfaceox_row(depth_m, iw_stops, chamber_stops, deco_min, till_min):
    """Exact QA for surface-decompression rows (SOX/HSOX O2, SAB/HSAB air).
    Confirmed against the DCD 2015 tables:
        deco = depth/10 + sum(in-water stops) + sum(chamber stops) + deepest_chamber/10
        till = (depth - deepest in-water stop)/10   (= depth/10 if no in-water stop)
    where the chamber ascent term is 12/10 on O2 (recompress to 12 m) or 18/10 on air.
    iw_stops / chamber_stops: {depth_m: minutes}. Returns short flag codes."""
    flags = []
    siw = sum(iw_stops.values())
    sch = sum(chamber_stops.values())
    deepest_ch = max(chamber_stops) if chamber_stops else 0
    if deco_min is not None:
        exp = round(depth_m / 10.0 + siw + sch + deepest_ch / 10.0, 1)
        if abs(deco_min - exp) > 0.11:
            flags.append(f"deco≠{exp}")
    if till_min is not None:
        deepest_iw = max(iw_stops) if iw_stops else None
        exp = round((depth_m - deepest_iw) / 10.0, 1) if deepest_iw else round(depth_m / 10.0, 1)
        if abs(till_min - exp) > 0.11:
            flags.append(f"till≠{exp}")
    return flags


def _validate_row(row, depth_m, sum_stops, deepest_stop, prev_deco, prev_otu):
    """Model-free QA checks. Returns short flag codes (empty = clean).
    For these DCD air/nitrox tables two relations are EXACT (ascent 10 m/min):
        total_deco = depth/10 + Σ(stop minutes)
        till_1st   = (depth − deepest stop)/10
    so violations pinpoint OCR/transcription errors. Softer monotonic checks
    catch the rest. Never aborts the build; the QA report shows what to check."""
    flags = []
    td = row.get("total_deco_min")
    if td is None:
        flags.append("no_deco")
    else:
        exp = round(depth_m / 10.0 + sum_stops, 1)
        if abs(td - exp) > 0.11:
            flags.append(f"deco≠{exp}")
        if prev_deco is not None and td < prev_deco - 0.01:
            flags.append("deco<prev")
    till = row.get("till_first_stop_min")
    if till is not None and deepest_stop is not None:
        expt = round((depth_m - deepest_stop) / 10.0, 1)
        if abs(till - expt) > 0.11:
            flags.append(f"till≠{expt}")
    otu = row.get("otu")
    if otu is not None:
        if otu < 0:
            flags.append("otu<0")
        if prev_otu is not None and otu < prev_otu - 0.01:
            flags.append("otu<prev")
    return flags


def build_db(source_dir=None, db_path=None):
    """(Re)build the SQLite DB from every *.json source file on the volume.

    Returns a summary dict: {loaded, verified, warnings:[...], families:[...]}.
    Idempotent — drops and rebuilds the fact rows for each family it finds.
    """
    source_dir = source_dir or DCD_SOURCE_DIR
    con = _connect(db_path)
    con.executescript(SCHEMA)
    warnings, families, n_loaded = [], [], 0

    files = sorted(f for f in os.listdir(source_dir) if f.endswith(".json")) \
        if os.path.isdir(source_dir) else []
    for fname in files:
        with open(os.path.join(source_dir, fname), "r", encoding="utf-8") as fh:
            src = json.load(fh)

        std, fam = src["standard"], src.get("family")

        con.execute(
            "INSERT OR REPLACE INTO dive_standard "
            "(code,name,publisher,edition,model,units_native,license,public,source_ref)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (std["code"], std["name"], std.get("publisher"), std.get("edition"),
             std.get("model"), std.get("units_native"), std.get("license"),
             int(std.get("public", 0)), std.get("source_ref")))

        # No-stop limit tables (ND15 / LND15) load into the same store, uniformly.
        for nl in src.get("nostop_limits", []):
            con.execute(
                "INSERT OR REPLACE INTO nostop_limit (standard_code,table_depth_m,"
                "depth_native,depth_unit,repeat_interval_h,no_stop_min,is_extended,"
                "source_page) VALUES (?,?,?,?,?,?,?,?)",
                (std["code"], float(nl["table_depth_m"]),
                 nl.get("depth_native", nl["table_depth_m"]),
                 nl.get("depth_unit", std.get("units_native", "m")),
                 nl.get("repeat_interval_h"), nl.get("no_stop_min"),
                 int(nl.get("is_extended", 0)), nl.get("source_page")))
            n_loaded += 1

        if not fam:                      # nostop-only source file: done
            continue
        if fam["gas"] not in GASES:
            raise LoadError(f"{fname}: unknown gas {fam['gas']}")
        if fam["mode"] not in MODES:
            raise LoadError(f"{fname}: unknown mode {fam['mode']}")

        con.execute(
            "INSERT OR REPLACE INTO table_family "
            "(code,standard_code,gas,mode,repeat_interval_h,o2_used,is_backup,"
            "revision,ascent_max_mpm,ascent_min_mpm,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (fam["code"], std["code"], fam["gas"], fam["mode"],
             fam.get("repeat_interval_h"), int(fam.get("o2_used", 0)),
             int(fam.get("is_backup", 0)), fam.get("revision"),
             fam.get("ascent_max_mpm", DEFAULT_ASCENT_MAX_MPM),
             fam.get("ascent_min_mpm", DEFAULT_ASCENT_MIN_MPM), fam.get("notes")))

        con.execute("DELETE FROM schedule WHERE family_code=?", (fam["code"],))
        stop_depths = set(src.get("stop_depths_m", []))
        for block in src["schedules"]:
            depth_m = float(block["table_depth_m"])
            prev_deco = prev_otu = None
            for row in sorted(block["rows"], key=lambda r: r["bottom_time_min"]):
                stops = row.get("stops", {}) or {}
                profile, sum_stops = _expand_profile(stops, stop_depths, fam["gas"])
                deepest = max((float(k) for k in stops), default=None)
                flags = _validate_row(row, depth_m, sum_stops, deepest,
                                      prev_deco, prev_otu)
                if flags:
                    warnings.append(f"{fam['code']} {depth_m:g}m/"
                                    f"{row['bottom_time_min']}min: {','.join(flags)}")
                if row.get("total_deco_min") is not None:
                    prev_deco = row["total_deco_min"]
                if row.get("otu") is not None:
                    prev_otu = row["otu"]
                con.execute(
                    "INSERT INTO schedule (family_code,table_depth_m,depth_native,"
                    "depth_unit,bottom_time_min,till_first_stop_min,tts_min,"
                    "total_deco_min,sum_stops_min,rep_group,otu,o2_periods,"
                    "surface_interval_max_min,below_bold_line,profile_json,"
                    "qa_flags,source_page,verified) VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (fam["code"], depth_m, block.get("depth_native", depth_m),
                     block.get("unit", std.get("units_native", "m")),
                     int(row["bottom_time_min"]), row.get("till_first_stop_min"),
                     row.get("tts_min"), row.get("total_deco_min"), sum_stops,
                     row.get("rep_group"), row.get("otu"), row.get("o2_periods"),
                     row.get("surface_interval_max_min"),
                     int(row.get("below_bold_line", 0)), json.dumps(profile),
                     json.dumps(flags), row.get("source_page"),
                     int(row.get("verified", 0))))
                n_loaded += 1
        families.append(fam["code"])

    con.execute("INSERT OR REPLACE INTO meta VALUES ('built_at',?)",
                (datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",))
    con.commit()
    n_ver = con.execute("SELECT COUNT(*) FROM schedule WHERE verified=1").fetchone()[0]
    con.close()
    return {"loaded": n_loaded, "verified": n_ver, "warnings": warnings,
            "families": families}


# --------------------------------------------------------------------------- #
# Query API (the planner primitives)
# --------------------------------------------------------------------------- #
def list_standards(db_path=None):
    con = _connect(db_path)
    rows = con.execute("SELECT * FROM dive_standard ORDER BY code").fetchall()
    con.close()
    return [dict(r) for r in rows]


def list_families(standard_code=None, db_path=None):
    con = _connect(db_path)
    q = "SELECT * FROM table_family"
    args = ()
    if standard_code:
        q += " WHERE standard_code=?"
        args = (standard_code,)
    rows = con.execute(q + " ORDER BY code", args).fetchall()
    con.close()
    return [dict(r) for r in rows]


def select_schedule(family_code, actual_depth_m, actual_bottom_time_min,
                    require_verified=False, db_path=None):
    """Apply the DCD selection rules (sec 4.2): choose the SMALLEST table depth
    >= actual depth, then the SMALLEST bottom time >= actual time within that
    depth. Returns the schedule dict with `profile` decoded, or None."""
    con = _connect(db_path)
    ver = "AND verified=1" if require_verified else ""
    depth_row = con.execute(
        f"SELECT MIN(table_depth_m) d FROM schedule WHERE family_code=? "
        f"AND table_depth_m>=? {ver}", (family_code, actual_depth_m)).fetchone()
    if not depth_row or depth_row["d"] is None:
        con.close()
        return None
    depth = depth_row["d"]
    row = con.execute(
        f"SELECT * FROM schedule WHERE family_code=? AND table_depth_m=? "
        f"AND bottom_time_min>=? {ver} ORDER BY bottom_time_min LIMIT 1",
        (family_code, depth, actual_bottom_time_min)).fetchone()
    con.close()
    if not row:
        return None
    out = dict(row)
    out["profile"] = json.loads(out.pop("profile_json") or "[]")
    return out


def get_profiles_at_depth(depth_m, family_codes, db_path=None):
    """For the comparison view: for each family, the full ordered list of
    (bottom_time -> profile) at the table depth covering `depth_m`."""
    result = {}
    con = _connect(db_path)
    for fc in family_codes:
        drow = con.execute(
            "SELECT MIN(table_depth_m) d FROM schedule WHERE family_code=? "
            "AND table_depth_m>=?", (fc, depth_m)).fetchone()
        if not drow or drow["d"] is None:
            result[fc] = []
            continue
        rows = con.execute(
            "SELECT bottom_time_min,tts_min,total_deco_min,otu,profile_json,verified "
            "FROM schedule WHERE family_code=? AND table_depth_m=? "
            "ORDER BY bottom_time_min", (fc, drow["d"])).fetchall()
        result[fc] = [{**dict(r), "profile": json.loads(r["profile_json"] or "[]")}
                      for r in rows]
    con.close()
    return result


def coverage(db_path=None):
    """QA summary: rows per family and how many are verified vs pending."""
    con = _connect(db_path)
    rows = con.execute(
        "SELECT family_code, COUNT(*) n, SUM(verified) v, "
        "MIN(table_depth_m) dmin, MAX(table_depth_m) dmax "
        "FROM schedule GROUP BY family_code ORDER BY family_code").fetchall()
    con.close()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# QA verifier — page-by-page sign-off against the source image
# --------------------------------------------------------------------------- #
def build_qa_report(out_path, image_url_for_page=None, db_path=None):
    """Emit a standalone HTML report. For each family, one section per source
    page: the stored grid on the left, the source page image on the right, so a
    supervisor can eyeball every cell and flip `verified`. `image_url_for_page`
    maps a source_page int -> an <img src>; if None, a filename hint is shown.

    Nothing here trusts the data — it exists precisely so a human confirms it.
    """
    con = _connect(db_path)
    fams = con.execute(
        "SELECT f.*, s.name std_name FROM table_family f "
        "JOIN dive_standard s ON s.code=f.standard_code ORDER BY f.code").fetchall()
    parts = ["<!doctype html><meta charset=utf-8><title>DCD QA</title>",
             "<style>body{font:14px system-ui;margin:24px;color:#1f2937}"
             "h2{border-bottom:2px solid #0f766e;padding-bottom:4px}"
             ".pg{display:flex;gap:20px;margin:18px 0;align-items:flex-start}"
             "table{border-collapse:collapse;font-size:12px}"
             "td,th{border:1px solid #cbd5e1;padding:2px 6px;text-align:center}"
             "th{background:#f1f5f9}.bad{background:#fee2e2}.pend{color:#b45309}"
             ".ok{color:#15803d}img{max-width:520px;border:1px solid #cbd5e1}"
             ".src{color:#64748b;font-size:12px}</style>"]
    for f in fams:
        parts.append(f"<h2>{f['code']} — {f['std_name']} "
                     f"<span class=src>({f['gas']}, {f['mode']}, "
                     f"RI {f['repeat_interval_h']}h)</span></h2>")
        pages = con.execute(
            "SELECT DISTINCT source_page, table_depth_m FROM schedule "
            "WHERE family_code=? ORDER BY table_depth_m", (f["code"],)).fetchall()
        for pg in pages:
            rows = con.execute(
                "SELECT * FROM schedule WHERE family_code=? AND table_depth_m=? "
                "ORDER BY bottom_time_min", (f["code"], pg["table_depth_m"])).fetchall()
            n = len(rows)
            nver = sum(r["verified"] for r in rows)
            status = (f"<span class=ok>&#10003; {nver}/{n} verified</span>"
                      if nver == n else
                      f"<span class=pend>&#9888; {nver}/{n} verified</span>")
            grid = ["<table><tr><th>btm</th><th>1st</th><th>profile "
                    "(deep&rarr;shallow)</th><th>&Sigma;stops</th>"
                    "<th>deco</th><th>OTU</th><th>flags</th></tr>"]
            for r in rows:
                prof = json.loads(r["profile_json"] or "[]")
                ptxt = " · ".join(f"{p['depth_m']:g}m:{p['minutes']:g}"
                                  f"{'' if p['gas']=='air' else '/'+p['gas']}"
                                  for p in prof) or "—"
                flags = json.loads(r["qa_flags"] or "[]") \
                    if "qa_flags" in r.keys() else []
                bad = "bad" if flags else ""
                grid.append(
                    f"<tr class={bad}><td>{r['bottom_time_min']}</td>"
                    f"<td>{r['till_first_stop_min'] or ''}</td><td>{ptxt}</td>"
                    f"<td>{r['sum_stops_min']:g}</td><td>{r['total_deco_min']}</td>"
                    f"<td>{r['otu']}</td><td>{', '.join(flags)}</td></tr>")
            grid.append("</table>")
            img = (f"<img src='{image_url_for_page(pg['source_page'])}'>"
                   if image_url_for_page and pg["source_page"] else
                   f"<div class=src>source: PDF p.{pg['source_page']}</div>")
            parts.append(
                f"<div class=src><b>{pg['table_depth_m']:g} m</b> "
                f"(PDF p.{pg['source_page']}) — {status}</div>"
                f"<div class=pg>{''.join(grid)}{img}</div>")
    con.close()
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))
    return out_path


# --------------------------------------------------------------------------- #
# Presentation reader — the DCD Tables page renders from a finalized JSON that
# lives on the /data volume (the table data is copyright, so it is never in git).
# This is the same data that feeds build_db() for the multi-standard comparison
# layer; for on-screen presentation we read it directly.
# --------------------------------------------------------------------------- #
TABLES_JSON = os.getenv("DCD_TABLES_JSON", "/data/tools/dcd/dcd_tables.json")
_TABLES_CACHE = {"mtime": None, "data": None}


def load_tables(path=None):
    """Return the presentation dict {meta, families:[...]} or None if not staged.
    Cached on file mtime so edits on the volume are picked up without a restart."""
    path = path or TABLES_JSON
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _TABLES_CACHE.update(mtime=None, data=None)
        return None
    if _TABLES_CACHE["mtime"] != mtime:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                _TABLES_CACHE.update(mtime=mtime, data=json.load(fh))
        except (OSError, ValueError):
            return None
    return _TABLES_CACHE["data"]


_KIND_LABEL = {"inwater": "In-water", "surfaceox": "Surface / Ox", "reference": "No-stop"}


def _short_label(f):
    """Compact one-line label for the family dropdown."""
    code, kind, ri = f["code"], f["kind"], f.get("ri")
    if kind == "reference":
        return f"{code}  \u00b7  no-stop limits"
    if kind == "inwater":
        gas = f.get("gas", "")
        g = "air" if gas == "air" else "nitrox " + gas.replace("nitrox_", "").replace("_", "/")
        desc = f"{g} in-water"
    else:
        desc = "surface O\u2082" if code in ("SOX15", "HSOX15") else "surface air (backup)"
    return f"{code}  \u00b7  {desc}" + (f"  \u00b7  RI {ri} h" if ri else "")


def ui_families(path=None):
    """List of families for the dropdown: [{code,label,kind}], data order preserved."""
    data = load_tables(path)
    if not data:
        return []
    return [{"code": f["code"], "label": _short_label(f), "kind": f["kind"]}
            for f in data["families"]]


def ui_family(code, path=None):
    """The full family dict for `code`, or None."""
    data = load_tables(path)
    if not data:
        return None
    for f in data["families"]:
        if f["code"] == code:
            return f
    return None


def ui_depths(code, path=None):
    """Sorted depths available for a family (empty for reference tables)."""
    f = ui_family(code, path)
    if not f or f["kind"] == "reference":
        return []
    return [d["depth"] for d in f["depths"]]


def ui_table(code, depth=None, path=None):
    """Return one renderable table: the family meta plus the selected depth block
    (or the whole reference table). Returns None if not found."""
    f = ui_family(code, path)
    if not f:
        return None
    if f["kind"] == "reference":
        return f
    blocks = f["depths"]
    block = None
    if depth is not None:
        block = next((d for d in blocks if d["depth"] == depth), None)
    if block is None and blocks:
        block = blocks[0]
    return {**f, "block": block}
