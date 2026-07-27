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
WAVE_VARS = ["significant_height_of_combined_wind_waves_and_swell"]   # 0.5deg grid
WIND_VARS = ["10m_u_component_of_wind", "10m_v_component_of_wind"]    # 0.25deg grid
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


def _resolve_nc(path):
    """Return a path to a readable .nc file. CDS sometimes returns a ZIP bundle
    (e.g. different grids in one request); if so, extract and use the .nc inside."""
    with open(path, "rb") as fh:
        magic = fh.read(4)
    if magic[:2] == b"PK":                     # zip archive
        import zipfile, tempfile
        d = tempfile.mkdtemp()
        with zipfile.ZipFile(path) as z:
            ncs = [n for n in z.namelist() if n.endswith(".nc")]
            if not ncs:
                raise RuntimeError("ERA5 zip contained no .nc file")
            z.extract(ncs[0], d)
            return os.path.join(d, ncs[0])
    if magic == b"GRIB":                        # unexpected GRIB
        raise RuntimeError("ERA5 returned GRIB, expected NetCDF")
    return path


def _read_nc(path, lat=None, lon=None):
    """Read one ERA5 NetCDF file -> DataFrame with whichever of hs/wind the file
    holds, at the node nearest (lat, lon) if given, hourly UTC."""
    from netCDF4 import Dataset, num2date
    ds = Dataset(_resolve_nc(path))
    try:
        tname = "valid_time" if "valid_time" in ds.variables else "time"
        tv = ds.variables[tname]
        times = num2date(tv[:], tv.units,
                         only_use_cftime_datetimes=False, only_use_python_datetimes=True)
        idx = pd.to_datetime([pd.Timestamp(t) for t in times], utc=True)

        latname = "latitude" if "latitude" in ds.variables else "lat"
        lonname = "longitude" if "longitude" in ds.variables else "lon"
        lats = np.asarray(ds.variables[latname][:], dtype="float64")
        lons = np.asarray(ds.variables[lonname][:], dtype="float64")
        if lat is not None and lon is not None:
            iy = int(np.argmin(np.abs(lats - lat)))
            ix = int(np.argmin(np.abs(((lons - lon + 180) % 360) - 180)))
        else:
            iy = ix = None

        def series(var):
            a = np.ma.masked_invalid(np.array(ds.variables[var][:], dtype="float64"))
            while a.ndim > 3:
                a = a[0]
            v = a[:, iy, ix] if iy is not None else a.reshape(a.shape[0], -1).mean(axis=1)
            return np.asarray(np.ma.filled(v, np.nan), dtype="float64")

        cols = {}
        if "swh" in ds.variables:
            cols["hs"] = series("swh")
        if "u10" in ds.variables and "v10" in ds.variables:
            cols["wind"] = np.hypot(series("u10"), series("v10")) * MS_TO_KN
    finally:
        ds.close()
    return pd.DataFrame(cols, index=idx).sort_index()


def _retrieve_one(c, lat, lon, years, months, times, variables):
    import tempfile
    # box must be >= the coarsest grid (waves 0.5deg) or MARS crops to empty
    half = 0.75
    req = {
        "product_type": "reanalysis",
        "variable": variables,
        "year": [str(y) for y in years],
        "month": [f"{int(m):02d}" for m in months],
        "day": _ALL_DAYS,
        "time": times,
        "area": [round(lat + half, 3), round(lon - half, 3),
                 round(lat - half, 3), round(lon + half, 3)],  # N,W,S,E
        "data_format": "netcdf",
        "download_format": "unarchived",
    }
    target = tempfile.mktemp(suffix="_era5.nc")
    try:
        c.retrieve(DATASET, req, target)
        return _read_nc(target, lat, lon)
    finally:
        try:
            os.remove(target)
        except OSError:
            pass


def _retrieve_years(c, lat, lon, years, months, times):
    # waves and wind are on DIFFERENT grids; request separately (each a single
    # NetCDF) then merge, so CDS never bundles them into an unreadable zip.
    waves = _retrieve_one(c, lat, lon, years, months, times, WAVE_VARS)
    wind = _retrieve_one(c, lat, lon, years, months, times, WIND_VARS)
    return waves.join(wind, how="outer")


def fetch_point_era5(lat: float, lon: float, years, months,
                     time_step_h: int = 6) -> pd.DataFrame:
    """
    Return hourly ERA5 hs + wind for the cell nearest (lat, lon), covering the
    execution `months` across `years`. Waves (0.5deg) and wind (0.25deg) are
    fetched as separate single-grid requests and merged. Years are chunked to
    stay under the CDS cost limit and the 120 s worker timeout; sub-daily
    sampling is interpolated to the hourly engine grid. Raises on hard failure.
    """
    c = _client()
    years = list(years)
    times = [f"{h:02d}:00" for h in range(0, 24, max(1, time_step_h))]
    per_year = 31 * len(months) * len(times)      # per grid, per variable-group
    chunk = max(1, min(len(years), 6000 // max(1, per_year)))
    frames, errors = [], []
    for i in range(0, len(years), chunk):
        yrs = years[i:i + chunk]
        try:
            frames.append(_retrieve_years(c, lat, lon, yrs, months, times))
        except Exception as ex:
            errors.append(str(ex))
    if not frames:
        raise RuntimeError("ERA5 request failed" + (f": {errors[0]}" if errors else ""))
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df = df.resample("1h").mean().interpolate("time")
    for c_ in ("hs", "wind"):
        if c_ not in df:
            df[c_] = np.nan
    df["cur_surf"] = np.nan
    df["cur_mid"] = np.nan
    df["cur_bottom"] = np.nan
    df.attrs["source_name"] = "ERA5"
    df.attrs["current_note"] = "ERA5 waves & wind, execution months (no currents)"
    return df
