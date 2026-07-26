"""
CMEMS product registry for the workability metocean layer.

Every dataset ID and variable name below is a Copernicus Marine catalogue
identifier. The multi-year (reanalysis) products are what the workability
statistics are built on; the analysis/forecast products are listed for the
live/nowcast side but are not used by the climatology.

NOTE ON VARIABLE NAMES: these follow the CMEMS/CF conventions as published on
each product page. Confirm against the Product User Manual before first run in
your environment (variable short-names occasionally change between product
versions). They are centralised here so a change is a one-line edit.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Dataset:
    product_id: str          # human catalogue product (for reference/citation)
    dataset_id: str          # the actual dataset_id passed to copernicusmarine
    variables: List[str]     # variable short-names to request
    note: str = ""


# ---------------------------------------------------------------------------
# WAVE  — WAVERYS global reanalysis, 1993->present, 3-hourly, 1/5 deg
#   VHM0  significant wave height (m)      -> hs
#   VTM10 mean wave period (s)             -> tp
#   VMDR  mean wave direction (deg)        -> dir
# ---------------------------------------------------------------------------
WAVE_REANALYSIS = Dataset(
    product_id="GLOBAL_MULTIYEAR_WAV_001_032",
    dataset_id="cmems_mod_glo_wav_my_0.2deg_PT3H-i",
    variables=["VHM0", "VTM10", "VMDR"],
    note="WAVERYS. Significant wave height is the primary workability driver.",
)

# ---------------------------------------------------------------------------
# WIND — global reprocessed L4 sea-surface wind, hourly, 0.125 deg
#   eastward_wind / northward_wind (m/s)   -> combined to speed (kn)
# ---------------------------------------------------------------------------
WIND_REANALYSIS = Dataset(
    product_id="WIND_GLO_PHY_L4_MY_012_006",
    dataset_id="cmems_obs-wind_glo_phy_my_l4_0.125deg_PT1H",
    variables=["eastward_wind", "northward_wind"],
    note="ERA5-based, scatterometer bias-corrected. Stress-equivalent 10 m wind.",
)

# ---------------------------------------------------------------------------
# CURRENTS — GLORYS global physics reanalysis, daily, 1/12 deg, 50 depth levels
#   uo / vo (m/s) at chosen depth levels   -> speed (kn) at surface & working depth
# Caveat: GLORYS is daily-mean and does NOT resolve the tidal cycle. For
# tide-dominated shelf sites (e.g. southern North Sea) the workability engine
# uses deterministic harmonic tides for the tidal signal and treats GLORYS as
# the residual/current-climatology layer. See workability.py.
# ---------------------------------------------------------------------------
CURRENT_REANALYSIS = Dataset(
    product_id="GLOBAL_MULTIYEAR_PHY_001_030",
    dataset_id="cmems_mod_glo_phy_my_0.083deg_P1D-m",
    variables=["uo", "vo"],
    note="GLORYS12. Daily-mean; tidal cycle NOT resolved (see workability tides).",
)

# Regional higher-resolution alternative for the NW-European shelf / North Sea.
# IBI reanalysis ~1/36 deg, tide-resolving. Preferred where the point falls in box.
CURRENT_REANALYSIS_IBI = Dataset(
    product_id="IBI_MULTIYEAR_PHY_005_002",
    dataset_id="cmems_mod_ibi_phy-cur_my_0.027deg_P1D-m",
    variables=["uo", "vo"],
    note="IBI reanalysis currents (~2.5 km), daily-mean, Iberia-Biscay-Ireland / N. Sea.",
)


@dataclass(frozen=True)
class Region:
    key: str
    label: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    prefer_ibi: bool = False


# Ordered; first containing box wins. Purely to pick the best regional current
# product and to label the site — the wave/wind reanalysis is global.
REGIONS = [
    Region("gulf", "Persian Gulf", 23, 31, 47, 57),
    Region("nsea", "Southern North Sea", 50, 61, -5, 10, prefer_ibi=True),
    Region("ibi",  "Iberia-Biscay-Ireland", 26, 56, -19, 5, prefer_ibi=True),
    Region("med",  "Mediterranean", 30, 46, -6, 37),
]


def classify_region(lat: float, lon: float) -> Region:
    for r in REGIONS:
        if r.lat_min <= lat <= r.lat_max and r.lon_min <= lon <= r.lon_max:
            return r
    return Region("open", "Open / temperate shelf", -90, 90, -180, 180)


def current_dataset_for(lat: float, lon: float) -> Dataset:
    """Pick the tide-resolving regional product where available, else GLORYS."""
    r = classify_region(lat, lon)
    return CURRENT_REANALYSIS_IBI if r.prefer_ibi else CURRENT_REANALYSIS
