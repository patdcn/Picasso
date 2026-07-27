"""
Workability engine (depth-resolved, task-free).

Consumes a multi-year point series (from fetch_point or synth_point) and reports
workability at three levels in the water column — Surface, Mid-water, Bottom —
against Hs, wind, and a per-depth current limit.

Two modes, chosen by a toggle in the UI:

  single    A weather-sensitive operation needing `duration_h` CONTINUOUS hours
            under limits (a lift, a tie-in). Reports, per depth, the % of
            historical years in which such a window exists in the client period
            and the wait to the first one.

  campaign  A programme whose NOMINAL (good-weather) working time is
            `nominal_days`. Weather adds delay on top: the tool accumulates
            workable hours through the real weather until it reaches the nominal
            total, and the elapsed calendar time is the answer. Reports, per
            depth, elapsed P50/P80/P90 and whether it fits the client window.

Each Monte-Carlo realisation is a real historical year's version of the same
calendar window (block resampling), drawn with recency weights, so storm
persistence comes from the data.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

from .climatology import ClimatologyConfig, recency_weights

# the three reported levels and their current column
DEPTHS = [("Surface", "cur_surf"), ("Mid-water", "cur_mid"), ("Bottom", "cur_bottom")]


# ---------------------------------------------------------------------------
# historical window sampling (block resampling, recency-weighted)
# ---------------------------------------------------------------------------
def _window_length_hours(start, end) -> int:
    return int((pd.Timestamp(end) - pd.Timestamp(start)) / pd.Timedelta(hours=1))


def historical_windows(df: pd.DataFrame, start, end, cfg: ClimatologyConfig,
                       overrun_buffer_days: int = 60):
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
            continue
        w_end = w_start + span
        sl = df.loc[(df.index >= w_start) & (df.index < w_end)]
        if len(sl) < L:
            continue
        out.append((y, sl))

    if not out:
        return [], L
    # We need every window uniform AND long enough to include the overrun buffer.
    # A window near the data end is data-limited (too short); DROP those rather
    # than truncating every window down to the shortest (which would remove the
    # buffer the campaign accumulation needs). Fall back to the common minimum
    # only if too few full-length windows remain.
    target = L + int(overrun_buffer_days * 24)
    full = [(y, sl) for (y, sl) in out if len(sl) >= target]
    if len(full) >= 5:
        out = [(y, sl.iloc[:target]) for (y, sl) in full]
        common = target
    else:
        common = min(len(sl) for _, sl in out)
        out = [(y, sl.iloc[:common]) for (y, sl) in out]

    yrs = np.array([o[0] for o in out], dtype=float)
    wts = recency_weights(yrs, cfg.recency, cfg.half_life_years)
    wts = wts / wts.sum()
    packed = []
    for (y, sl), wt in zip(out, wts):
        packed.append((int(y), float(wt), {
            "hs": sl["hs"].to_numpy(float),
            "wind": sl["wind"].to_numpy(float),
            "cur_surf": sl["cur_surf"].to_numpy(float),
            "cur_mid": sl["cur_mid"].to_numpy(float) if "cur_mid" in sl else np.full(len(sl), np.nan),
            "cur_bottom": sl["cur_bottom"].to_numpy(float),
        }))
    return packed, L


# ---------------------------------------------------------------------------
# feasibility mask (NaN-safe: a missing column drops that constraint)
# ---------------------------------------------------------------------------
def _feas(arr, hs_max, wind_max, cur_key, cur_max):
    n = len(arr["hs"])
    cond = np.ones(n, dtype=bool)
    for key, lim in (("hs", hs_max), ("wind", wind_max), (cur_key, cur_max)):
        v = arr[key]
        if not np.any(np.isfinite(v)):
            continue
        cond &= (v <= lim)
    return cond


def _first_continuous(mask, need):
    """Index of the start of the first run of >= `need` True hours, else -1."""
    run = 0
    for h in range(len(mask)):
        if mask[h]:
            run += 1
            if run >= need:
                return h - need + 1
        else:
            run = 0
    return -1


def _elapsed_to_accumulate(mask, need_hours):
    """Calendar hour by which `need_hours` workable hours have accumulated, else -1."""
    c = np.cumsum(mask)
    idx = np.searchsorted(c, need_hours)   # first index where cumsum >= need
    if idx >= len(mask) or c[-1] < need_hours:
        return -1
    return int(idx) + 1                    # +1: hours elapsed = index+1


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------
@dataclass
class DepthOutcome:
    label: str
    cur_key: str
    depth_m: Optional[float]
    available: bool
    # single
    exists_pct: float = float("nan")
    wait_p50: float = float("nan")
    wait_p80: float = float("nan")
    # campaign
    elapsed_p50: float = float("nan")
    elapsed_p80: float = float("nan")
    elapsed_p90: float = float("nan")
    fit_pct: float = float("nan")
    horizon_h: int = 0
    censored: bool = False       # campaign didn't complete within the sim horizon
    # campaign progress trajectory (mean cumulative work vs elapsed), daily
    progress_days: list = field(default_factory=list)
    progress_pct: list = field(default_factory=list)


@dataclass
class AssessResult:
    mode: str
    window_hours: int
    n_years: int
    duration_h: int = 0          # single
    nominal_hours: int = 0       # campaign
    depths: List[DepthOutcome] = field(default_factory=list)

    def report(self) -> str:
        lines = [f"{self.mode} · {self.n_years} historical windows"]
        for d in self.depths:
            dm = f"{d.depth_m:.0f} m" if d.depth_m is not None else "n/a"
            if self.mode == "single":
                lines.append(f"  {d.label:<10} ({dm}): exists {d.exists_pct:.0f}% · "
                             f"wait P50 {d.wait_p50/24:.1f} d / P80 {d.wait_p80/24:.1f} d")
            else:
                lines.append(f"  {d.label:<10} ({dm}): elapsed P50 {d.elapsed_p50/24:.1f} / "
                             f"P80 {d.elapsed_p80/24:.1f} / P90 {d.elapsed_p90/24:.1f} d · "
                             f"fits {d.fit_pct:.0f}%")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# top-level assessment
# ---------------------------------------------------------------------------
def window_bands(df: pd.DataFrame, start, end, cfg: ClimatologyConfig):
    """
    Per-hour-of-window P10/P50/P90 across the look-back years, for each variable.
    This is what the metocean strip draws — it responds to the look-back setting
    (more years -> the band reflects them) rather than showing one arbitrary year.
    Returns (bands, L) where bands[var] = {p10,p50,p90} arrays of length L.
    """
    wins, L = historical_windows(df, start, end, cfg, overrun_buffer_days=0)
    if not wins:
        return None, 0
    bands = {}
    for k in ("hs", "wind", "cur_surf", "cur_mid", "cur_bottom"):
        M = np.vstack([w[2][k][:L] for w in wins])          # (n_years, L)
        with np.errstate(all="ignore"):
            bands[k] = {
                "p10": np.nanpercentile(M, 10, axis=0),
                "p50": np.nanpercentile(M, 50, axis=0),
                "p90": np.nanpercentile(M, 90, axis=0),
            }
    return bands, L


def assess(df: pd.DataFrame, start, end, mode: str,
           hs_max: float, wind_max: float, cur_limits: Dict[str, float],
           duration_h: int = 6, nominal_days: float = 30.0,
           cfg: ClimatologyConfig = ClimatologyConfig(),
           n_runs: int = 500, seed: int = 1) -> AssessResult:
    """
    cur_limits: {'cur_surf': .., 'cur_mid': .., 'cur_bottom': ..} in knots.
    mode: 'single' (uses duration_h) or 'campaign' (uses nominal_days).
    """
    buffer_days = 60 if mode == "single" else max(60, int(nominal_days * 2))
    windows, L = historical_windows(df, start, end, cfg, overrun_buffer_days=buffer_days)
    if not windows:
        raise ValueError("No historical windows available for this coordinate/period.")
    weights = np.array([w[1] for w in windows])
    horizon = len(windows[0][2]["hs"])
    rng = np.random.default_rng(seed)
    draw = rng.choice(len(windows), size=n_runs, p=weights)

    depth_m = {"cur_surf": df.attrs.get("depth_surf"),
               "cur_mid": df.attrs.get("depth_mid"),
               "cur_bottom": df.attrs.get("depth_bott")}

    res = AssessResult(mode=mode, window_hours=L, n_years=len(windows),
                       duration_h=int(duration_h),
                       nominal_hours=int(round(nominal_days * 24)))

    for label, ckey in DEPTHS:
        available = np.any(np.isfinite(df[ckey].to_numpy())) if ckey in df.columns else False
        cur_max = cur_limits.get(ckey, 9e9)
        out = DepthOutcome(label=label, cur_key=ckey, depth_m=depth_m.get(ckey),
                           available=available)

        if mode == "single":
            need = max(1, int(round(duration_h)))
            waits, found = [], 0
            for i in draw:
                mask = _feas(windows[i][2], hs_max, wind_max, ckey, cur_max)[:L]
                s = _first_continuous(mask, need)
                if s >= 0:
                    found += 1
                    waits.append(s)
                else:
                    waits.append(L)
            waits = np.array(waits, float)
            out.exists_pct = 100.0 * found / n_runs
            out.wait_p50 = float(np.percentile(waits, 50))
            out.wait_p80 = float(np.percentile(waits, 80))
        else:
            need_h = max(1, int(round(nominal_days * 24)))
            # progress trajectory: mean cumulative work fraction vs elapsed hours
            maxH = min(horizon, int(need_h * 4) + 24)
            prog_sum = np.zeros(maxH)
            elapsed, fits = [], 0
            for i in draw:
                mask = _feas(windows[i][2], hs_max, wind_max, ckey, cur_max)
                e = _elapsed_to_accumulate(mask, need_h)
                if e < 0:
                    e = horizon
                elapsed.append(e)
                fits += int(e <= L)
                cum = np.minimum(np.cumsum(mask[:maxH]), need_h) / need_h
                if len(cum) < maxH:                     # short window: hold last value
                    pad = cum[-1] if len(cum) else 0.0
                    cum = np.concatenate([cum, np.full(maxH - len(cum), pad)])
                prog_sum += cum
            elapsed = np.array(elapsed, float)
            out.elapsed_p50 = float(np.percentile(elapsed, 50))
            out.elapsed_p80 = float(np.percentile(elapsed, 80))
            out.elapsed_p90 = float(np.percentile(elapsed, 90))
            out.fit_pct = 100.0 * fits / n_runs
            out.horizon_h = horizon
            out.censored = out.elapsed_p50 >= horizon - 1
            mean_prog = prog_sum / n_runs
            out.progress_days = (np.arange(0, maxH, 24) / 24.0).tolist()
            out.progress_pct = (mean_prog[::24] * 100.0).tolist()

        res.depths.append(out)

    return res
