"""
Saturation gas consumption, blowdown mix and cost.

Ported from the DCN Picasso gas workbook (`Gascalc` sheet). Where the minimum-
gas engine (sat_gas.py) gives the abort reserve that must remain onboard, this
engine estimates what a job actually *consumes*: the initial system blowdown
mix (rich + lean volumes held to a chamber PPO2 during blowdown), daily chamber
and diver losses, metabolic oxygen in operations and in decompression, sodasorb,
bell pressurisation and diver lockout gas, a reclaim-adjusted loss per lock/
trunk, and the resulting gas cost.

Every rate, efficiency and unit cost is a caller-supplied argument (from
app.params) so the assumptions stay visible and tunable. Volumes and per-job
figures are passed in from the page.

Pressures in bar absolute (depth/10 + surface); volumes in m3 at surface;
breathing rates in L/min; O2 fractions as fractions (0.20 = 20%).

The blowdown / loss / deco-oxygen volume `v_sys` is the floodable living volume.
Per the DCN decision the bells ARE included in it (the workbook originally summed
the chambers only); the page seeds v_sys with the bells added.
"""
import math


def deco_estimate_usn7a(storage_m):
    """Indicative deco time [h] from storage depth, per the workbook's USN 7a
    piecewise estimate (surface-decompression-style), scaled 24/16. Used only to
    seed a sensible default; the page lets the user type the value actually used.
    """
    fsw = storage_m * 3.28084
    if fsw > 200:
        base = (fsw - 200) / 6 + 100 / 5 + 50 / 4 + 20
    elif fsw > 100:
        base = (fsw - 100) / 5 + 50 / 4 + 20
    elif fsw > 50:
        base = (fsw - 50) / 4 + 20
    elif fsw > 30:
        base = (fsw - 30) / 3 + 20
    else:
        base = fsw / 3 * 2
    return math.ceil(base) * (24 / 16)


def _reclaim_loss(p1, p2, vol, n_per_day, reclaim, last_bar_lost, surface_bar):
    """Generic reclaim-adjusted daily loss for a lock/trunk depressurisation.

        (P1 - P2 - surface*LBL) * Vol * N * (1 - reclaim) + surface*LBL * Vol * N

    The first term is the reclaimed blow-off; the second returns the last
    (un-reclaimable) bar when it is vented rather than recovered.
    """
    lbl = 1.0 if last_bar_lost else 0.0
    return ((p1 - p2 - surface_bar * lbl) * vol * n_per_day * (1 - reclaim)
            + surface_bar * lbl * vol * n_per_day)


def consumption(
    *,
    # --- depths / job ---
    storage_m, working_m, surface_bar=1.01325,
    occupants=9, working_divers=2, bellman=1,
    bell_runs_day=3, lockout_hours=6, job_days=1, deco_hours=None,
    # --- lock / bell activity (events per day) ---
    medlock_uses=20, entrylock_uses=1, eqlock_uses=3,
    wetpot_depress=0, bell_depress=0.1,
    # --- volumes (m3) ---
    v_sys=215.65, v_bell=6.49, v_belltrunk=0.25132741228718347,
    v_wetpot=26.0, v_entry=7.4, v_medlock=0.035, v_eqlock=0.4,
    # --- consumption rates ---
    o2_resting=0.8, o2_moderate=2.5, br_working=40.0, br_bellman=25.0,
    sodasorb_per_person_day=0.36,
    # --- losses / reclaim (single measured reclaim, applied everywhere) ---
    loss_chamber=0.005, loss_diver=0.01, reclaim=0.90,
    # --- gas mix ---
    blowdown_ppo2=0.4, mix_a_o2=0.20, mix_b_o2=0.02, deco_ppo2=0.5,
    # --- unit costs (per m3) ---
    cost_heliox=25.0, cost_o2=6.0, cost_sodasorb=11.0,
):
    if deco_hours is None:
        deco_hours = deco_estimate_usn7a(storage_m)

    p_storage = storage_m / 10.0 + surface_bar
    p_working = working_m / 10.0 + surface_bar
    dp_storage = p_storage - surface_bar
    non_lockout_h = 24 - bell_runs_day * lockout_hours

    # ---- initial system blowdown mix (held at blowdown_ppo2 during blowdown) ----
    d = mix_a_o2 - mix_b_o2
    mix_a_vol = (blowdown_ppo2 * v_sys) / d * math.log(p_storage / surface_bar) \
        - v_sys * dp_storage * mix_b_o2 / d
    mix_b_vol = v_sys * dp_storage - mix_a_vol
    blowdown = {"mix_a": mix_a_vol, "mix_b": mix_b_vol, "total": mix_a_vol + mix_b_vol}

    # ---- operational chamber losses (heliox) ----
    chamber_loss_day = p_storage * v_sys * loss_chamber

    # ---- metabolic oxygen: operations ----
    # In-chamber resting metabolic O2, counted once per occupant over the
    # non-lockout window. (The original workbook added the non-diving occupants
    # a second time here; that duplicate is removed.) Working divers' in-water
    # consumption is the o2_ops_working term below.
    o2_ops_chamber = occupants * non_lockout_h * 60 * o2_resting / 1000.0
    o2_ops_working = (working_divers + bellman) * o2_moderate * 60 * lockout_hours * bell_runs_day / 1000.0
    o2_ops_day = o2_ops_chamber + o2_ops_working

    # ---- metabolic oxygen: decompression ----
    o2_deco_chamber = math.log(p_storage) * deco_ppo2 * v_sys
    o2_deco_metabolic = occupants * deco_hours * (o2_resting * 60 / 1000.0)
    o2_deco_total = o2_deco_chamber + o2_deco_metabolic

    # ---- sodasorb (empirical per-occupant-day rate, calibrated to Picasso
    # daily-usage actuals ~3 units/day for 9 occupants) ----
    sodasorb_day = sodasorb_per_person_day * occupants

    # ---- bell operations ----
    bell_pressurisation = bell_runs_day * v_bell * (working_m - storage_m) / 10.0
    lockout_gas = br_working * 60 * working_divers * lockout_hours * bell_runs_day * p_working / 1000.0
    lockout_loss = lockout_gas * loss_diver

    # ---- reclaim-adjusted daily losses (heliox) ----
    reclaim_rows = {
        "medical_lock": _reclaim_loss(p_storage, 0, v_medlock, medlock_uses,
                                      reclaim, True, surface_bar),
        "entry_lock": _reclaim_loss(p_storage, 0, v_entry, entrylock_uses,
                                    reclaim, False, surface_bar),
        "diver_lockouts": lockout_gas * (1 - reclaim),
        "bell_blowdown": _reclaim_loss(p_storage, 0, v_bell, bell_depress,
                                       reclaim, False, surface_bar),
        "bell_work_to_storage": _reclaim_loss(p_working, p_storage, v_bell, bell_runs_day,
                                              reclaim, False, surface_bar),
        "bell_trunk": _reclaim_loss(p_storage, 0, v_belltrunk, bell_runs_day,
                                    reclaim, True, surface_bar),
        "wetpot": _reclaim_loss(p_storage, 0, v_wetpot, wetpot_depress,
                                reclaim, False, surface_bar),
        "equipment_trunk": _reclaim_loss(p_storage, 0, v_eqlock, eqlock_uses,
                                         reclaim, False, surface_bar),
    }
    reclaim_total = sum(reclaim_rows.values())

    # ---- cost ----
    # Daily operational cost (chamber/diver losses + reclaim losses + O2 + soda),
    # plus the one-off initial blowdown, combined into a project total.
    cost_heliox_losses = (chamber_loss_day + lockout_loss) * cost_heliox
    cost_heliox_consumption = reclaim_total * cost_heliox
    cost_o2_metabolic = o2_ops_day * cost_o2
    cost_sodasorb = sodasorb_day * cost_sodasorb
    cost_daily = cost_heliox_losses + cost_heliox_consumption + cost_o2_metabolic + cost_sodasorb
    cost_blowdown = blowdown["total"] * cost_heliox
    cost_project = cost_daily * job_days + cost_blowdown

    return {
        "inputs": {"p_storage": p_storage, "p_working": p_working,
                   "deco_hours": deco_hours, "non_lockout_h": non_lockout_h,
                   "v_sys": v_sys},
        "blowdown": blowdown,
        "daily": {
            "chamber_loss": chamber_loss_day,
            "o2_ops": o2_ops_day,
            "sodasorb": sodasorb_day,
            "bell_pressurisation": bell_pressurisation,
            "lockout_gas": lockout_gas,
            "lockout_loss": lockout_loss,
            "reclaim_rows": reclaim_rows,
            "reclaim_total": reclaim_total,
        },
        "deco": {"chamber": o2_deco_chamber, "metabolic": o2_deco_metabolic,
                 "total": o2_deco_total},
        "project": {
            "chamber_loss": chamber_loss_day * job_days,
            "o2_ops": o2_ops_day * job_days,
        },
        "cost": {
            "heliox_losses": cost_heliox_losses,
            "heliox_consumption": cost_heliox_consumption,
            "o2_metabolic": cost_o2_metabolic,
            "sodasorb": cost_sodasorb,
            "daily_total": cost_daily,
            "blowdown": cost_blowdown,
            "project_total": cost_project,
        },
    }


# Labels for the reclaim-loss rows (for the UI).
RECLAIM_LABELS = {
    "medical_lock": "Medical lock",
    "entry_lock": "Entry lock",
    "diver_lockouts": "Diver lockouts",
    "bell_blowdown": "Bell blowdown (storage \u2192 amb)",
    "bell_work_to_storage": "Bell (working \u2192 storage)",
    "bell_trunk": "Bell trunk",
    "wetpot": "Wet-pot / transfer lock",
    "equipment_trunk": "Equipment trunk",
}
