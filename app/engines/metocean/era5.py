"""
ERA5 (ECMWF, Copernicus *Climate* Data Store) as an independent second source
for waves and wind, used only as a cross-check against the CMEMS reanalysis.

This is a DIFFERENT service from copernicusmarine: it authenticates against the
Climate Data Store with a Personal Access Token (CDS_KEY), and the API is a
queued batch system — you submit a request and download a NetCDF file, one
request at a time. So this is deliberately kept off the normal run path: the
page fetches ERA5 only when the user ticks "Compare vs ERA5", and the result is
cached per location so the slow first pull is paid once.

Area-subset strategy: request the single ~0.25deg cell containing the point, one
year per request (kinder to the CDS queue and easier to cache), then concatenate.
Variables: significant_height_of_combined_wind_waves_and_swell (Hs) and the two
10 m wind components -> speed in knots. No currents (ERA5 has none here) — the
comparison is waves and wind only.

Credentials come from the environment (never hardcoded, public repo):
    CDS_URL   (default https://cds.climate.copernicus.eu/api)
    CDS_KEY   your CDS Personal Access Token
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd

MS_TO_KN = 1.943844
DATASET = "reanalysis-era5-single-levels"
VARS = [
    "significant_height_of_combined_wind_waves_and_swell",
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
]
_ALL_DAYS = [f"{d:02d}" for d in range(1, 32)]
_ALL_TIMES = [f"{h:02d}:00" for h in range(24)]
_ALL_MONTHS = [f"{m:02d}" for m in range(1, 13)]


def cds_credentials_present() -> bool:
    if os.environ.get("CDS_KEY"):
        return True
    return (Path.home() / ".cdsapirc").exists()


def _client():
    import cdsapi
    url = os.environ.get("CDS_URL", "https://cds.climate.copernicus.eu/api")
    key = os.environ.get("CDS_KEY")
    if key:
        return cdsapi.Client(url=url, key=key, quiet=True)
    return cdsapi.Client(quiet=True)   # falls back to ~/.cdsapirc


def _read_nc(path, months_only=None):
    """Read one ERA5 NetCDF file -> DataFrame(hs, wind) at the single cell, hourly UTC."""
    from netCDF4 import Dataset, num2date
    ds = Dataset(path)
    try:
        # time coordinate name varies ('time' or 'valid_time')
        tname = "valid_time" if "valid_time" in ds.variables else "time"
        tv = ds.variables[tname]
        times = num2date(tv[:], tv.units,
                         only_use_cftime_datetimes=False, only_use_python_datetimes=True)
        idx = pd.to_datetime([pd.Timestamp(t) for t in times], utc=True)

        def cell_mean(var):
            a = np.array(ds.variables[var][:], dtype="float64")
            # dims (time, lat, lon) [possibly with expver] -> mean over the tiny box
            a = np.ma.masked_invalid(a)
            ax = tuple(range(1, a.ndim))
            return np.asarray(np.ma.filled(a.mean(axis=ax), np.nan), dtype="float64")

        swh = cell_mean("swh")
        u10 = cell_mean("u10")
        v10 = cell_mean("v10")
    finally:
        ds.close()
    wind = np.hypot(u10, v10) * MS_TO_KN
    df = pd.DataFrame({"hs": swh, "wind": wind}, index=idx).sort_index()
    return df


def fetch_point_era5(lat: float, lon: float, start, end,
                     progress: Optional[callable] = None) -> pd.DataFrame:
    """
    Return hourly ERA5 hs + wind for the cell containing (lat, lon), one CDS
    request per year over [start, end]. Raises on hard failure (caller fails soft).
    Adds NaN current columns so the frame is shape-compatible with the engine.
    """
    import tempfile
    c = _client()
    y0, y1 = pd.Timestamp(start).year, pd.Timestamp(end).year
    # a small box around the point (>= one 0.25deg cell each side)
    n, s = lat + 0.13, lat - 0.13
    w, e = lon - 0.13, lon + 0.13
    frames = []
    for yr in range(y0, y1 + 1):
        target = tempfile.mktemp(suffix=f"_era5_{yr}.nc")
        req = {
            "product_type": "reanalysis",
            "variable": VARS,
            "year": str(yr),
            "month": _ALL_MONTHS,
            "day": _ALL_DAYS,
            "time": _ALL_TIMES,
            "area": [round(n, 3), round(w, 3), round(s, 3), round(e, 3)],  # N,W,S,E
            "data_format": "netcdf",
        }
        try:
            c.retrieve(DATASET, req, target)
            frames.append(_read_nc(target))
        finally:
            try:
                os.remove(target)
            except OSError:
                pass
        if progress:
            progress(yr, y0, y1)
    if not frames:
        raise RuntimeError("ERA5 returned no data")
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    # engine expects current columns; ERA5 has none -> NaN (dropped as constraints)
    df["cur_surf"] = np.nan
    df["cur_mid"] = np.nan
    df["cur_bottom"] = np.nan
    df.attrs["source_name"] = "ERA5"
    df.attrs["current_note"] = "ERA5 waves & wind (no currents)"
    return df
