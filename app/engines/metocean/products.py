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


# Cosmetic label boxes (first containing box wins). These name the site for the
# sidebar/print only — they do NOT decide the current product (see IBI_DOMAIN).
# Ordered specific-sea-first so small seas win over the large Mediterranean box.
REGIONS = [
    Region("gulf",        "Persian / Arabian Gulf", 23, 31, 47, 57),
    Region("red_sea",     "Red Sea",                12, 30, 32, 44),
    Region("caspian",     "Caspian Sea",            36, 47, 47, 54),
    Region("baltic",      "Baltic Sea",             54, 66, 12, 30),
    Region("norwegian",   "Norwegian Sea",          62, 72, -5, 15),
    Region("nsea_n",      "Northern North Sea",     57, 62, -4, 10),
    Region("nsea_c",      "Central North Sea",      55, 57, -4, 10),
    Region("nsea_s",      "Southern North Sea",     50, 55, -3, 10),
    Region("med",         "Mediterranean Sea",      30, 47, -6, 37),
    Region("w_africa",    "West Africa (Guinea)",   -6, 6, -8, 12),
    Region("gulf_mexico", "Gulf of Mexico",         18, 31, -98, -80),
    Region("se_asia",     "SE Asia",               -12, 25, 95, 130),
    Region("nw_australia","NW Australia",          -28, -10, 108, 132),
    Region("brazil",      "Brazil (Santos)",       -30, 2, -52, -34),
]

# Functional: the IBI reanalysis domain (tide-resolving currents). A point is
# served by IBI only if it genuinely sits here; everywhere else uses global
# GLORYS. This is independent of the cosmetic label above, so the sidebar only
# claims "tide-resolving" where it's actually true.
IBI_DOMAIN = Region("ibi", "IBI", 26, 56, -19, 5)


def _in(r: Region, lat: float, lon: float) -> bool:
    return r.lat_min <= lat <= r.lat_max and r.lon_min <= lon <= r.lon_max


def classify_region(lat: float, lon: float) -> Region:
    for r in REGIONS:
        if _in(r, lat, lon):
            return r
    return Region("open", "Open ocean", -90, 90, -180, 180)


def current_dataset_for(lat: float, lon: float) -> Dataset:
    """Tide-resolving IBI only inside its true domain; else global GLORYS."""
    return CURRENT_REANALYSIS_IBI if _in(IBI_DOMAIN, lat, lon) else CURRENT_REANALYSIS
