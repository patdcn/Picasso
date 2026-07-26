"""
Climatology core — the statistics layer.

Turns a multi-year point time series (wave / wind / current) into the
workability distributions a tender needs, with four deliberate design choices
made explicit and configurable:

  1. LOOK-BACK       how many years of reanalysis to use (default 30).
  2. MONTH FILTER    keep only the calendar months of the execution window,
                     because a September job cares about Septembers, not the
                     annual average.
  3. RECENCY WEIGHT  weight recent years more heavily so a non-stationary
                     climate doesn't bias the distribution toward stale years,
                     while still using the full record for the storm tail.
  4. TREND DIAGNOSTIC report the measured trend (slope/decade + significance)
                     as a transparent number rather than silently baking it in.

All functions are pure (DataFrame in, numbers out) and unit-tested.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence
import numpy as np
import pandas as pd
import math


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------
@dataclass
class ClimatologyConfig:
    lookback_years: int = 30
    recency: str = "exponential"      # 'none' | 'linear' | 'exponential'
    half_life_years: float = 10.0     # for exponential weighting
    trend_stat: str = "p95"           # aggregate to trend-test: 'mean' | 'p95'
    trend_alpha: float = 0.05         # significance threshold


# --------------------------------------------------------------------------
# month / look-back selection
# --------------------------------------------------------------------------
def execution_months(start: pd.Timestamp, end: pd.Timestamp) -> List[int]:
    """Calendar months (1-12) spanned by the execution window, inclusive."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    months, cur = [], start.replace(day=1)
    while cur <= end:
        months.append(cur.month)
        cur = (cur + pd.offsets.MonthBegin(1))
    # de-dup, preserve order
    seen, out = set(), []
    for m in months:
        if m not in seen:
            seen.add(m); out.append(m)
    return out


def apply_lookback(df: pd.DataFrame, years: int,
                   ref: Optional[pd.Timestamp] = None) -> pd.DataFrame:
    """Keep only the most recent `years` of the record (by the index)."""
    idx = df.index
    ref = pd.Timestamp(ref) if ref is not None else idx.max()
    cutoff = ref - pd.DateOffset(years=years)
    return df[idx >= cutoff]


def filter_execution_months(df: pd.DataFrame, months: Sequence[int]) -> pd.DataFrame:
    return df[df.index.month.isin(list(months))]


# --------------------------------------------------------------------------
# recency weighting
# --------------------------------------------------------------------------
def recency_weights(years: np.ndarray, method: str, half_life: float) -> np.ndarray:
    """
    Per-sample weights from each sample's calendar year. Newest year weight 1.0.
    Returned weights are NOT normalised (weighted_* handle normalisation).
    """
    years = np.asarray(years, dtype=float)
    if years.size == 0:
        return years
    age = years.max() - years
    if method == "none":
        return np.ones_like(years)
    if method == "linear":
        span = max(age.max(), 1.0)
        return 1.0 - 0.5 * (age / span)          # newest 1.0 -> oldest 0.5
    if method == "exponential":
        return 0.5 ** (age / max(half_life, 1e-6))
    raise ValueError(f"unknown recency method: {method}")


# --------------------------------------------------------------------------
# weighted statistics
# --------------------------------------------------------------------------
def weighted_quantile(values: np.ndarray, weights: np.ndarray,
                      q: float) -> float:
    """Weighted quantile (q in [0,1]) via cumulative-weight interpolation."""
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    m = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    values, weights = values[m], weights[m]
    if values.size == 0:
        return float("nan")
    order = np.argsort(values)
    values, weights = values[order], weights[order]
    cum = np.cumsum(weights) - 0.5 * weights
    cum /= weights.sum()
    return float(np.interp(q, cum, values))


def weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    values = np.asarray(values, float); weights = np.asarray(weights, float)
    m = np.isfinite(values) & np.isfinite(weights)
    if not m.any():
        return float("nan")
    return float(np.average(values[m], weights=weights[m]))


def weighted_exceedance(values: np.ndarray, weights: np.ndarray,
                        threshold: float) -> float:
    """Weighted P(value > threshold) — the downtime driver for a limit."""
    values = np.asarray(values, float); weights = np.asarray(weights, float)
    m = np.isfinite(values) & np.isfinite(weights)
    values, weights = values[m], weights[m]
    if weights.sum() == 0:
        return float("nan")
    return float(weights[values > threshold].sum() / weights.sum())


# --------------------------------------------------------------------------
# distribution summary for one variable
# --------------------------------------------------------------------------
@dataclass
class VarSummary:
    variable: str
    n_hours: int
    n_years: int
    w_mean: float
    p50: float
    p80: float
    p90: float
    p95: float
    exceedance: Dict[float, float]     # threshold -> weighted P(exceed)

    def as_dict(self):
        d = self.__dict__.copy()
        d["exceedance"] = {float(k): round(v, 4) for k, v in self.exceedance.items()}
        return d


def summarise_variable(df: pd.DataFrame, column: str,
                       thresholds: Sequence[float],
                       cfg: ClimatologyConfig) -> VarSummary:
    """Weighted distribution + exceedance for one metocean variable."""
    vals = df[column].to_numpy(dtype=float)
    yrs = df.index.year.to_numpy()
    w = recency_weights(yrs, cfg.recency, cfg.half_life_years)
    exc = {float(t): weighted_exceedance(vals, w, t) for t in thresholds}
    return VarSummary(
        variable=column,
        n_hours=int(np.isfinite(vals).sum()),
        n_years=int(pd.unique(yrs).size),
        w_mean=weighted_mean(vals, w),
        p50=weighted_quantile(vals, w, 0.50),
        p80=weighted_quantile(vals, w, 0.80),
        p90=weighted_quantile(vals, w, 0.90),
        p95=weighted_quantile(vals, w, 0.95),
        exceedance=exc,
    )



# --------------------------------------------------------------------------
# numpy-only OLS trend + Student-t p-value (validated against scipy to 1e-13)
# --------------------------------------------------------------------------
def _betacf(a, b, x):
    MAXIT, EPS, FPMIN = 300, 3e-12, 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN: d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN: c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN: d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN: c = FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < EPS:
            break
    return h


def _betai(a, b, x):
    if x <= 0.0: return 0.0
    if x >= 1.0: return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                  + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _ols_trend(years, vals):
    """Return (slope, two_sided_p_value) for vals ~ years via OLS + t-test."""
    x = np.asarray(years, float); y = np.asarray(vals, float)
    n = len(x)
    xm, ym = x.mean(), y.mean()
    sxx = ((x - xm) ** 2).sum()
    if sxx == 0 or n < 3:
        return float("nan"), float("nan")
    slope = ((x - xm) * (y - ym)).sum() / sxx
    intercept = ym - slope * xm
    resid = y - (slope * x + intercept)
    df = n - 2
    se = math.sqrt((resid ** 2).sum() / df / sxx) if df > 0 else 0.0
    if se == 0:
        return slope, float("nan")
    t = slope / se
    p = _betai(df / 2.0, 0.5, df / (df + t * t))
    return slope, p

# --------------------------------------------------------------------------
# trend diagnostic
# --------------------------------------------------------------------------
@dataclass
class TrendResult:
    variable: str
    stat: str
    slope_per_decade: float
    p_value: float
    significant: bool
    n_years: int
    first_year: int
    last_year: int
    baseline: float          # the aggregate stat in the first year
    note: str = ""

    def as_dict(self):
        return self.__dict__.copy()


def trend_diagnostic(df: pd.DataFrame, column: str,
                     cfg: ClimatologyConfig) -> TrendResult:
    """
    Fit an OLS trend to the per-year aggregate (mean or 95th pctile) of the
    month-filtered series and test significance. Reported, not applied.
    """
    yrs = df.index.year
    agg_fn = (lambda s: s.mean()) if cfg.trend_stat == "mean" \
        else (lambda s: s.quantile(0.95))
    by_year = df.groupby(yrs)[column].apply(agg_fn).dropna()
    years = by_year.index.to_numpy(dtype=float)
    vals = by_year.to_numpy(dtype=float)

    if years.size < 3:
        return TrendResult(column, cfg.trend_stat, float("nan"), float("nan"),
                           False, int(years.size),
                           int(years.min()) if years.size else 0,
                           int(years.max()) if years.size else 0,
                           float("nan"),
                           note="Too few years to fit a trend.")

    slope, pval = _ols_trend(years, vals)
    return TrendResult(
        variable=column,
        stat=cfg.trend_stat,
        slope_per_decade=float(slope * 10.0),
        p_value=float(pval),
        significant=bool(pval < cfg.trend_alpha) if pval == pval else False,
        n_years=int(years.size),
        first_year=int(years.min()),
        last_year=int(years.max()),
        baseline=float(vals[0]),
    )


# --------------------------------------------------------------------------
# top-level: full climatology bundle
# --------------------------------------------------------------------------
@dataclass
class Climatology:
    lat: float
    lon: float
    months: List[int]
    lookback_years: int
    recency: str
    summaries: Dict[str, VarSummary]
    trends: Dict[str, TrendResult]

    def report(self) -> str:
        lines = [f"Metocean climatology @ {self.lat:.3f}, {self.lon:.3f}",
                 f"  months={self.months}  look-back={self.lookback_years}y  "
                 f"recency={self.recency}"]
        for k, s in self.summaries.items():
            lines.append(f"  [{k}] mean={s.w_mean:.2f}  P50={s.p50:.2f}  "
                         f"P80={s.p80:.2f}  P90={s.p90:.2f}  "
                         f"({s.n_years}y, {s.n_hours} obs)")
            for t, p in s.exceedance.items():
                lines.append(f"        exceed >{t:g}: {100*p:.1f}% of time")
        for k, tr in self.trends.items():
            sig = "SIGNIFICANT" if tr.significant else "not significant"
            lines.append(f"  [trend {k}/{tr.stat}] "
                         f"{tr.slope_per_decade:+.3f}/decade  "
                         f"p={tr.p_value:.3f} ({sig})")
        return "\n".join(lines)


# columns expected in the input frame, with default operating thresholds
DEFAULT_THRESHOLDS = {
    "hs":         [1.0, 1.5, 2.0, 2.5],   # m
    "wind":       [15, 20, 25],           # kn
    "cur_surf":   [0.5, 0.8, 1.0],        # kn
    "cur_mid":    [0.4, 0.6, 0.8],        # kn
    "cur_bottom": [0.3, 0.5, 0.7],        # kn
}


def build_climatology(df: pd.DataFrame, lat: float, lon: float,
                      start, end,
                      cfg: ClimatologyConfig = ClimatologyConfig(),
                      thresholds: Optional[Dict[str, Sequence[float]]] = None,
                      ) -> Climatology:
    """
    df: point time series indexed by UTC datetime, any subset of columns
        {hs, wind, cur_surf, cur_bottom}.
    """
    thresholds = thresholds or DEFAULT_THRESHOLDS
    months = execution_months(start, end)

    df = apply_lookback(df, cfg.lookback_years)
    df = filter_execution_months(df, months)

    summaries, trends = {}, {}
    for col in df.columns:
        if col not in thresholds:
            continue
        summaries[col] = summarise_variable(df, col, thresholds[col], cfg)
        trends[col] = trend_diagnostic(df, col, cfg)

    return Climatology(lat, lon, months, cfg.lookback_years, cfg.recency,
                       summaries, trends)
