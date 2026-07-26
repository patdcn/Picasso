"""
Workability engine.

Consumes a multi-year point series (from fetch_point or synth_point) and a
scope definition, and returns a duration/feasibility distribution tested
against the client's fixed execution window.

Key method: each Monte-Carlo realisation is a REAL historical year's version of
the same calendar window (block resampling), so storm persistence is inherited
from the data rather than modelled. Years are drawn with recency weights, so a
non-stationary climate tilts the sample toward recent conditions.

Two scope modes:
  single   — one continuous D-hour window (atomic lift). Reports the probability
             such a window exists inside the client period and the wait to it.
  campaign — an ordered list of task TYPES {duration, off, limits, resetup},
             executed in sequence. A weather break is standby-nearby waiting
             (no remob). An interrupted unit restarts and pays its re-setup
             cost on the retry. Reports elapsed-duration P50/P80/P90 and whether
             it fits the client window.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import numpy as np
import pandas as pd

from .climatology import ClimatologyConfig, recency_weights, execution_months


# ---------------------------------------------------------------------------
# scope definition
# ---------------------------------------------------------------------------
@dataclass
class TaskType:
    name: str
    duration_h: int          # hours per unit
    off: int                 # number of units of this type
    hs_max: float            # m
    wind_max: float          # kn
    cur_surf_max: float      # kn  (vessel / DP limit)
    cur_bottom_max: float    # kn  (diver limit)
    resetup_h: float = 0.0   # hours added to a unit that gets interrupted


DEFAULT_CAMPAIGN = [
    TaskType("As-found survey", 2, 4, 2.0, 25, 1.2, 0.9, resetup_h=0.1),
    TaskType("Dredge / expose", 1, 20, 1.5, 20, 1.0, 0.8, resetup_h=0.1),
    TaskType("Cut / flange",    1, 10, 1.2, 18, 0.6, 0.5, resetup_h=0.5),
    TaskType("Rig & recover",   2, 5, 1.5, 20, 0.8, 0.7, resetup_h=2.0),
    TaskType("Backfill",        1, 8, 1.8, 22, 1.1, 0.9, resetup_h=0.1),
]


# ---------------------------------------------------------------------------
# historical window sampling
# ---------------------------------------------------------------------------
def _window_length_hours(start, end) -> int:
    return int((pd.Timestamp(end) - pd.Timestamp(start)) / pd.Timedelta(hours=1))


def historical_windows(df: pd.DataFrame, start, end, cfg: ClimatologyConfig,
                       overrun_buffer_days: int = 60):
    """
    Return a list of (year, weight, arrays) for each historical year that has
    the execution calendar-window. arrays is a dict of numpy arrays for the
    window plus an overrun buffer (so overruns get a measurable duration).
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    tz = df.index.tz
    years = sorted(pd.unique(df.index.year))
    last = max(years)
    yr0 = last - cfg.lookback_years + 1
    L = _window_length_hours(start, end)
    span = pd.Timedelta(hours=L) + pd.Timedelta(days=overrun_buffer_days)

    out = []
    for y in years:
        if y < yr0:
            continue
        try:
            w_start = pd.Timestamp(year=y, month=start.month, day=start.day,
                                   hour=start.hour, tz=tz)
        except ValueError:
            continue  # e.g. Feb 29 in a non-leap year
        w_end = w_start + span
        sl = df.loc[(df.index >= w_start) & (df.index < w_end)]
        if len(sl) < L:               # not enough data for this year
            continue
        out.append((y, sl))

    if not out:
        return [], L
    yrs = np.array([o[0] for o in out], dtype=float)
    wts = recency_weights(yrs, cfg.recency, cfg.half_life_years)
    wts = wts / wts.sum()
    packed = []
    for (y, sl), wt in zip(out, wts):
        packed.append((int(y), float(wt), {
            "hs": sl["hs"].to_numpy(float),
            "wind": sl["wind"].to_numpy(float),
            "cur_surf": sl["cur_surf"].to_numpy(float),
            "cur_bottom": sl["cur_bottom"].to_numpy(float),
        }))
    return packed, L


# ---------------------------------------------------------------------------
# campaign placement on one realisation
# ---------------------------------------------------------------------------
def _feasible(arr, t: TaskType):
    return ((arr["hs"] <= t.hs_max) & (arr["wind"] <= t.wind_max) &
            (arr["cur_surf"] <= t.cur_surf_max) & (arr["cur_bottom"] <= t.cur_bottom_max))


def run_campaign_once(arr: dict, tasks: List[TaskType], horizon: int):
    """
    Walk the hourly window and place every unit in sequence.
    Returns (elapsed_hours, completed_bool, wait_by_task[np]).
    Interrupted unit restarts and pays resetup on the retry.
    """
    n = len(arr["hs"])
    horizon = min(horizon, n)
    clock = 0
    wait_by = np.zeros(len(tasks))
    productive_by = np.zeros(len(tasks))

    for ti, t in enumerate(tasks):
        feas = _feasible(arr, t)
        for _u in range(t.off):
            need = t.duration_h
            unit_start_clock = clock
            placed = False
            while clock < horizon:
                # seek next feasible hour
                while clock < horizon and not feas[clock]:
                    clock += 1
                if clock >= horizon:
                    break
                # attempt a continuous run of `need` feasible hours
                run = 0
                while clock < horizon and feas[clock] and run < need:
                    run += 1
                    clock += 1
                if run >= need:
                    placed = True
                    break
                else:
                    # interrupted mid-unit: restart, pay resetup on retry
                    need = t.duration_h + t.resetup_h
            if not placed:
                elapsed = horizon
                return elapsed, False, wait_by
            productive_by[ti] += t.duration_h
            wait_by[ti] += (clock - unit_start_clock) - t.duration_h
    return clock, True, wait_by


def run_single_once(arr: dict, t: TaskType, horizon: int):
    """First continuous D-hour feasible window: (wait_hours, found_bool)."""
    n = min(len(arr["hs"]), horizon)
    feas = _feasible(arr, t)
    run = 0
    for h in range(n):
        if feas[h]:
            run += 1
            if run >= t.duration_h:
                return h - t.duration_h + 1, True
        else:
            run = 0
    return n, False


# ---------------------------------------------------------------------------
# top-level assessment
# ---------------------------------------------------------------------------
@dataclass
class WorkabilityResult:
    mode: str
    window_hours: int
    n_runs: int
    n_years: int
    productive_hours: int
    # campaign
    dur_p50: float = float("nan")
    dur_p80: float = float("nan")
    dur_p90: float = float("nan")
    fit_pct: float = float("nan")        # % realisations completing within window
    wait_by_task: Dict[str, float] = field(default_factory=dict)
    bottleneck: str = ""
    # single
    wait_p50: float = float("nan")
    wait_p80: float = float("nan")
    exists_pct: float = float("nan")     # % realisations with a valid window

    def report(self) -> str:
        d = 24.0
        if self.mode == "campaign":
            return (f"Campaign · {self.n_years} historical windows, {self.n_runs} runs\n"
                    f"  productive {self.productive_hours}h ({self.productive_hours/d:.1f}d)\n"
                    f"  elapsed  P50 {self.dur_p50/d:.1f}d  P80 {self.dur_p80/d:.1f}d  "
                    f"P90 {self.dur_p90/d:.1f}d\n"
                    f"  fits client window: {self.fit_pct:.0f}% of realisations\n"
                    f"  bottleneck: {self.bottleneck}")
        return (f"Single window · {self.n_years} historical windows, {self.n_runs} runs\n"
                f"  window exists in period: {self.exists_pct:.0f}% of realisations\n"
                f"  wait to first window  P50 {self.wait_p50/d:.1f}d  P80 {self.wait_p80/d:.1f}d")


def assess(df: pd.DataFrame, start, end,
           tasks: Optional[List[TaskType]] = None,
           mode: str = "campaign",
           cfg: ClimatologyConfig = ClimatologyConfig(),
           n_runs: int = 500,
           seed: int = 1) -> WorkabilityResult:
    windows, L = historical_windows(df, start, end, cfg)
    if not windows:
        raise ValueError("No historical windows available for this coordinate/period.")
    years = [w[0] for w in windows]
    weights = np.array([w[1] for w in windows])
    horizon_full = len(windows[0][2]["hs"])   # window + overrun buffer
    rng = np.random.default_rng(seed)
    draw = rng.choice(len(windows), size=n_runs, p=weights)

    if mode == "single":
        t = (tasks or [DEFAULT_CAMPAIGN[2]])[0]
        waits, found = [], 0
        for i in draw:
            w, ok = run_single_once(windows[i][2], t, L)
            waits.append(w)
            found += int(ok)
        waits = np.array(waits, float)
        return WorkabilityResult(
            mode="single", window_hours=L, n_runs=n_runs, n_years=len(windows),
            productive_hours=t.duration_h,
            wait_p50=float(np.percentile(waits, 50)),
            wait_p80=float(np.percentile(waits, 80)),
            exists_pct=100.0 * found / n_runs)

    tasks = tasks or DEFAULT_CAMPAIGN
    productive = sum(t.duration_h * t.off for t in tasks)
    elapsed, fits, waitmat = [], 0, np.zeros(len(tasks))
    for i in draw:
        e, ok, wby = run_campaign_once(windows[i][2], tasks, horizon_full)
        elapsed.append(e)
        fits += int(ok and e <= L)
        waitmat += wby
    elapsed = np.array(elapsed, float)
    waitmat /= n_runs
    wait_by = {t.name: float(waitmat[k]) for k, t in enumerate(tasks)}
    bn = tasks[int(np.argmax(waitmat))].name if len(tasks) else ""
    return WorkabilityResult(
        mode="campaign", window_hours=L, n_runs=n_runs, n_years=len(windows),
        productive_hours=productive,
        dur_p50=float(np.percentile(elapsed, 50)),
        dur_p80=float(np.percentile(elapsed, 80)),
        dur_p90=float(np.percentile(elapsed, 90)),
        fit_pct=100.0 * fits / n_runs,
        wait_by_task=wait_by, bottleneck=bn)
