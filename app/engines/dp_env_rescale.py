"""
DP environment-rescale engine — station-keeping capability at USER-CHOSEN
current, wind and Hs, derived from the Thrustmaster Appendix C force
decomposition, with estimated thruster power (and hence generator loading
including the DP consumer registry) at the user's actual condition.

Data source
-----------
Digitised Appendix C (wind/current/wave force components in surge, sway and
yaw per 10 deg incidence, at the capability limit), Appendix D (limiting wind
and the fixed analysis basis) and Appendix E (per-thruster kW at the limit)
for every case of both capability studies. Proprietary Thrustmaster data ->
lives ONLY on the /data volume, never in this repository:

    /data/tools/dp/dp_env_rescale.json    (override with env DP_RESCALE_JSON)

Upload via Admin -> Data volume files. Electrical metadata (bus map, DG
rating, PMS thresholds, DGs per mode) is read from the existing
dp_capability engine/volume file.

Method (and its limits — be explicit with users)
------------------------------------------------
At each incidence the study tabulates the wind, current and wave force
components separately, evaluated AT the capability limit. Scaling laws:
wind force ~ V^2 (coefficient calibrated from the tabulated wind force at the
tabulated limiting wind), current force ~ Vc^2, wave drift ~ Hs^2 at the
study's spectral shape (Tp is NOT rescaled). The thrust system is assumed
able to balance any environmental wrench whose |surge|, |sway| and |yaw|
components do not exceed the study-limit wrench components — a per-axis
("box") capability bound. This reproduces the published envelopes EXACTLY at
the study basis; away from the basis it is an engineering estimate whose
error grows with the wrench-direction shift, i.e. with how far current/Hs
deviate from the analysed values. The UI must surface this.

Power estimate: total-wrench utilisation s (weighted magnitude ratio vs the
study limit) drives a propeller-law scaling of the Appendix E loads:
kW_est = kW_AppE * s^1.5, exact at s = 1. Estimated figures are labelled as
such wherever shown.

Everything here is pure-python/deterministic so it unit-tests without Dash.
"""
import json
import math
import os

from app.engines import dp_capability as dp

DATA_JSON = os.getenv("DP_RESCALE_JSON", "/data/tools/dp/dp_env_rescale.json")

MS_TO_KN = 1.0 / 0.514444
_YAW_LEVER_M = 55.0     # normalisation lever for mixing kNm into the kN wrench
_EPS = 1e-9
_S_CLAMP = 1.25         # power-estimate clamp above the limit

# mode -> study key inside the rescale JSON (independent of whatever study
# keys the dp_capability volume file uses)
MODE_STUDY = {"2split": "ag2020", "3split": "wcfi2019"}

_cache = {"key": None, "data": None}


def _data():
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
            return None                      # never cache a miss
        _cache["key"], _cache["data"] = key, data
    return _cache["data"]


def available():
    return _data() is not None


def reload():
    _cache["key"], _cache["data"] = None, None


def provenance():
    d = _data()
    return list(d.get("provenance", [])) if d else []


def _study(mode_key):
    d = _data()
    return d["studies"][MODE_STUDY[mode_key]]


def cases(mode_key):
    return list(_study(mode_key)["cases"].keys())


def wcfdi_cases(mode_key):
    """Side-switchboard loss cases (worst case failure design intent), where
    the study analysed them. Mirrors dp_capability.wcfdi_cases."""
    cs = _study(mode_key)["cases"]
    return [c for c in ("Loss of Bus 1", "Loss of Bus 3") if c in cs]


def _case(mode_key, case_name):
    return _study(mode_key)["cases"][case_name]


def env_basis(mode_key, case_name):
    return _case(mode_key, case_name)["env"]


# ------------------------------------------------------------------ core solve
#
# Capability criterion (radial model): the environment is holdable while the
# weighted magnitude of its wrench (surge, sway, yaw/lever) does not exceed
# the magnitude of the study-limit wrench at that incidence:  M(V) <= M_lim.
# Exact at the study basis by construction; away from it the error grows with
# the wrench-direction shift, i.e. with how far current/Hs deviate from the
# analysed values. The limiting wind solves M(V*) = M_lim — the same scalar s
# = M/M_lim that drives the power estimate, so envelope and power are
# mutually consistent (s = 1 exactly on the rescaled envelope).
#
# An earlier per-axis ("box") bound was rejected: on axes where wind and
# current oppose, the near-cancelled axis total at the limit grossly
# understates real thrust authority and the computed limit collapses.

def _axis_terms(c, angle_key):
    """Per axis: (alpha, cur, wav, d) with wrench component
    t(u) = alpha*u + cur*rc + wav*rh, u = V^2, weighted by 1/d."""
    v_lim = c["wind_limit_ms"][angle_key]
    u_lim = v_lim * v_lim
    out = {}
    for axis, d in (("surge", 1.0), ("sway", 1.0), ("yaw", _YAW_LEVER_M)):
        r = c["forces"][axis][angle_key]
        alpha = (r["wind"] / u_lim) if u_lim > _EPS else 0.0
        out[axis] = (alpha, r["current"], r["wave"], d)
    return out


def _mag2(terms, u, rc, rh):
    s2 = 0.0
    for (alpha, cur, wav, d) in terms.values():
        t = alpha * u + cur * rc + wav * rh
        s2 += (t / d) ** 2
    return s2


def _limit_u(terms, m_lim2, rc, rh):
    """Largest u = V^2 >= 0 with M(u)^2 <= m_lim2. Returns (u, binding_axis).
    M(u)^2 is an upward parabola in u; the limit is its larger root."""
    A = B = C = 0.0
    for (alpha, cur, wav, d) in terms.values():
        beta = cur * rc + wav * rh
        A += (alpha / d) ** 2
        B += 2.0 * alpha * beta / (d * d)
        C += (beta / d) ** 2
    C -= m_lim2
    if A < _EPS:
        u = 0.0 if C > 0 else float("inf")
    else:
        disc = B * B - 4.0 * A * C
        u = 0.0 if disc < 0 else (-B + math.sqrt(disc)) / (2.0 * A)
    u = max(u, 0.0)
    # diagnostic: axis contributing most to the wrench magnitude at the limit
    binding, best = None, -1.0
    for axis, (alpha, cur, wav, d) in terms.items():
        contrib = abs((alpha * (0.0 if u == float("inf") else u)
                       + cur * rc + wav * rh) / d)
        if contrib > best:
            binding, best = axis, contrib
    return u, binding


def limit_wind_ms(mode_key, case_name, incidence_deg, current_ms, hs_m):
    """Rescaled limiting wind [m/s] at the incidence for the user's current
    and Hs, linearly interpolated between the 10-deg grid solutions (matching
    how the study envelopes themselves are interpolated)."""
    a = float(incidence_deg) % 360.0
    lo = int(a // 10) * 10
    hi = (lo + 10) % 360
    f = (a - lo) / 10.0
    v_lo, _ = _limit_at_grid(mode_key, case_name, lo, current_ms, hs_m)
    v_hi, _ = _limit_at_grid(mode_key, case_name, hi, current_ms, hs_m)
    return v_lo + f * (v_hi - v_lo)


def _limit_at_grid(mode_key, case_name, angle, current_ms, hs_m):
    c = _case(mode_key, case_name)
    b = c["env"]
    rc = (float(current_ms) / b["current_ms"]) ** 2 if b["current_ms"] > 0 else 0.0
    rh = (float(hs_m) / b["hs_m"]) ** 2 if b["hs_m"] > 0 else 0.0
    terms = _axis_terms(c, str(angle))
    u_lim = c["wind_limit_ms"][str(angle)] ** 2
    m_lim2 = _mag2(terms, u_lim, 1.0, 1.0)
    u, binding = _limit_u(terms, m_lim2, rc, rh)
    if u == float("inf"):
        u = u_lim  # degenerate: no wind sensitivity at this angle
    return math.sqrt(max(u, 0.0)), binding


def envelope(mode_key, case_name, current_ms, hs_m):
    """(angles, rescaled_limits_ms) closed 0..360 for plotting."""
    angs = list(range(0, 360, 10)) + [360]
    vals = [_limit_at_grid(mode_key, case_name, a % 360, current_ms, hs_m)[0]
            for a in angs]
    return angs, vals


def study_envelope(mode_key, case_name):
    """The published App D envelope (at the fixed study basis), for reference
    overlay."""
    tab = _case(mode_key, case_name)["wind_limit_ms"]
    angs = list(range(0, 360, 10)) + [360]
    return angs, [tab[str(a % 360)] for a in angs]


# ------------------------------------------------------------------ assessment

def assess(mode_key, case_name, heading_deg, wind_ms, wind_from_deg,
           current_ms, hs_m):
    inc = (float(wind_from_deg) - float(heading_deg)) % 360.0
    limit = limit_wind_ms(mode_key, case_name, inc, current_ms, hs_m)
    _v, binding = _limit_at_grid(mode_key, case_name, int(round(inc / 10.0) * 10) % 360,
                                 current_ms, hs_m)
    basis = env_basis(mode_key, case_name)
    util = float(wind_ms) / limit if limit > _EPS else float("inf")
    if util >= 1.0:
        status = "NO-GO"
    elif util >= 0.80:
        status = "MARGINAL"
    else:
        status = "GO"
    warnings = []
    rc = float(current_ms) / basis["current_ms"] if basis["current_ms"] > 0 else 0.0
    rh = float(hs_m) / basis["hs_m"] if basis["hs_m"] > 0 else 0.0
    if rc > 1.0 + 1e-9 or rh > 1.0 + 1e-9:
        warnings.append("Above the analysis basis "
                        f"(current {basis['current_ms']:.2f} m/s, Hs {basis['hs_m']:.1f} m) — "
                        "the envelope shown is a rescaled estimate, not a study result.")
    if rc > 1.5 or rh > 1.5:
        warnings.append("More than 1.5\u00d7 the analysis basis — the quadratic "
                        "scaling assumption is untested this far out; treat as "
                        "indicative only.")
    if abs(float(hs_m) - basis["hs_m"]) > 1e-9:
        warnings.append(f"Wave drift scaled as Hs\u00b2 at the study spectral shape "
                        f"(Tp {basis['tp_s']:.1f} s not rescaled).")
    return dict(incidence_deg=inc, limit_ms=limit, limit_kn=limit * MS_TO_KN,
                wind_ms=float(wind_ms), utilisation=util,
                margin_ms=limit - float(wind_ms), status=status, basis=basis,
                binding_axis=binding, warnings=warnings)


# ------------------------------------------------------------------ power

def _wrench_mag(c, angle_key, u, rc, rh):
    return math.sqrt(_mag2(_axis_terms(c, angle_key), u, rc, rh))


def thrust_utilisation(mode_key, case_name, incidence_deg, wind_ms,
                       current_ms, hs_m):
    """Scalar s = |env wrench at the user's condition| / |study-limit wrench|,
    at the nearest 10-deg grid angle. s = 1 at the study limit."""
    c = _case(mode_key, case_name)
    b = c["env"]
    ang = str(int(round(float(incidence_deg) / 10.0) * 10) % 360)
    rc = (float(current_ms) / b["current_ms"]) ** 2 if b["current_ms"] > 0 else 0.0
    rh = (float(hs_m) / b["hs_m"]) ** 2 if b["hs_m"] > 0 else 0.0
    m_user = _wrench_mag(c, ang, float(wind_ms) ** 2, rc, rh)
    m_lim = _wrench_mag(c, ang, c["wind_limit_ms"][ang] ** 2, 1.0, 1.0)
    return (m_user / m_lim) if m_lim > _EPS else 0.0


def thruster_loads_est(mode_key, case_name, incidence_deg, wind_ms,
                       current_ms, hs_m):
    """Estimated per-thruster kW at the USER'S condition: Appendix E loads
    (exact at the study limit) scaled by s^1.5 (propeller law), s clamped at
    1.25. Returns ({name: kW}, s)."""
    c = _case(mode_key, case_name)
    ang = str(int(round(float(incidence_deg) / 10.0) * 10) % 360)
    loads = c["thruster_loads_kw"][ang]
    names = dp.thruster_names(mode_key) if dp.available() else None
    if not names or len(names) != len(loads):
        names = [f"Thr {i + 1}" for i in range(len(loads))]
    s = thrust_utilisation(mode_key, case_name, incidence_deg, wind_ms,
                           current_ms, hs_m)
    f = min(max(s, 0.0), _S_CLAMP) ** 1.5
    return {n: kw * f for n, kw in zip(names, loads)}, s


def power_panel_est(mode_key, thr_kw, aux_kw=None):
    """Bus/DG rollup of ESTIMATED thruster loads + consumer aux, using the
    electrical metadata from the dp_capability volume file (bus map, DG
    rating, PMS thresholds, DGs per mode)."""
    el = dp.electrical()
    aux_kw = aux_kw or {}
    dg_kw = el["dg_nominal_kw"]
    warn, lim = el["pms_warning_frac"], el["pms_limit_frac"]
    dgs_per_bus = dp.modes()[mode_key]["dgs_per_bus"]
    buses = []
    for bus in ("bus1", "bus2", "bus3"):
        members = el["bus_map"][bus]["thrusters"]
        t_kw = sum(thr_kw.get(n, 0.0) for n in members)
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
    return dict(buses=buses, thresholds=(warn, lim), dg_nominal_kw=dg_kw)
