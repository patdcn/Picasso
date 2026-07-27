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
from . import era5 as _era5
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


def era5_credentials_present() -> bool:
    return _era5.cds_credentials_present()


def _key_era5(lat: float, lon: float, tag: str) -> Path:
    return CACHE_DIR / f"era5_{lat:.2f}_{lon:.2f}_{tag}.pkl"


import threading, time as _time
_era5_lock = threading.Lock()
_era5_inflight = {}
_LOCK_STALE_S = 1200   # 20 min: a lock older than this means the worker died


def _era5_scope(lat, lon, start, end, cfg):
    from .climatology import execution_months
    months = execution_months(start, end)
    end_year = pd.Timestamp(HISTORY_END).year
    years = list(range(end_year - int(cfg.lookback_years) + 1, end_year + 1))
    tag = f"m{'-'.join(f'{m:02d}' for m in months)}_lb{cfg.lookback_years}"
    return years, months, _key_era5(lat, lon, tag)


def _era5_worker(lat, lon, years, months, path):
    lock = Path(str(path) + ".lock")
    try:
        df = _era5.fetch_point_era5(lat, lon, years, months)
        df.to_pickle(path)
    except Exception as e:
        print(f"[weather_stats] ERA5 background fetch failed: {e}")
        try:
            Path(str(path) + ".err").write_text(f"{type(e).__name__}: {e}")
        except Exception:
            pass
    finally:
        for p in (lock,):
            try:
                p.unlink()
            except OSError:
                pass
        with _era5_lock:
            _era5_inflight.pop(str(path), None)


def get_series_era5_async(lat, lon, start, end, cfg=None):
    """
    Non-blocking ERA5 fetch. Returns (status, df_or_None, note):
      'ready'       -> df is the cached ERA5 series
      'pending'     -> a background CDS pull is running (poll again shortly)
      'unavailable' -> no credentials, or the last pull failed (note says why)
    The CDS queue is far slower than the 120 s web request, so the fetch runs in a
    daemon thread that writes the shared /data cache; the page polls the cache. A
    lock file on the shared volume coordinates the two gunicorn workers so only one
    fetch runs per scope.
    """
    from .climatology import ClimatologyConfig
    cfg = cfg or ClimatologyConfig()
    years, months, path = _era5_scope(lat, lon, start, end, cfg)
    err = Path(str(path) + ".err")
    lock = Path(str(path) + ".lock")

    if path.exists():
        try:
            return "ready", pd.read_pickle(path), ""
        except Exception:
            pass
    if not era5_credentials_present():
        return "unavailable", None, "ERA5 needs a CDS Personal Access Token (CDS_KEY)."
    if err.exists():
        msg = err.read_text()
        try:
            err.unlink()
        except Exception:
            pass
        return "unavailable", None, f"ERA5 fetch failed: {msg}"

    # a fresh lock (this or the other worker) means a fetch is already running
    if lock.exists():
        try:
            if _time.time() - lock.stat().st_mtime < _LOCK_STALE_S:
                return "pending", None, ("Fetching ERA5 from the CDS queue — this can take a "
                                         "few minutes; the comparison appears automatically.")
        except OSError:
            pass
        try:
            lock.unlink()   # stale -> allow restart
        except OSError:
            pass

    with _era5_lock:
        if str(path) not in _era5_inflight:
            _era5_inflight[str(path)] = True
            try:
                lock.write_text(str(_time.time()))
            except Exception:
                pass
            threading.Thread(target=_era5_worker, args=(lat, lon, years, months, path),
                             daemon=True).start()
    return "pending", None, ("Fetching ERA5 from the CDS queue — this can take a few "
                             "minutes; the comparison appears automatically.")
