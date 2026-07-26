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
                 depth=None, depth_range=None):
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
    elif depth_range is not None:
        kw.update(minimum_depth=depth_range[0], maximum_depth=depth_range[1])
    u, p = _creds(username, password)
    if u and p:
        kw.update(username=u, password=p)
    df = cm.read_dataframe(**kw)
    # read_dataframe returns a (multi-)indexed frame; flatten to a time index
    df = df.reset_index()
    return df


def _pick_levels(cds, lat, lon, start, username, password, max_probe=6000):
    """
    Probe the full water column at the point (1-day sample) and return
    (surface_depth, mid_depth, bottom_depth) using only WET (non-NaN) levels:
      surface = shallowest wet level
      bottom  = deepest wet level (the model seabed at this cell — could be
                20 m in the shallow Gulf or 3 km in deep water; no cap)
      mid     = wet level nearest half the seabed depth
    Returns (None, None, None) if the column has no wet level.
    """
    probe = _point_frame(cds, lat, lon, start,
                         pd.Timestamp(start) + pd.Timedelta(days=1),
                         username, password, depth_range=(0, max_probe))
    spd = np.hypot(probe["uo"], probe["vo"])
    wet = probe.loc[np.isfinite(spd), "depth"]
    if wet.empty:
        return None, None, None
    depths = np.sort(wet.unique())
    surf_d = float(depths.min())
    bott_d = float(depths.max())
    mid_target = bott_d / 2.0
    mid_d = float(depths[np.argmin(np.abs(depths - mid_target))])
    return surf_d, mid_d, bott_d


def fetch_point(lat: float, lon: float, start, end,
                username: Optional[str] = None,
                password: Optional[str] = None,
                resample: str = "1h", **_ignore) -> pd.DataFrame:
    """
    Return an hourly point time series with columns hs, wind, cur_surf, cur_mid,
    cur_bottom (currents at the shallowest / mid / deepest wet model levels).
    Products differ in native cadence (waves 3-hourly, wind hourly, currents
    daily) so each is resampled/interpolated onto a common hourly grid.
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

    # -- currents at surface / mid-water / bottom wet levels, FAIL-SOFT.
    # Try the preferred (regional, e.g. IBI) product first; on any error fall
    # back to global GLORYS; if that also fails, continue with empty currents so
    # the assessment still runs on real waves and wind.
    preferred = products.current_dataset_for(lat, lon)
    candidates = [preferred]
    if preferred.dataset_id != products.CURRENT_REANALYSIS.dataset_id:
        candidates.append(products.CURRENT_REANALYSIS)   # GLORYS global fallback

    cols = {}
    cur_source, cur_note = "none", ""
    depths = {"surf": None, "mid": None, "bott": None}
    for cds in candidates:
        try:
            surf_d, mid_d, bott_d = _pick_levels(cds, lat, lon, start,
                                                 username, password)
            if surf_d is None:
                raise ValueError("no wet model level in the water column")
            for key, d in (("cur_surf", surf_d), ("cur_mid", mid_d), ("cur_bottom", bott_d)):
                fr = _point_frame(cds, lat, lon, start, end, username, password,
                                  depth=d).set_index("time")
                cols[key] = (np.hypot(fr["uo"], fr["vo"]) * MS_TO_KN).to_frame(key)
            depths = {"surf": surf_d, "mid": mid_d, "bott": bott_d}
            cur_source = cds.product_id.split("_")[0]     # 'IBI' or 'GLOBAL'
            cur_note = f"surface {surf_d:.1f} m · mid {mid_d:.1f} m · bottom {bott_d:.1f} m"
            break
        except Exception as e:
            cur_note = f"{cds.dataset_id}: {e}"
            continue

    # -- assemble & align onto common hourly grid
    out = w.join(wind, how="outer")
    for key in ("cur_surf", "cur_mid", "cur_bottom"):
        if key in cols:
            out = out.join(cols[key], how="outer")
        else:
            out[key] = np.nan
    out.index = pd.to_datetime(out.index, utc=True)
    out = out.sort_index().resample(resample).mean().interpolate("time")
    out = out[["hs", "wind", "cur_surf", "cur_mid", "cur_bottom"]]
    out.attrs["current_source"] = cur_source
    out.attrs["current_note"] = cur_note
    out.attrs["depth_surf"] = depths["surf"]
    out.attrs["depth_mid"] = depths["mid"]
    out.attrs["depth_bott"] = depths["bott"]
    return out
