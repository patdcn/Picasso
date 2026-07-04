"""
US Navy decompression tables - presentation reader.

Reads a finalized JSON from the /data volume (USN_TABLES_JSON, default
/data/tools/usn/usn_tables.json), cached on file mtime. The table data is not
bundled in the repo; stage the JSON on the volume via Admin -> Data volume.

Structure:
    {"meta": {...}, "tables": [ {code, kind, title, rules, columns, rows, ...} ]}
Each table is a simple column/row grid; a table may set "group_from" (+ optional
"group_label") to render a spanning header over the columns from that index on
(used by the no-decompression table's repetitive-group block).
"""
import json
import os

TABLES_JSON = os.getenv("USN_TABLES_JSON", "/data/tools/usn/usn_tables.json")
_CACHE = {"mtime": None, "data": None}


def load_tables(path=None):
    path = path or TABLES_JSON
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _CACHE.update(mtime=None, data=None)
        return None
    if _CACHE["mtime"] != mtime:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                _CACHE.update(mtime=mtime, data=json.load(fh))
        except (OSError, ValueError):
            return None
    return _CACHE["data"]


def ui_tables(path=None):
    data = load_tables(path)
    if not data:
        return []
    return [{"code": t["code"], "label": t.get("title", t["code"])} for t in data["tables"]]


def ui_table(code, path=None):
    data = load_tables(path)
    if not data:
        return None
    for t in data["tables"]:
        if t["code"] == code:
            return t
    return None


def ui_depths(code, path=None):
    """Depths available for a per-depth (deco_blocks) table; [] otherwise."""
    t = ui_table(code, path)
    if not t or t.get("kind") != "deco_blocks":
        return []
    return [d["depth"] for d in t.get("depths", [])]


def rnt_groups(path=None):
    """Repetitive groups selectable for the air RNT calculator (A..O; Z excluded
    since a group-Z diver may not make a repetitive dive)."""
    data = load_tables(path)
    rnt = (data or {}).get("rnt_air") or {}
    groups = [g for g in rnt.get("groups", []) if g != "Z"]
    # present A..O ascending
    return sorted(groups)


def rnt_for(group, depth, path=None):
    """Residual nitrogen time (minutes) for repetitive group `group` at `depth`
    (fsw), from Table 9-8 (air dives). Returns an int, or None if not
    determinable from the table. Dives shallower than 30 fsw use the 30 fsw
    values (the table's "\u2020" rule)."""
    data = load_tables(path)
    rnt = (data or {}).get("rnt_air") or {}
    bg = rnt.get("by_group", {}).get(group)
    if not bg:
        return None
    avail = sorted(int(x) for x in bg.keys())
    if not avail:
        return None
    d = 30 if depth < 30 else depth
    deeper = [x for x in avail if x >= d]
    key = str(min(deeper) if deeper else max(avail))
    return bg.get(key)


def new_group_air(prev, si_min, path=None):
    """New repetitive group after a surface interval, from the credit half of
    Table 9-8 (air). `si_min` = surface interval in minutes. Returns the new
    group letter, or None when the interval is long enough that it is no longer
    a repetitive dive (the table's "*" rule). Returns `prev` unchanged if the
    group is unknown."""
    data = load_tables(path)
    sic = (data or {}).get("sic_air") or {}
    ordered = sic.get(prev)
    if not ordered:
        return prev
    for ng, upper in ordered:            # ascending upper bounds
        if si_min <= upper:
            return ng
    return None                          # beyond the last bound -> not a repetitive dive


def ui_block(code, depth=None, path=None):
    """For a deco_blocks table, return {'table':t,'block':selected-or-first}."""
    t = ui_table(code, path)
    if not t:
        return None
    if t.get("kind") != "deco_blocks":
        return {"table": t, "block": None}
    blocks = t.get("depths", [])
    blk = None
    if depth is not None:
        blk = next((d for d in blocks if d["depth"] == depth), None)
    if blk is None and blocks:
        blk = blocks[0]
    return {"table": t, "block": blk}
