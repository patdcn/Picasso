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
