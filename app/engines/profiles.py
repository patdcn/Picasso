"""
Shared dive-profile leg builders + schedule enumeration.

Used by the DCD, US Navy and Compare pages so the profile logic lives in one
place. Legs feed app.engines.profile_chart. Selection helpers enumerate the
in-water and surface-decompression schedules (no-stop-limit / RNT tables are
excluded).
"""
from app.engines import dcd_tables as dcd
from app.engines import usn_tables as usn

MPM = 3.28084          # m/min -> ft/min for the (ft-based) rate model
DCD_STYLE_LABELS = {"ascent": "10 m/min ascent", "surfacing": "to surface",
                    "chamber": "chamber recompression"}


# --------------------------------------------------------------------------- #
# US Navy leg builders (depths in fsw)
# --------------------------------------------------------------------------- #
def _usn_gas(code):
    if "N2O2" in code:
        return "nitrox"
    if "HEO2" in code:
        return "heliox"
    return "air"


def _bt(r):
    try:
        return float(r.get("bt") or 0)
    except (TypeError, ValueError):
        return 0.0


def _usn_row_bt(rows, i):
    b = _bt(rows[i])
    if b:
        return b
    for j in range(i - 1, -1, -1):
        if rows[j].get("type") == "divider":
            break
        if rows[j].get("type") == "air":
            return _bt(rows[j])
    return 0.0


def _usn_inwater(bottom, sd, stops, gas, bt, descent_rate, o2_shallow=False):
    legs = [{"kind": "move", "to": bottom, "rate_fpm": descent_rate, "gas": gas,
             "style": "descent", "phase": "water"}]
    hold = max(bt - bottom / descent_rate, 0) if bt else 0
    legs.append({"kind": "hold", "depth": bottom, "min": hold, "gas": gas, "phase": "water"})
    last_gas = gas
    for d in sd:
        v = stops.get(str(d))
        if not v:
            continue
        g = "o2" if (o2_shallow and d <= 30) else gas
        legs.append({"kind": "move", "to": d, "rate_fpm": 30, "gas": g,
                     "style": "ascent", "phase": "water"})
        legs.append({"kind": "hold", "depth": d, "min": float(v), "gas": g, "phase": "water"})
        last_gas = g
    legs.append({"kind": "move", "to": 0, "rate_fpm": 30, "gas": last_gas,
                 "style": "ascent", "phase": "water"})
    return legs


def _usn_surdo2(bottom, sd, air_stops, periods, bt, descent_rate):
    legs = [{"kind": "move", "to": bottom, "rate_fpm": descent_rate, "gas": "air",
             "style": "descent", "phase": "water"},
            {"kind": "hold", "depth": bottom, "min": max(bt - bottom / descent_rate, 0) if bt else 0,
             "gas": "air", "phase": "water"}]
    cur = bottom
    for d in sd:
        if d >= bottom or d < 40:
            continue
        v = air_stops.get(str(d))
        if v:
            legs.append({"kind": "move", "to": d, "rate_fpm": 30, "gas": "air",
                         "style": "ascent", "phase": "water"})
            legs.append({"kind": "hold", "depth": d, "min": float(v), "gas": "air", "phase": "water"})
            cur = d
    if bottom >= 40 and cur > 40:
        legs.append({"kind": "move", "to": 40, "rate_fpm": 30, "gas": "air",
                     "style": "ascent", "phase": "water"})
        cur = 40
    legs.append({"kind": "move", "to": 0, "rate_fpm": 40, "gas": "air",
                 "style": "surfacing", "phase": "water"})
    legs.append({"kind": "hold", "depth": 0, "min": 2, "gas": "surface", "phase": "surface"})
    legs.append({"kind": "move", "to": 50, "rate_fpm": 100, "gas": "air",
                 "style": "chamber", "phase": "surface"})
    try:
        p = float(periods or 0)
    except (TypeError, ValueError):
        p = 0
    o2 = p * 30
    at50 = min(15, o2)
    at40 = max(o2 - at50, 0)
    legs.append({"kind": "hold", "depth": 50, "min": at50, "gas": "o2", "phase": "surface"})
    if at40 > 0:
        legs.append({"kind": "move", "to": 40, "rate_fpm": 30, "gas": "o2",
                     "style": "ascent", "phase": "surface"})
        legs.append({"kind": "hold", "depth": 40, "min": at40, "gas": "o2", "phase": "surface"})
    legs.append({"kind": "move", "to": 0, "rate_fpm": 30, "gas": "air",
                 "style": "ascent", "phase": "surface"})
    return legs


def usn_legs(t, block, i, mode="inwater"):
    rows = block["rows"]
    if i < 0 or i >= len(rows):
        return None
    row = rows[i]
    if row.get("type") == "divider":
        return None
    gas = _usn_gas(t["code"])
    bottom = block["depth"]
    sd = t["stop_depths"]
    is_air = t.get("variant") == "air"
    descent_rate = 75 if gas == "air" else 60
    if is_air and mode == "surdo2":
        air = row if row.get("type") == "air" else \
            (rows[i - 1] if i > 0 and rows[i - 1].get("type") == "air" else row)
        try:
            p = float(air.get("periods") or 0)
        except (TypeError, ValueError):
            p = 0
        if p > 0:
            return _usn_surdo2(bottom, sd, air.get("stops", {}), air.get("periods", ""),
                               _bt(air), descent_rate)
    o2_shallow = is_air and row.get("type") == "airo2"
    return _usn_inwater(bottom, sd, row.get("stops", {}), gas, _usn_row_bt(rows, i),
                        descent_rate, o2_shallow)


# --------------------------------------------------------------------------- #
# DCD leg builders (depths in metres)
# --------------------------------------------------------------------------- #
def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


# --- HSE DVIS5 (Diving Information Sheet No.5) exposure limits ---------------
# Maximum planned bottom time (surface to the start of decompression, minutes)
# for surface-supplied air / nitrox (EAD) diving, using the DVIS5 Table 1 column
# "Surface decompression and in-water decompression" -- the column that applies
# to every table currently populated (both in-water and SurDO2 schedules).
#
# The table intentionally stops at 51 m / 170 fsw: surface-supplied air is not
# permitted deeper under UK rules -- that regime becomes closed-bell /
# saturation -- so any deeper schedule is treated as outside the limits (the
# lookups return None, which the pages render as "no schedule selectable").
#
# Rows are (metres, fsw, limit_min). The metric and fsw keys are aligned exactly
# as tabulated, so DCD looks up by metres and USN by fsw with no unit-conversion
# drift (e.g. 50 fsw -> 180 min, matching the sheet, not 15.24 m rounded up).
DVIS5_SURD_LIMITS = [
    (12, 40, 240), (15, 50, 180), (18, 60, 120), (21, 70, 90),
    (24, 80, 70), (27, 90, 60), (30, 100, 50), (33, 110, 40),
    (36, 120, 35), (39, 130, 30), (42, 140, 30), (45, 150, 25),
    (48, 160, 25), (51, 170, 20),
]
DVIS5_MAX_M = 51
DVIS5_MAX_FSW = 170


def _dvis5_lookup(depth, key):
    """Applicable DVIS5 SurD/in-water bottom-time limit (min) for `depth`,
    matching on the metres column (key=0) or the fsw column (key=1). A depth
    that falls between tabulated rows rounds up to the next-deeper row (the
    conservative choice). Returns None when the depth is beyond the table."""
    d = _num(depth)
    if d is None:
        return None
    for row in DVIS5_SURD_LIMITS:
        if d <= row[key]:
            return row[2]
    return None


def dvis5_limit_m(depth_m):
    """DVIS5 SurD/in-water bottom-time limit (min) for a metric depth (DCD)."""
    return _dvis5_lookup(depth_m, 0)


def dvis5_limit_fsw(depth_fsw):
    """DVIS5 SurD/in-water bottom-time limit (min) for an fsw depth (USN)."""
    return _dvis5_lookup(depth_fsw, 1)


def dvis5_limit(value, depth):
    """DVIS5 limit (min) for a selectable-table value and its native depth
    (metres for DCD, fsw for USN). None => the depth is beyond the DVIS5 table
    (surface-supplied air not permitted; closed-bell / saturation regime)."""
    if not value or depth is None:
        return None
    return dvis5_limit_m(depth) if value.split("|")[0] == "dcd" else dvis5_limit_fsw(depth)


def dvis5_over(value, depth, bt):
    """True when bottom time `bt` (min) exceeds the DVIS5 limit for this
    table+depth, or when the depth is beyond the table altogether."""
    lim = dvis5_limit(value, depth)
    if lim is None:
        return True
    b = _num(bt)
    return b is not None and b > lim


def _dcd_inwater(family, block, row):
    bottom = block["depth"]
    gas = "nitrox" if (family.get("gas") or "").startswith("nitrox") else "air"
    bt = _num(row.get("bt")) or 0
    stops = row.get("stops", {})
    sd = family["stop_depths"]
    legs = [{"kind": "move", "to": bottom, "rate_fpm": 20 * MPM, "gas": gas,
             "style": "descent", "phase": "water"},
            {"kind": "hold", "depth": bottom, "min": max(bt - bottom / 20.0, 0),
             "gas": gas, "phase": "water"}]
    for d in sd:
        v = _num(stops.get(str(d)))
        if not v:
            continue
        legs.append({"kind": "move", "to": d, "rate_fpm": 10 * MPM, "gas": gas,
                     "style": "ascent", "phase": "water"})
        legs.append({"kind": "hold", "depth": d, "min": v, "gas": gas, "phase": "water"})
    legs.append({"kind": "move", "to": 0, "rate_fpm": 10 * MPM, "gas": gas,
                 "style": "ascent", "phase": "water"})
    return legs


def _dcd_surdo2(family, block, row):
    cols = family["columns"]
    di = family["deco_i"]
    bottom = block["depth"]
    bt = _num(row[0]) if row else 0
    legs = [{"kind": "move", "to": bottom, "rate_fpm": 20 * MPM, "gas": "air",
             "style": "descent", "phase": "water"},
            {"kind": "hold", "depth": bottom, "min": max((bt or 0) - bottom / 20.0, 0),
             "gas": "air", "phase": "water"}]
    iw = [(int(cols[i].split()[1]), _num(row[i]))
          for i in range(2, di) if cols[i].lower().startswith("iw") and i < len(row) and _num(row[i])]
    cur = bottom
    for d, mins in iw:
        legs.append({"kind": "move", "to": d, "rate_fpm": 10 * MPM, "gas": "air",
                     "style": "ascent", "phase": "water"})
        legs.append({"kind": "hold", "depth": d, "min": mins, "gas": "air", "phase": "water"})
        cur = d
    legs.append({"kind": "move", "to": 0, "rate_fpm": 10 * MPM, "gas": "air",
                 "style": "surfacing", "phase": "water"})
    legs.append({"kind": "hold", "depth": 0, "min": 1.5, "gas": "surface", "phase": "surface"})
    chamber = [(cols[i], _num(row[i]))
               for i in range(2, di) if not cols[i].lower().startswith("iw")
               and i < len(row) and _num(row[i]) is not None]
    if chamber:
        first_d = int(chamber[0][0].split()[1])
        legs.append({"kind": "move", "to": first_d, "rate_fpm": 30 * MPM, "gas": "air",
                     "style": "chamber", "phase": "surface"})
        cur = first_d
        for label, mins in chamber:
            gas = "o2" if label.lower().replace(" ", "").startswith("ox") else "air"
            d = int(label.split()[1])
            if d < cur:
                legs.append({"kind": "move", "to": d, "rate_fpm": 10 * MPM, "gas": "air",
                             "style": "ascent", "phase": "surface"})
                cur = d
            legs.append({"kind": "hold", "depth": d, "min": mins, "gas": gas, "phase": "surface"})
        legs.append({"kind": "move", "to": 0, "rate_fpm": 10 * MPM, "gas": "air",
                     "style": "ascent", "phase": "surface"})
    return legs


def dcd_legs(t, block, i):
    if not block:
        return None
    rows = block["rows"]
    if i < 0 or i >= len(rows):
        return None
    if t["kind"] == "inwater":
        return _dcd_inwater(t, block, rows[i])
    if t["kind"] == "surfaceox":
        return _dcd_surdo2(t, block, rows[i])
    return None


# --------------------------------------------------------------------------- #
# Selection helpers for the Compare page (value = "source|code|mode")
# --------------------------------------------------------------------------- #
def selectable_tables():
    out = []
    for f in dcd.ui_families():
        if f["kind"] == "inwater":
            out.append({"label": "DCD \u00b7 " + f["label"], "value": f"dcd|{f['code']}|",
                        "cat": "inwater"})
        elif f["kind"] == "surfaceox":
            out.append({"label": "DCD \u00b7 " + f["label"], "value": f"dcd|{f['code']}|",
                        "cat": "surdo2"})
    for tinfo in usn.ui_tables():
        t = usn.ui_table(tinfo["code"])
        if not t or t.get("kind") != "deco_blocks":
            continue
        if t.get("variant") == "air":
            out.append({"label": "USN \u00b7 " + tinfo["label"] + " (in-water)",
                        "value": f"usn|{t['code']}|inwater", "cat": "inwater"})
            out.append({"label": "USN \u00b7 " + tinfo["label"] + " (SurDO2)",
                        "value": f"usn|{t['code']}|surdo2", "cat": "surdo2"})
        else:
            out.append({"label": "USN \u00b7 " + tinfo["label"],
                        "value": f"usn|{t['code']}|inwater", "cat": "inwater"})
    return out


CATEGORY_LABEL = {"inwater": "in-water", "surdo2": "surface-decompression (SurDO2)"}


def table_category(value):
    for o in selectable_tables():
        if o["value"] == value:
            return o["cat"]
    return None


def depths(value):
    source, code, _mode = value.split("|")
    return dcd.ui_depths(code) if source == "dcd" else usn.ui_depths(code)


def rows(value, depth, apply_limit=False):
    """Selectable schedule rows for a table+depth. When apply_limit is True,
    rows whose bottom time exceeds the DVIS5 / IMCA limit (or every row, when the
    depth is beyond the table) are marked disabled so the Compare dropdowns grey
    them out and make them non-selectable."""
    source, code, _mode = value.split("|")
    lim = dvis5_limit(value, depth) if apply_limit else None

    def _disabled(bt):
        if not apply_limit:
            return False
        if lim is None:                     # depth beyond the DVIS5 table
            return True
        b = _num(bt)
        return b is not None and b > lim

    out = []
    if source == "dcd":
        t = dcd.ui_table(code, depth)
        blk = t.get("block") if t else None
        if not blk:
            return []
        for i, r in enumerate(blk["rows"]):
            if t["kind"] == "inwater":
                bt = r.get("bt")
                lbl = f"{bt} min" + ("  (backup)" if r.get("backup") else "")
            else:
                bt = r[0]
                lbl = f"{bt} min"
            opt = {"label": lbl, "value": i}
            if _disabled(bt):
                opt["disabled"] = True
            out.append(opt)
    else:
        res = usn.ui_block(code, depth)
        blk = res.get("block") if res else None
        if not blk:
            return []
        for i, r in enumerate(blk["rows"]):
            if r.get("type") in ("divider", "airo2"):
                continue
            if r.get("bt"):
                opt = {"label": f"{r['bt']} min", "value": i}
                if _disabled(r.get("bt")):
                    opt["disabled"] = True
                out.append(opt)
    return out


def legs_for(value, depth, row_index):
    """Return (legs, native_unit) for a selected schedule, or (None, unit)."""
    source, code, mode = value.split("|")
    if source == "dcd":
        t = dcd.ui_table(code, depth)
        return dcd_legs(t, t.get("block") if t else None, row_index), "m"
    t = usn.ui_table(code)
    res = usn.ui_block(code, depth)
    blk = res.get("block") if res else None
    if not t or not blk:
        return None, "fsw"
    return usn_legs(t, blk, row_index, mode or "inwater"), "fsw"


def run_minutes(legs, native_unit):
    """Total elapsed minutes for a leg list (for labelling)."""
    if not legs:
        return 0.0
    m_per_ft = 0.3048
    t = 0.0
    depth_ft = 0.0
    for leg in legs:
        if leg["kind"] == "move":
            to_ft = leg["to"] if native_unit == "fsw" else leg["to"] / m_per_ft
            rate = leg.get("rate_fpm") or 30
            t += abs(to_ft - depth_ft) / rate
            depth_ft = to_ft
        else:
            t += leg.get("min") or 0
    return t
