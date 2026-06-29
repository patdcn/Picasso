"""
Engineered-subsea engine for the 140 t crane.

Implements the MacGregor "engineered subsea lift" relationship:

    SWL(radius) = MaxDynCap(radius) / DAF              (DAF floored at 1.33)
    allowable   = SWL(radius) - depth * wire_weight    ("less weight of paid-out wire")

MaxDynCap (the maximum dynamic load capacity) is read from a single data file,
app/data/crane/maxdyncap.json, so the official MacGregor table can be dropped in
without touching any code. Until then the file holds an interim recovered
envelope (clearly flagged via the "source" field).
"""
import json
import os
import numpy as np

_DATA = os.path.join(os.path.dirname(__file__), "..", "data", "crane", "maxdyncap.json")
_CACHE = None
DAF_FLOOR = 1.33


def _load():
    global _CACHE
    if _CACHE is None:
        with open(_DATA) as f:
            _CACHE = json.load(f)
        _CACHE["daf_floor"] = float(_CACHE.get("daf_floor", DAF_FLOOR))
    return _CACHE


def is_interim():
    return str(_load().get("source", "")).upper().startswith("INTERIM")


def source_note():
    return _load().get("source", "")


def floor_daf(daf):
    """DAF can never be set below the engineered-subsea minimum."""
    fl = _load()["daf_floor"]
    try:
        return max(float(daf), fl)
    except (TypeError, ValueError):
        return fl


def wire_t_per_m(line="main", water="wet"):
    w = _load()["wire_kg_per_m"]
    return w[f"{line}_{water}"] / 1000.0


def _curve(line):
    d = _load().get(line)
    if not d:
        return None, None
    return np.asarray(d["radius"], float), np.asarray(d["maxdyncap"], float)


def maxdyncap_at(radius, line="main"):
    r, m = _curve(line)
    if r is None or radius < r.min() or radius > r.max():
        return None
    return float(np.interp(float(radius), r, m))


def swl_at_daf(radius, daf, line="main"):
    """SWL at the rope exit point = MaxDynCap / DAF (no wire subtraction)."""
    mc = maxdyncap_at(radius, line)
    if mc is None:
        return None
    return mc / floor_daf(daf)


def allowable(radius, daf, depth=0.0, line="main", water="wet"):
    """Allowable lift weight = SWL(daf) minus paid-out wire weight at depth."""
    swl = swl_at_daf(radius, daf, line)
    if swl is None:
        return None
    return swl - float(depth or 0.0) * wire_t_per_m(line, water)


def curve(daf, depth=0.0, line="main", water="wet"):
    """Arrays for plotting: radius, MaxDynCap, SWL@1.33, SWL@daf, allowable@daf+depth."""
    r, mc = _curve(line)
    if r is None:
        return None
    d = floor_daf(daf)
    swl133 = mc / DAF_FLOOR
    swld = mc / d
    allow = swld - float(depth or 0.0) * wire_t_per_m(line, water)
    return {"radius": r, "maxdyncap": mc, "swl133": swl133,
            "swl_daf": swld, "allowable": allow, "daf": d}


def max_radius_for_load(load_t, daf, depth=0.0, line="main", water="wet"):
    c = curve(daf, depth, line, water)
    if c is None:
        return None
    ok = c["allowable"] >= float(load_t)
    return float(c["radius"][ok].max()) if ok.any() else None


def daf_table(dafs=(1.33, 1.5, 1.8, 2.0), line="main"):
    """Booklet-style SWL table: standard radii x DAF columns (before wire)."""
    std = _load().get("standard_radii", [])
    rows = []
    for rr in std:
        mc = maxdyncap_at(rr, line)
        if mc is None:
            continue
        rows.append({"radius": rr, "maxdyncap": mc,
                     "swl": {f"{d}": mc / max(d, DAF_FLOOR) for d in dafs}})
    return rows, list(dafs)
