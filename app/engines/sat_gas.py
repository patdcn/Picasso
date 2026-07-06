"""
Saturation gas calculations.

MINIMUM GAS (must-have-onboard reserve) follows the IMCA D050 "minimum
quantities of gas required offshore" framework: the bottom-mix and oxygen
volumes that must remain onboard once the system is at depth, below which diving
stops and decompression starts. Every coefficient is supplied by the caller
(from app.params) so the site-specific numbers stay visible and tunable rather
than buried here.

The secondary "job gas order" model is intentionally NOT used: per the DCN
decision the minimum gas figure is the minimum-quantities model only.

BLOWDOWN MIX reproduces the standard gas-mixing identities (single-gas blowdown
to establish a chamber PPO2, and a two-gas fill to make a target mix).

Conventions: depths in metres sea water (MSW); ATA = depth/10 + 1; O2 fractions
as plain percent numbers (e.g. 7.5 for 7.5%); PPO2 in millibar; volumes in m3
referenced to surface.
"""
import math


def ata(depth_m):
    """Absolute pressure (ATA) at a depth in MSW."""
    return depth_m / 10.0 + 1.0


# --------------------------------------------------------------------------- #
# Minimum gas — IMCA D050 minimum-quantities model
# --------------------------------------------------------------------------- #
def min_gas(
    storage_m,
    working_m,
    system_vol_m3,
    deco_hours,
    divers,
    *,
    bells=1,
    # Dive / bell gas (abort reserve to complete the held bell runs)
    dive_rmv_lpm=40.0,
    divers_per_bell=2.0,
    dive_run_min=480.0,
    dive_runs=2.0,
    # BIBS (chamber therapeutic breathing)
    bibs_lpm=20.0,
    bibs_hours=4.0,
    # Blowdown / line loss / therapeutic
    blowdowns=1.0,
    lineloss_m3_day=30.0,
    lineloss_cycles=2.0,
    therapeutic_lpm=20.0,
    therapeutic_min_per_diver=200.0,
    # Oxygen
    o2_metabolic=0.72,
    o2_deco_coeff=0.5,
    o2_ppo2_coeff=0.1,
    o2_reserve=90.0,
):
    """
    Return the minimum-gas breakdown for a saturation spread.

    At the default coefficients the components are:

        Dive gas    = W_ata * (rmv * divers_per_bell) * run_min /1000 * runs * bells
        BIBS        = S_ata * (bibs_lpm * 60 * bibs_hours)/1000 * divers
        Blowdown    = blowdowns * (storage_m/10) * system_vol
        Line loss   = lineloss_m3_day * deco_days * lineloss_cycles
        Therapeutic = S_ata * therapeutic_lpm * (therapeutic_min * divers)/1000
        Oxygen      = metabolic + deco_LN + ppo2 + reserve

    `bells` = 1 (single) or 2 (twin). Only the dive/bell gas scales with bell
    count (each bell carries its own abort reserve); BIBS, blowdown, line loss,
    therapeutic and oxygen are per-system and unaffected. The single-bell case
    reproduces the workbook.

    Result: {"mix": {...components}, "mix_total", "oxygen": {...}, "inputs": {...}}.
    Mix components are all bottom-mix / control gas (m3); oxygen is separate.
    """
    deco_days = deco_hours / 24.0
    s_ata = ata(storage_m)
    w_ata = ata(working_m)

    dive_gas = (
        w_ata * (dive_rmv_lpm * divers_per_bell) * dive_run_min / 1000.0
        * dive_runs * bells
    )
    bibs = s_ata * (bibs_lpm * 60.0 * bibs_hours) / 1000.0 * divers
    blowdown = blowdowns * (storage_m / 10.0) * system_vol_m3
    line_loss = lineloss_m3_day * deco_days * lineloss_cycles
    therapeutic = (
        s_ata * therapeutic_lpm * (therapeutic_min_per_diver * divers) / 1000.0
    )

    o2_metab = o2_metabolic * divers * deco_days
    o2_deco = o2_deco_coeff * system_vol_m3 * math.log(storage_m / 10.0 + 1.0)
    o2_ppo2 = o2_ppo2_coeff * system_vol_m3
    oxygen_total = o2_metab + o2_deco + o2_ppo2 + o2_reserve

    mix = {
        "dive_gas": dive_gas,
        "bibs": bibs,
        "blowdown": blowdown,
        "line_loss": line_loss,
        "therapeutic": therapeutic,
    }
    return {
        "mix": mix,
        "mix_total": sum(mix.values()),
        "oxygen": {
            "metabolic": o2_metab,
            "deco": o2_deco,
            "ppo2": o2_ppo2,
            "reserve": o2_reserve,
            "total": oxygen_total,
        },
        "inputs": {
            "storage_m": storage_m,
            "working_m": working_m,
            "system_vol_m3": system_vol_m3,
            "deco_hours": deco_hours,
            "deco_days": deco_days,
            "divers": divers,
            "bells": bells,
        },
    }


# Human-readable labels + one-line rationale for each mix component (for the UI).
MIX_LABELS = {
    "dive_gas": ("Dive / bell gas", "Bell-run abort reserve at working depth"),
    "bibs": ("BIBS gas", "Chamber therapeutic breathing, per diver"),
    "blowdown": ("Blowdown", "One full-system blowdown at storage depth"),
    "line_loss": ("Line loss", "Daily loss over the decompression"),
    "therapeutic": ("Therapeutic gas", "Recompression treatment reserve"),
}


# --------------------------------------------------------------------------- #
# Blowdown gas mix
# --------------------------------------------------------------------------- #
def blowdown_on_rich(target_ppo2_mb, chamber_depth_m, o2_rich_pct, o2_lean_pct,
                     surface_ppo2_mb=210.0):
    """
    Depth (MSW) to blow down on the RICH gas before switching to the LEAN gas,
    to establish `target_ppo2_mb` at `chamber_depth_m`.

    Workbook `General Calculations` B3 / ISS `Gas Mixing`:
        MSW_on_rich = ((PPO2 - surface) - depth*O2_lean) / (O2_rich - O2_lean)

    The -surface term removes the ~0.21 bar air PPO2 baseline. Returns None if
    the two gases have the same O2 fraction (no solution).
    """
    denom = o2_rich_pct - o2_lean_pct
    if denom == 0:
        return None
    return ((target_ppo2_mb - surface_ppo2_mb) - chamber_depth_m * o2_lean_pct) / denom


def two_gas_fill(p_total, o2_lean_pct, o2_rich_pct, o2_target_pct):
    """
    Make a target mix by charging RICH gas then topping with LEAN gas to a total
    pressure. Workbook `General Calculations` B38.

        bar_rich = (O2_target - O2_lean) * P_total / (O2_rich - O2_lean)
        bar_lean = P_total - bar_rich

    Returns (bar_rich, bar_lean), or (None, None) if the gases have equal O2.
    """
    denom = o2_rich_pct - o2_lean_pct
    if denom == 0:
        return None, None
    bar_rich = (o2_target_pct - o2_lean_pct) * p_total / denom
    return bar_rich, p_total - bar_rich
