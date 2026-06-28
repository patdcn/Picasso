"""
Single bell vs single-twin (spare-bell) DSV reliability & cost engine.

Pure Python, no Dash imports. Ported verbatim from the single-vs-single-twin HTML
calculator. Reuses the shared single-bell dive model from app.engines.bell so the
per-day diving numbers stay identical across tools.

Model in brief
--------------
Four scenarios, paired by crew size:
  S1  single bell, 9 in sat, 3 runs/day  -> breaks down (loses bd h/week)
  S2  single bell, 12 in sat, 4 runs/day -> breaks down
  S4  single-twin, 9 in sat, 3 runs/day  -> spare bell, no idle time
  S5  single-twin, 12 in sat, 4 runs/day -> spare bell, no idle time

The single-twin dives exactly the same day as its single-bell counterpart — the
difference is purely reliability. A true single bell loses `bd` hours per week to
breakdown, which reduces its effective on-job hours per day (bd/7) and stretches the
project. The single-twin carries a second bell on standby, so a breakdown is a bell
swap rather than idle time, at a modest day-rate premium. The question the tool
answers: does that premium pay for itself?
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List

from app.engines.bell import _single, DAY


@dataclass
class SpareBellInputs:
    W: float = 6.0
    C: float = 1.0
    T: float = 15.0        # transit, minutes one way
    B: float = 1.0
    E: float = 0.5
    R1: float = 150000.0   # single bell 9-man
    R2: float = 160000.0   # single bell 12-man
    R4: float = 160000.0   # single-twin 9-man
    R5: float = 170000.0   # single-twin 12-man
    bd: float = 10.0       # breakdown downtime, hours per week (single bell only)
    dur: float = 50.0      # base-case duration (days) -> fixed scope
    currency: str = "\u20ac"


@dataclass
class SpareScenario:
    key: str
    name: str
    role: str
    vessel: str
    win: bool          # is this a single-twin (spare-bell) scenario
    breaks: bool       # does it suffer breakdown downtime
    spare: bool
    crew: int
    runs: int
    rate: float
    cfg: List[str]
    # dive outputs
    transit: float = 0.0
    pair_win: float = 0.0
    bell_win: float = 0.0
    pair_job: float = 0.0
    bs_job: float = 0.0
    on_job: float = 0.0
    on_job_eff: float = 0.0
    shortened: bool = False
    overhead: float = 0.0
    cph: float = 0.0


@dataclass
class SpareRow:
    """A project-projection row (per scenario), accounting for breakdown."""
    name: str
    role: str
    rate: float
    nominal: float       # nominal on-job h/day before breakdown
    breaks: bool
    stwin: bool
    eff: float           # effective h/day after breakdown loss
    days: float
    cost: float
    idle: float          # extra idle days vs no-breakdown


@dataclass
class SparePair:
    id: str
    single: SpareRow
    stwin: SpareRow


@dataclass
class SpareBellResult:
    inputs: SpareBellInputs
    scenarios: List[SpareScenario]
    base_work_hours: float
    pairs: List[SparePair]
    save9: float
    save12: float
    both_win: bool
    idle_min: float
    idle_max: float
    meta: dict = field(default_factory=dict)


def run_comparison(inp: SpareBellInputs) -> SpareBellResult:
    # single-twins dive the same as the single bells
    c9 = _single(3, inp.W, inp.C, inp.T, inp.B, inp.E)
    c12 = _single(4, inp.W, inp.C, inp.T, 0.0, inp.E)

    defs = [
        dict(key="S1", name="Single bell \u00b7 9 diver", role="Scenario 1 \u00b7 breaks down",
             win=False, breaks=True, spare=False, crew=9, runs=3, rate=inp.R1,
             cfg=["Single bell", "9 in saturation", "3 runs/day"], data=c9),
        dict(key="S2", name="Single bell \u00b7 12 diver", role="Scenario 2 \u00b7 breaks down",
             win=False, breaks=True, spare=False, crew=12, runs=4, rate=inp.R2,
             cfg=["Single bell", "12 in saturation", "4 runs/day"], data=c12),
        dict(key="S4", name="Single-twin \u00b7 9 diver", role="Scenario 4 \u00b7 spare bell",
             win=True, breaks=False, spare=True, crew=9, runs=3, rate=inp.R4,
             cfg=["Single-twin", "9 in saturation", "3 runs/day"], data=c9),
        dict(key="S5", name="Single-twin \u00b7 12 diver", role="Scenario 5 \u00b7 spare bell",
             win=True, breaks=False, spare=True, crew=12, runs=4, rate=inp.R5,
             cfg=["Single-twin", "12 in saturation", "4 runs/day"], data=c12),
    ]

    scenarios: List[SpareScenario] = []
    for d in defs:
        data = d["data"]
        s = SpareScenario(
            key=d["key"], name=d["name"], role=d["role"], vessel=data["vessel"],
            win=d["win"], breaks=d["breaks"], spare=d["spare"], crew=d["crew"],
            runs=d["runs"], rate=d["rate"], cfg=d["cfg"],
            transit=data["transit"], pair_win=data["pair_win"], bell_win=data["bell_win"],
            pair_job=data["pair_job"], bs_job=data["bs_job"], on_job=data["on_job"],
            on_job_eff=data["on_job_eff"], shortened=data["shortened"],
        )
        s.overhead = DAY - s.on_job_eff
        s.cph = s.rate / s.on_job_eff if s.on_job_eff > 0 else 0.0
        scenarios.append(s)

    base, mid = scenarios[0], scenarios[1]
    work = base.on_job_eff * inp.dur     # fixed scope, on-job hours
    bd_per_day = inp.bd / 7.0

    def mk_row(name, role, rate, nominal, breaks, stwin) -> SpareRow:
        eff = max(0.0001, nominal - bd_per_day) if breaks else nominal
        days = work / eff
        idle = days - work / nominal
        return SpareRow(name=name, role=role, rate=rate, nominal=nominal, breaks=breaks,
                        stwin=stwin, eff=eff, days=days, cost=days * rate, idle=idle)

    pairs = [
        SparePair("pair9",
                  mk_row("Single bell \u00b7 9 diver", "3 runs \u00b7 breaks down", inp.R1, base.on_job_eff, True, False),
                  mk_row("Single-twin \u00b7 9 diver", "3 runs \u00b7 spare bell", inp.R4, base.on_job_eff, False, True)),
        SparePair("pair12",
                  mk_row("Single bell \u00b7 12 diver", "4 runs \u00b7 breaks down", inp.R2, mid.on_job_eff, True, False),
                  mk_row("Single-twin \u00b7 12 diver", "4 runs \u00b7 spare bell", inp.R5, mid.on_job_eff, False, True)),
    ]

    save9 = pairs[0].single.cost - pairs[0].stwin.cost
    save12 = pairs[1].single.cost - pairs[1].stwin.cost
    idle_a, idle_b = pairs[0].single.idle, pairs[1].single.idle

    return SpareBellResult(
        inputs=inp,
        scenarios=scenarios,
        base_work_hours=work,
        pairs=pairs,
        save9=save9,
        save12=save12,
        both_win=(save9 >= 0 and save12 >= 0),
        idle_min=min(idle_a, idle_b),
        idle_max=max(idle_a, idle_b),
    )
