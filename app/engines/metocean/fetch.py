"""
CMEMS point fetcher.

Pulls multi-year reanalysis for a single coordinate (nearest grid cell) and
returns one tidy hourly DataFrame with the columns the climatology expects:
    hs (m), wind (kn), cur_surf (kn), cur_bottom (kn)

Requires Copernicus Marine credentials (free registration at
https://data.marine.copernicus.eu). Provide them via:
    - copernicusmarine.login() once (stores a credentials file), or
    - CMEMS_USERNAME / CMEMS_PASSWORD environment variables, or
    - the username/password arguments here.

This module makes the real API calls but is not exercised in the offline test
suite (no network/credentials there). demo_source.py provides an equivalent
synthetic frame so the rest of the stack runs and is tested without CMEMS.
"""

from __future__ import annotations
import os
from typing import Optional
import numpy as np
import pandas as pd

from . import products

MS_TO_KN = 1.943844


def _creds(username, password):
    return (username or os.environ.get("CMEMS_USERNAME"),
            password or os.environ.get("CMEMS_PASSWORD"))


def _point_frame(dataset, lat, lon, start, end, username, password,
                 depth=None):
    """Thin wrapper over copernicusmarine.read_dataframe for one grid cell."""
    import copernicusmarine as cm
    kw = dict(
        dataset_id=dataset.dataset_id,
        variables=dataset.variables,
        minimum_longitude=lon, maximum_longitude=lon,
        minimum_latitude=lat, maximum_latitude=lat,
        start_datetime=pd.Timestamp(start).isoformat(),
        end_datetime=pd.Timestamp(end).isoformat(),
        coordinates_selection_method="nearest",
    )
    if depth is not None:
        kw.update(minimum_depth=depth, maximum_depth=depth)
    u, p = _creds(username, password)
    if u and p:
        kw.update(username=u, password=p)
    df = cm.read_dataframe(**kw)
    # read_dataframe returns a (multi-)indexed frame; flatten to a time index
    df = df.reset_index()
    return df


def fetch_point(lat: float, lon: float, start, end,
                working_depth_m: float = 34.0,
                username: Optional[str] = None,
                password: Optional[str] = None,
                resample: str = "1h") -> pd.DataFrame:
    """
    Return an hourly point time series with columns hs, wind, cur_surf,
    cur_bottom. Products differ in native cadence (waves 3-hourly, wind hourly,
    currents daily) so each is resampled/interpolated onto a common hourly grid.
    """
    # -- waves
    w = _point_frame(products.WAVE_REANALYSIS, lat, lon, start, end,
                     username, password)
    w = w.rename(columns={"VHM0": "hs"}).set_index("time")[["hs"]]

    # -- wind (components -> speed in knots)
    wind = _point_frame(products.WIND_REANALYSIS, lat, lon, start, end,
                        username, password).set_index("time")
    spd = np.hypot(wind["eastward_wind"], wind["northward_wind"]) * MS_TO_KN
    wind = spd.to_frame("wind")

    # -- currents at surface (~0.5 m) and working depth, FAIL-SOFT.
    # Try the preferred (regional, e.g. IBI) product first; on any error fall
    # back to global GLORYS; if that also fails, continue with empty currents so
    # the assessment still runs on real waves and wind. Record what happened in
    # df.attrs so the page can tell the user (surfaced instead of silent).
    preferred = products.current_dataset_for(lat, lon)
    candidates = [preferred]
    if preferred.dataset_id != products.CURRENT_REANALYSIS.dataset_id:
        candidates.append(products.CURRENT_REANALYSIS)   # GLORYS global fallback

    cur_surf = cur_bot = None
    cur_source, cur_note = "none", ""
    for cds in candidates:
        try:
            cs = _point_frame(cds, lat, lon, start, end, username, password,
                              depth=0.5).set_index("time")
            cb = _point_frame(cds, lat, lon, start, end, username, password,
                              depth=working_depth_m).set_index("time")
            cur_surf = (np.hypot(cs["uo"], cs["vo"]) * MS_TO_KN).to_frame("cur_surf")
            cur_bot = (np.hypot(cb["uo"], cb["vo"]) * MS_TO_KN).to_frame("cur_bottom")
            cur_source = cds.product_id.split("_")[0]     # 'IBI' or 'GLOBAL'
            break
        except Exception as e:
            cur_note = f"{cds.dataset_id}: {e}"
            continue

    # -- assemble & align onto common hourly grid
    out = w.join(wind, how="outer")
    if cur_surf is not None:
        out = out.join(cur_surf, how="outer").join(cur_bot, how="outer")
    else:
        out["cur_surf"] = np.nan
        out["cur_bottom"] = np.nan
    out.index = pd.to_datetime(out.index, utc=True)
    out = out.sort_index().resample(resample).mean().interpolate("time")
    out = out[["hs", "wind", "cur_surf", "cur_bottom"]]
    out.attrs["current_source"] = cur_source
    out.attrs["current_note"] = cur_note
    return out
