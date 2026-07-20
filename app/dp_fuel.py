"""
DP fuel estimate — expected DG fuel consumption at the planner's assessed
condition, from the estimated electrical load (thrusters at the user's
environment via the propeller-law scaling, plus the selected DP consumers).

SFOC curve: piecewise-linear through the admin-editable anchor points at
25/50/75/85/100% MCR (Admin -> Parameters -> DP fuel). The seeded values are
TYPICAL medium-speed diesel figures — replace them with the engine-specific
shop-test / FAT curve. Below 25% the curve is held flat at the 25% value
(real SFOC deteriorates further there; a low-load warning is raised instead
of pretending to know the shape). Above 100% it is held at the 100% value.

Scope: DP electrical load only — no boilers, no transit propulsion, no
harbour generator. Rates in kg/h; daily totals in t/day and m3/day via the
fuel-density parameter.
"""
from app import params

_ANCHORS = (("dg_sfoc_25", 0.25), ("dg_sfoc_50", 0.50), ("dg_sfoc_75", 0.75),
            ("dg_sfoc_85", 0.85), ("dg_sfoc_100", 1.00))
LOW_LOAD_FRAC = 0.30


def _curve():
    return [(frac, float(params.get(key))) for key, frac in _ANCHORS]


def sfoc_g_per_kwh(load_frac):
    """Piecewise-linear SFOC [g/kWh] at the given per-DG load fraction."""
    pts = _curve()
    f = max(float(load_frac), 0.0)
    if f <= pts[0][0]:
        return pts[0][1]
    if f >= pts[-1][0]:
        return pts[-1][1]
    for (f0, s0), (f1, s1) in zip(pts, pts[1:]):
        if f0 <= f <= f1:
            return s0 + (s1 - s0) * (f - f0) / (f1 - f0)
    return pts[-1][1]


def estimate(power_panel):
    """Fuel estimate from a power_panel_est() result.

    Returns dict(buses=[{bus, n_dg, per_dg_kw, per_dg_frac, sfoc, kg_h}],
    total_kg_h, t_day, m3_day, warnings)."""
    buses, warnings = [], []
    total_kg_h = 0.0
    for b in power_panel["buses"]:
        if b["band"] == "offline" or not b["n_dg"]:
            continue
        frac = b["per_dg_frac"]
        sfoc = sfoc_g_per_kwh(frac)
        kg_h = b["per_dg_kw"] * sfoc / 1000.0 * b["n_dg"]
        total_kg_h += kg_h
        buses.append(dict(bus=b["bus"], n_dg=b["n_dg"],
                          per_dg_kw=b["per_dg_kw"], per_dg_frac=frac,
                          sfoc=sfoc, kg_h=kg_h))
        if frac < LOW_LOAD_FRAC:
            warnings.append(
                f'{b["bus"].upper()}: DGs at {frac*100:.0f}% load — below '
                f'{LOW_LOAD_FRAC*100:.0f}%, SFOC held at the 25% anchor; real '
                "consumption per kWh is worse and sustained low-load running "
                "has maintenance impact.")
    density = float(params.get("dg_fuel_density"))     # kg/l
    t_day = total_kg_h * 24.0 / 1000.0
    m3_day = (total_kg_h / density) * 24.0 / 1000.0 if density > 0 else 0.0
    return dict(buses=buses, total_kg_h=total_kg_h, t_day=t_day,
                m3_day=m3_day, warnings=warnings)


def estimate_uniform(total_kw, n_dg, dg_kw=2851.0):
    """Fuel estimate for a manually specified total electrical load split
    evenly over n_dg engines (rating dg_kw kWe each). Same result shape as
    estimate(), with a single pseudo-bus 'plant'."""
    n = max(int(n_dg or 1), 1)
    per = max(float(total_kw or 0.0), 0.0) / n
    frac = per / dg_kw if dg_kw > 0 else 0.0
    sfoc = sfoc_g_per_kwh(frac)
    kg_h = per * sfoc / 1000.0 * n
    warnings = []
    if 0.0 < frac < LOW_LOAD_FRAC:
        warnings.append(
            f"DGs at {frac*100:.0f}% load — below {LOW_LOAD_FRAC*100:.0f}%, "
            "SFOC held at the 25% anchor; real consumption per kWh is worse "
            "and sustained low-load running has maintenance impact.")
    if frac > 1.0:
        warnings.append(
            f"DGs at {frac*100:.0f}% load — above 100% MCR; not a sustainable "
            "operating point.")
    density = float(params.get("dg_fuel_density"))
    t_day = kg_h * 24.0 / 1000.0
    m3_day = (kg_h / density) * 24.0 / 1000.0 if density > 0 else 0.0
    return dict(buses=[dict(bus="plant", n_dg=n, per_dg_kw=per,
                            per_dg_frac=frac, sfoc=sfoc, kg_h=kg_h)],
                total_kg_h=kg_h, t_day=t_day, m3_day=m3_day, warnings=warnings)


MP_TOTAL_KW = 7000.0     # 2 x 3,500 kW main propellers — cube-law cap


def transit_estimate(speed_kn, n_dg, sea_margin_pct=15.0, distance_nm=None,
                     aux_kw=0.0):
    """Transit fuel from a cube-law propulsion model anchored at the
    admin-set service point (transit_prop_kw_service at
    transit_service_speed_kn, per the electrical load balance transit
    column), plus the transit auxiliary load, with a sea-margin factor on
    the propulsion share. Same result shape as estimate_uniform(), plus a
    'transit' dict with the propulsion breakdown, per-distance economy and
    (when a distance is given) voyage totals.

    Validated against the vessel's Oct 2025 fuel monitoring: the flagged
    transit days (11.4-12.0 m3/day) are reproduced at ~8 kn with zero sea
    margin, and port days (~5.0 m3/day) match the auxiliary-only base."""
    v = max(float(speed_kn or 0.0), 0.0)
    v_srv = float(params.get("transit_service_speed_kn"))
    p_srv = float(params.get("transit_prop_kw_service"))
    aux = max(float(aux_kw or 0.0), 0.0)
    margin = max(float(sea_margin_pct or 0.0), 0.0) / 100.0
    prop = p_srv * (v / v_srv) ** 3 if v_srv > 0 else 0.0
    prop = min(prop * (1.0 + margin), MP_TOTAL_KW)
    total = prop + aux
    est = estimate_uniform(total, n_dg)
    m3_day = est["m3_day"]
    tr = dict(prop_kw=prop, aux_kw=aux, total_kw=total, speed_kn=v,
              sea_margin_pct=margin * 100.0,
              m3_per_100nm=(m3_day / 24.0) * (100.0 / v) if v > 0.1 else None)
    if distance_nm and v > 0.1:
        hours = float(distance_nm) / v
        tr.update(distance_nm=float(distance_nm), hours=hours,
                  voyage_m3=m3_day / 24.0 * hours,
                  voyage_t=est["t_day"] / 24.0 * hours)
    est["transit"] = tr
    if prop >= MP_TOTAL_KW - 1e-6:
        est["warnings"] = list(est["warnings"]) + [
            "Propulsion demand capped at the installed 7,000 kW — the "
            "requested speed exceeds what the cube-law model considers "
            "attainable; result shown at full propulsion power."]
    return est
