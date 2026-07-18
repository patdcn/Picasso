"""
DP capability engine — DSV Picasso station-keeping envelopes and power demand.

Data source
-----------
Digitised Appendix D (limiting wind speed per 10 deg incidence) and Appendix E
(per-thruster load in kW at the capability limit) tables from the two
Thrustmaster capability analyses, plus electrical metadata (bus mapping, DG
rating, PMS power-limit thresholds) taken from the DP FMEA and the 2026 Annual
DP Trials. The numeric data is proprietary (Thrustmaster of Texas, Inc.) and
therefore lives ONLY on the /data volume, never in this repository:

    /data/tools/dp/dp_capability.json     (override with env DP_DATA_JSON)

Upload via Admin -> Data volume files. If the file is absent every accessor
degrades gracefully and the page shows a "data not installed" notice.

Conventions
-----------
* Incidence angle: direction the environment comes FROM, relative to the bow,
  0 deg = head-on, positive clockwise (Thrustmaster convention). All wind, wave
  and current components are collinear in the underlying analyses.
* incidence = (wind_from_true - vessel_heading_true) mod 360.
* Wind speeds are 1-minute means at 10 m above water level (analysis basis).
* Envelope validity: the tabulated wind limits hold only at the study's fixed
  current speed / Hs / Tp. If the actual current or Hs EXCEEDS the basis the
  check reports OUTSIDE BASIS instead of silently passing.

Everything here is pure-python/deterministic so it unit-tests without Dash.
"""
import json
import math
import os

DATA_JSON = os.getenv("DP_DATA_JSON", "/data/tools/dp/dp_capability.json")

MS_TO_KN = 1.0 / 0.514444

# ---------------------------------------------------------------- data access
#
# The JSON is uploaded via the Admin page while the app is running, and the app
# runs under multiple gunicorn workers. The cache below therefore (a) NEVER
# caches a miss — a worker that started before the upload must pick the file up
# on its next request — and (b) keys on the file's mtime, so re-uploading a new
# revision takes effect on all workers without a redeploy.

_cache = {"key": None, "data": None}


def _data():
    """Load the volume JSON, cached per (path, mtime). Returns None when the
    file is absent or unreadable — and never caches that outcome."""
    try:
        mtime = os.path.getmtime(DATA_JSON)
    except OSError:
        return None
    key = (DATA_JSON, mtime)
    if _cache["key"] != key:
        try:
            with open(DATA_JSON, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None
        _cache["key"], _cache["data"] = key, data
    return _cache["data"]


def available():
    return _data() is not None


def reload():
    """Drop the cache (kept for admin convenience; mtime keying normally makes
    this unnecessary)."""
    _cache["key"], _cache["data"] = None, None


def modes():
    d = _data()
    if not d:
        return {}
    return d["modes"]


def mode_meta(mode_key):
    d = _data()
    m = d["modes"][mode_key]
    sm = d["study_meta"][m["study"]]
    return {**m, "study_title": sm["title"], "study_ref": sm["ref"],
            "study_note": sm.get("note", "")}


def cases(mode_key):
    d = _data()
    study = d["modes"][mode_key]["study"]
    return list(d["studies"][study]["cases"].keys())


def _case(mode_key, case_name):
    d = _data()
    study = d["modes"][mode_key]["study"]
    return d["studies"][study]["cases"][case_name]


def thruster_names(mode_key):
    d = _data()
    study = d["modes"][mode_key]["study"]
    return d["studies"][study]["thrusters"]


def env_basis(mode_key, case_name):
    """Fixed environmental basis of the study: current [m/s], Hs [m], Tp [s]."""
    return _case(mode_key, case_name)["env"]


def electrical():
    return _data()["electrical"]


def fmea_load_balance():
    return _data().get("fmea_load_balance", [])


def provenance():
    return _data().get("provenance", [])


# ---------------------------------------------------------------- geometry

def incidence_deg(wind_from_true_deg, heading_true_deg):
    """Angle of incidence of the environment relative to the bow, [0, 360)."""
    return (float(wind_from_true_deg) - float(heading_true_deg)) % 360.0


def _circ_interp(table_deg_to_val, angle_deg):
    """Linear interpolation on a 10-deg circular grid {'0':v0,...,'350':v35}."""
    a = float(angle_deg) % 360.0
    lo = int(a // 10) * 10
    hi = (lo + 10) % 360
    f = (a - lo) / 10.0
    v_lo = table_deg_to_val[str(lo)]
    v_hi = table_deg_to_val[str(hi)]
    if isinstance(v_lo, list):
        return [x + f * (y - x) for x, y in zip(v_lo, v_hi)]
    return v_lo + f * (v_hi - v_lo)


# ---------------------------------------------------------------- capability

def wind_limit_ms(mode_key, case_name, incidence):
    """Limiting 1-min wind speed [m/s] at the given incidence angle."""
    return _circ_interp(_case(mode_key, case_name)["wind_limit_ms"], incidence)


def envelope(mode_key, case_name):
    """(angles_deg, limits_ms) arrays for plotting, closed (0..360)."""
    tab = _case(mode_key, case_name)["wind_limit_ms"]
    angs = list(range(0, 360, 10)) + [360]
    vals = [tab[str(a % 360)] for a in angs]
    return angs, vals


def assess(mode_key, case_name, heading_deg, wind_ms, wind_from_deg,
           current_ms=None, hs_m=None):
    """Full operations check. Returns a dict with incidence, limit, utilisation,
    margin, status and basis-validity flags.

    Status:
      'GO'        utilisation < 0.80 and inside analysis basis
      'MARGINAL'  0.80 <= utilisation < 1.00 and inside basis
      'NO-GO'     utilisation >= 1.00
      'OUTSIDE BASIS'  actual current or Hs exceeds the study's fixed values
                       (the envelope is then not a valid bound)
    """
    inc = incidence_deg(wind_from_deg, heading_deg)
    limit = wind_limit_ms(mode_key, case_name, inc)
    basis = env_basis(mode_key, case_name)
    util = float(wind_ms) / limit if limit > 0 else float("inf")

    cur_ok = current_ms is None or float(current_ms) <= basis["current_ms"] + 1e-9
    hs_ok = hs_m is None or float(hs_m) <= basis["hs_m"] + 1e-9
    inside = cur_ok and hs_ok

    if not inside:
        status = "OUTSIDE BASIS"
    elif util >= 1.0:
        status = "NO-GO"
    elif util >= 0.80:
        status = "MARGINAL"
    else:
        status = "GO"

    return dict(incidence_deg=inc, limit_ms=limit, limit_kn=limit * MS_TO_KN,
                wind_ms=float(wind_ms), utilisation=util,
                margin_ms=limit - float(wind_ms),
                basis=basis, current_ok=cur_ok, hs_ok=hs_ok, inside_basis=inside,
                status=status)


# ---------------------------------------------------------------- power panel

def thruster_loads_at_limit(mode_key, case_name, incidence):
    """Per-thruster power [kW] at the capability limit (Appendix E),
    interpolated to the given incidence. Returns {name: kW} preserving the
    study's thruster order."""
    loads = _circ_interp(_case(mode_key, case_name)["thruster_loads_kw"], incidence)
    return dict(zip(thruster_names(mode_key), loads))


def power_panel(mode_key, case_name, incidence, aux_kw=None):
    """Bus- and engine-level power picture AT THE CAPABILITY LIMIT.

    aux_kw: optional {'bus1': kW, 'bus2': kW, 'bus3': kW} of non-thruster load
    added on top of the Appendix E thruster demand (default 0). Per-DG loading
    assumes equal load sharing across the DGs running on that bus.

    Returns {'thrusters': {...}, 'buses': [ {bus, thruster_kw, aux_kw, total_kw,
    n_dg, per_dg_kw, per_dg_frac, band} ... ], 'thresholds': (warn, limit)}.
    Band is 'ok' / 'warn' (>=80%) / 'limit' (>=85%) per the vessel's PMS
    power-limit function (2026 trials).
    """
    el = electrical()
    aux_kw = aux_kw or {}
    dg_kw = el["dg_nominal_kw"]
    warn, lim = el["pms_warning_frac"], el["pms_limit_frac"]
    dgs_per_bus = _data()["modes"][mode_key]["dgs_per_bus"]

    thr = thruster_loads_at_limit(mode_key, case_name, incidence)
    buses = []
    for bus in ("bus1", "bus2", "bus3"):
        members = el["bus_map"][bus]["thrusters"]
        t_kw = sum(thr.get(n, 0.0) for n in members)
        a_kw = float(aux_kw.get(bus, 0.0) or 0.0)
        n_dg = int(dgs_per_bus.get(bus, 0))
        total = t_kw + a_kw
        if n_dg > 0:
            per_dg = total / n_dg
            frac = per_dg / dg_kw
            band = "limit" if frac >= lim else ("warn" if frac >= warn else "ok")
        else:
            per_dg, frac, band = None, None, "offline"
        buses.append(dict(bus=bus, dgs=el["bus_map"][bus]["dgs"],
                          thrusters=members, thruster_kw=t_kw, aux_kw=a_kw,
                          total_kw=total, n_dg=n_dg, per_dg_kw=per_dg,
                          per_dg_frac=frac, band=band))
    return dict(thrusters=thr, buses=buses, thresholds=(warn, lim),
                dg_nominal_kw=dg_kw)

