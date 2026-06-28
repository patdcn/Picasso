"""
Twin-bell vs single-bell DSV productivity & cost engine.

Pure Python, no Dash imports — ported verbatim from the original HTML calculator's
single()/twin()/compute() logic so the numbers match exactly. The Dash page calls
run_comparison(BellInputs) and renders the returned BellResult; this module can also
be unit-tested on its own.

Model in brief
--------------
A diving day is 24 h. Three scenarios are compared over the same fixed scope:
  S1  single bell, 9 in sat, 3 runs/day, with a lone-bellsman top-up
  S2  single bell, 12 in sat, 4 runs/day
  S3  twin bell,   12 in sat, 4 runs/day (continuous seabed handover while it lasts)

Single bell: each run owns DAY/runs of vessel time. Inside it a bell changeover,
then the pair's out-of-bell window (capped at Wmax), then for S1 a bellsman top-up.
On-the-job time = window minus down+back transit. The lone bellsman works at a
fraction (bell_eff) of a full pair's rate.

Twin bell: while the changeover fits inside the dive window the relief crew is on
the seabed before the working crew leaves — continuous, no transit loss. Once the
changeover exceeds the dive window the relief can't be ready in time and even the
twin loses time.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List

DAY = 24.0  # hours in a diving day


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
@dataclass
class BellInputs:
    W: float = 6.0        # max out-of-bell (dive window), hours
    C: float = 1.0        # bell changeover, hours
    T: float = 15.0       # bell<->job transit, MINUTES (one way)
    B: float = 1.0        # bellsman top-up window for S1, hours
    E: float = 0.5        # bellsman reduced work rate (fraction of a pair)
    R1: float = 150000.0  # day rate, single bell 9-man
    R2: float = 160000.0  # day rate, single bell 12-man
    R3: float = 190000.0  # day rate, twin bell 12-man
    dur: float = 50.0     # base-case duration (days) defining the fixed scope
    currency: str = "\u20ac"


# --------------------------------------------------------------------------- #
# Per-scenario result
# --------------------------------------------------------------------------- #
@dataclass
class Scenario:
    key: str
    name: str
    role: str
    vessel: str           # "single" | "twin"
    win: bool
    base: bool
    cfg: List[str]
    runs: int
    rate: float
    divers: int
    # operational outputs
    transit: float = 0.0
    pair_win: float = 0.0
    bell_win: float = 0.0
    pair_job: float = 0.0
    bs_job: float = 0.0
    on_job: float = 0.0
    on_job_eff: float = 0.0
    bottom: float = 0.0
    changeover: float = 0.0
    shortened: bool = False
    continuous: bool = False
    overhead: float = 0.0
    cph: float = 0.0       # cost per effective on-job hour
    # project projection (filled by run_comparison)
    days: float = 0.0
    cost: float = 0.0


@dataclass
class BellResult:
    inputs: BellInputs
    scenarios: List[Scenario]
    base_work_hours: float = 0.0          # fixed scope, on-job hours
    # hero / verdict figures
    twin_extra_subtitle: str = ""
    cph_save_pct: float = 0.0
    faster_pct: float = 0.0
    days_faster: float = 0.0
    twin_save: float = 0.0
    twin_cheaper: bool = True
    meta: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Core models (1:1 with the original JS)
# --------------------------------------------------------------------------- #
def _single(runs: int, Wmax: float, C: float, Tmin: float,
            bell_win: float, bell_eff: float) -> dict:
    transit = 2 * (Tmin / 60.0)                                  # down + back, hours
    pair_win = max(0.0, min(Wmax, DAY / runs - C - bell_win))
    pair_job = max(0.0, pair_win - transit)
    bs_job = max(0.0, bell_win - transit) if bell_win > 0 else 0.0
    return dict(
        vessel="single", transit=transit, pair_win=pair_win, bell_win=bell_win,
        pair_job=pair_job, bs_job=bs_job,
        on_job=runs * (pair_job + bs_job),
        on_job_eff=runs * (pair_job + bs_job * bell_eff),
        bottom=runs * (pair_win + bell_win),
        changeover=runs * C,
        shortened=pair_win < Wmax - 1e-9,
        continuous=False,
    )


def _twin(runs: int, Wmax: float, C: float, Tmin: float) -> dict:
    transit = 2 * (Tmin / 60.0)
    if C <= Wmax:
        oj = min(DAY, runs * Wmax)
        return dict(
            vessel="twin", transit=0.0, pair_win=Wmax, bell_win=0.0,
            pair_job=Wmax, bs_job=0.0, on_job=oj, on_job_eff=oj,
            bottom=oj, changeover=0.0, shortened=False, continuous=True,
        )
    cov = min(1.0, 2 * Wmax / (Wmax + C))      # best 2-bell coverage of the day
    gross = DAY * cov
    windows = gross / Wmax if Wmax > 0 else 0.0
    oj = max(0.0, gross - windows * transit)
    return dict(
        vessel="twin", transit=transit, pair_win=Wmax, bell_win=0.0,
        pair_job=max(0.0, Wmax - transit), bs_job=0.0,
        on_job=oj, on_job_eff=oj, bottom=gross, changeover=0.0,
        shortened=False, continuous=False,
    )


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def run_comparison(inp: BellInputs) -> BellResult:
    c1 = _single(3, inp.W, inp.C, inp.T, inp.B, inp.E)
    c2 = _single(4, inp.W, inp.C, inp.T, 0.0, inp.E)
    c3 = _twin(4, inp.W, inp.C, inp.T)

    defs = [
        dict(key="S1", name="Single bell \u00b7 3 runs", role="Base case",
             win=False, base=True, runs=3, rate=inp.R1, divers=9,
             cfg=["Single bell", "9 in saturation", "3 runs/day"], data=c1),
        dict(key="S2", name="Single bell \u00b7 4 runs", role="Alternative",
             win=False, base=False, runs=4, rate=inp.R2, divers=12,
             cfg=["Single bell", "12 in saturation", "4 runs/day"], data=c2),
        dict(key="S3", name="Twin bell \u00b7 4 runs", role="Full twin mode",
             win=True, base=False, runs=4, rate=inp.R3, divers=12,
             cfg=["Twin bell", "12 in saturation", "4 runs/day"], data=c3),
    ]

    scenarios: List[Scenario] = []
    for d in defs:
        data = d["data"]
        s = Scenario(
            key=d["key"], name=d["name"], role=d["role"], vessel=data["vessel"],
            win=d["win"], base=d["base"], cfg=d["cfg"], runs=d["runs"],
            rate=d["rate"], divers=d["divers"],
            transit=data["transit"], pair_win=data["pair_win"], bell_win=data["bell_win"],
            pair_job=data["pair_job"], bs_job=data["bs_job"], on_job=data["on_job"],
            on_job_eff=data["on_job_eff"], bottom=data["bottom"],
            changeover=data["changeover"], shortened=data["shortened"],
            continuous=data["continuous"],
        )
        s.overhead = DAY - s.on_job_eff
        s.cph = s.rate / s.on_job_eff if s.on_job_eff > 0 else 0.0
        scenarios.append(s)

    # ---- fixed-scope project projection ----
    base, mid, twin = scenarios[0], scenarios[1], scenarios[2]
    base_work = base.on_job_eff * inp.dur          # hours of on-job work in the scope
    for s in scenarios:
        s.days = base_work / s.on_job_eff if s.on_job_eff > 0 else 0.0
        s.cost = s.days * s.rate

    base_cost = base.cost
    days_faster = base.days - twin.days
    faster_pct = (days_faster / base.days * 100.0) if base.days > 0 else 0.0
    cph_save_pct = (1 - twin.cph / base.cph) * 100.0 if base.cph > 0 else 0.0
    twin_save = base_cost - twin.cost

    return BellResult(
        inputs=inp,
        scenarios=scenarios,
        base_work_hours=base_work,
        twin_extra_subtitle=f"vs {twin.on_job_eff:.1f}h",
        cph_save_pct=cph_save_pct,
        faster_pct=faster_pct,
        days_faster=days_faster,
        twin_save=twin_save,
        twin_cheaper=twin_save >= 0,
        meta=dict(base_cost=base_cost),
    )
