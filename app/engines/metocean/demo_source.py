"""
Synthetic metocean source (no credentials required).

Produces a multi-year hourly point series with the same columns as fetch_point:
    hs (m), wind (kn), cur_surf (kn), cur_bottom (kn)

It is deliberately realistic enough to exercise every part of the stack:
  - seasonal cycle (rougher winters)
  - AR(1) persistence (storms cluster, so weather windows have real structure)
  - an OPTIONAL injected warming trend on Hs/wind, so the trend diagnostic has
    a known ground truth to detect (used by the tests)
  - deterministic tidal currents (surface + depth-scaled bottom) with a
    spring-neap beat

Region presets mirror products.classify_region so demo output is plausible
for the coordinate.
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

from .products import classify_region

# monthly mean Hs (m) and wind (kn) by region key
_CLIM = {
    "gulf": ([0.9, 0.9, 1.0, 1.0, 1.1, 1.3, 1.4, 1.3, 1.0, 0.8, 0.8, 0.9],
             [12, 12, 13, 13, 14, 17, 18, 16, 13, 11, 11, 12], 0.30, 0.55),
    "nsea": ([2.1, 1.9, 1.7, 1.4, 1.2, 1.0, 0.9, 1.0, 1.3, 1.7, 2.0, 2.2],
             [19, 18, 17, 15, 13, 12, 11, 12, 14, 17, 19, 20], 0.62, 0.60),
    "ibi":  ([2.3, 2.1, 1.9, 1.5, 1.2, 1.0, 0.9, 1.0, 1.4, 1.8, 2.1, 2.4],
             [20, 19, 18, 15, 13, 11, 11, 12, 14, 17, 19, 21], 0.45, 0.58),
    "med":  ([1.4, 1.4, 1.2, 1.0, 0.8, 0.6, 0.5, 0.6, 0.8, 1.1, 1.3, 1.5],
             [15, 15, 14, 12, 10, 9, 9, 9, 11, 13, 14, 16], 0.10, 0.50),
    "open": ([2.4, 2.2, 2.0, 1.6, 1.3, 1.1, 1.0, 1.1, 1.5, 1.9, 2.2, 2.5],
             [21, 20, 19, 16, 14, 12, 12, 13, 15, 18, 20, 22], 0.45, 0.58),
}

# tidal constituents (current knots, period hours) — M2/S2 give spring-neap
_TIDE = [(1.0, 12.4206, 0.4), (0.34, 12.0, 1.1), (0.19, 12.6583, 2.3)]


@dataclass
class DemoConfig:
    years: int = 32
    end_year: int = 2025
    hs_trend_per_decade: float = 0.06     # injected: +6 cm/decade Hs (known truth)
    wind_trend_per_decade: float = 0.0    # injected wind trend (kn/decade)
    seed: int = 7


def synth_point(lat: float, lon: float, cfg: DemoConfig = DemoConfig()
                ) -> pd.DataFrame:
    reg = classify_region(lat, lon).key
    hs_m, wd_m, tide_amp, bot_factor = _CLIM.get(reg, _CLIM["open"])
    rng = np.random.default_rng(cfg.seed + int(abs(lat * 1000 + lon)))

    start = pd.Timestamp(f"{cfg.end_year - cfg.years + 1}-01-01", tz="UTC")
    end = pd.Timestamp(f"{cfg.end_year}-12-31 23:00", tz="UTC")
    idx = pd.date_range(start, end, freq="1h")
    n = len(idx)
    hours = (idx - start) / pd.Timedelta(hours=1)
    hours = hours.to_numpy(dtype=float)
    month = idx.month.to_numpy()
    year = idx.year.to_numpy()
    yfrac = (year - cfg.end_year) / 10.0     # decades from end (<=0)

    hs_base = np.array([hs_m[m - 1] for m in month]) + cfg.hs_trend_per_decade * yfrac
    wd_base = np.array([wd_m[m - 1] for m in month]) + cfg.wind_trend_per_decade * yfrac

    # AR(1) around the seasonal mean
    phi = 0.94
    hs = np.empty(n); wd = np.empty(n)
    hs[0], wd[0] = hs_base[0], wd_base[0]
    ihs = rng.normal(0, 1, n); iwd = rng.normal(0, 1, n)
    for i in range(1, n):
        hs[i] = max(0.05, hs_base[i] + phi * (hs[i-1] - hs_base[i-1]) + 0.45 * hs_base[i] * 0.4 * ihs[i])
        wd[i] = max(0.5, wd_base[i] + phi * (wd[i-1] - wd_base[i-1]) + 0.30 * wd_base[i] * 0.4 * iwd[i])

    # deterministic tidal current; surface strongest, mid ~0.8x, bottom scaled
    u = np.zeros(n)
    for A, T, p in _TIDE:
        u += tide_amp * A * np.cos(2 * np.pi * hours / T - p)
    cur_surf = np.abs(u)
    cur_mid = cur_surf * (0.5 + 0.5 * bot_factor)   # between surface and bottom
    cur_bottom = cur_surf * bot_factor

    df = pd.DataFrame(
        {"hs": hs, "wind": wd, "cur_surf": cur_surf, "cur_mid": cur_mid,
         "cur_bottom": cur_bottom},
        index=idx)
    # nominal model depths for demo (shallow-shelf-like)
    df.attrs["depth_surf"] = 0.5
    df.attrs["depth_mid"] = 15.0
    df.attrs["depth_bott"] = 30.0
    df.attrs["current_source"] = "DEMO"
    df.attrs["current_note"] = "surface 0.5 m · mid 15.0 m · bottom 30.0 m (demo)"
    return df
