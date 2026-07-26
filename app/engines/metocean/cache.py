"""
Data source with on-disk caching for the Weather Stats (Copernicus) page.

A portal must not re-pull ~30 years of reanalysis on every click. get_series()
caches each point pull (pickle; no extra build dependency) keyed by rounded
lat/lon, so the first assessment for a location is slow (the CMEMS download) and
every one after is instant.

If Copernicus credentials are absent it transparently falls back to the
synthetic source so the page still works (a DEMO banner is shown). Set
CMEMS_USERNAME / CMEMS_PASSWORD in the environment (Dokploy) to go live.
"""
from __future__ import annotations
import os
from pathlib import Path
import pandas as pd

from . import fetch as _fetch
from .demo_source import synth_point, DemoConfig

# Prefer the persistent /data volume so the cache survives redeploys; fall back
# to a local dir if /data isn't writable (e.g. local dev).
_DEFAULT = "/data/metocean_cache"
try:
    Path(_DEFAULT).mkdir(parents=True, exist_ok=True)
    _CACHE_ROOT = _DEFAULT
except Exception:
    _CACHE_ROOT = str(Path(__file__).parent / ".cache")
CACHE_DIR = Path(os.environ.get("METOCEAN_CACHE", _CACHE_ROOT))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

HISTORY_START = os.environ.get("METOCEAN_HISTORY_START", "1996-01-01")
HISTORY_END = os.environ.get("METOCEAN_HISTORY_END", "2025-12-31")


def credentials_present() -> bool:
    if os.environ.get("CMEMS_USERNAME") and os.environ.get("CMEMS_PASSWORD"):
        return True
    cfg = Path.home() / ".copernicusmarine" / ".copernicusmarine-credentials"
    return cfg.exists()


def _key(lat: float, lon: float, depth: float) -> Path:
    return CACHE_DIR / f"pt_{lat:.2f}_{lon:.2f}_d{depth:.0f}.pkl"


def get_series(lat: float, lon: float, working_depth_m: float = 34.0,
               force: bool = False):
    """
    Return (dataframe, source, meta) where source is 'live' | 'cache' | 'demo'
    and meta is a dict: {current_source, current_note, error}.
    Columns: hs, wind, cur_surf, cur_bottom (hourly, UTC index).
    """
    path = _key(lat, lon, working_depth_m)

    if path.exists() and not force:
        try:
            df = pd.read_pickle(path)
            return df, "cache", {"current_source": df.attrs.get("current_source", ""),
                                 "current_note": df.attrs.get("current_note", ""),
                                 "error": ""}
        except Exception:
            pass  # corrupt cache -> refetch

    if credentials_present() and _fetch.fetch_point is not None:
        try:
            df = _fetch.fetch_point(lat, lon, start=HISTORY_START, end=HISTORY_END,
                                    working_depth_m=working_depth_m)
            try:
                df.to_pickle(path)
            except Exception:
                pass
            return df, "live", {"current_source": df.attrs.get("current_source", ""),
                                "current_note": df.attrs.get("current_note", ""),
                                "error": ""}
        except Exception as e:
            # waves/wind (the essentials) failed — fall back to demo, but keep the
            # real error so the page can show it instead of a silent banner.
            err = f"{type(e).__name__}: {e}"
            print(f"[weather_stats] CMEMS fetch failed ({err}); using demo data.")
            df = synth_point(lat, lon, DemoConfig(years=30, end_year=2025,
                                                  hs_trend_per_decade=0.06))
            return df, "demo", {"current_source": "", "current_note": "", "error": err}

    df = synth_point(lat, lon, DemoConfig(years=30, end_year=2025,
                                          hs_trend_per_decade=0.06))
    return df, "demo", {"current_source": "", "current_note": "", "error": ""}
