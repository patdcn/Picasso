"""
Metocean workability engine for the DCN portal (Weather Stats / Copernicus page).

    get_series(lat, lon)        cached point series (live CMEMS or demo)
    build_climatology(...)      recency-weighted seasonal stats + trend diagnostic
    assess(...)                 single / campaign workability vs the client window
"""
from .products import classify_region, current_dataset_for
from .climatology import (
    ClimatologyConfig, build_climatology, execution_months,
    summarise_variable, trend_diagnostic, DEFAULT_THRESHOLDS,
)
from .workability import (
    assess, AssessResult, DepthOutcome, historical_windows, DEPTHS,
)
from .demo_source import synth_point, DemoConfig
from .cache import get_series, credentials_present

try:
    from .fetch import fetch_point
except Exception:  # pragma: no cover
    fetch_point = None

__all__ = [
    "get_series", "credentials_present", "fetch_point", "synth_point", "DemoConfig",
    "build_climatology", "ClimatologyConfig", "execution_months",
    "summarise_variable", "trend_diagnostic", "DEFAULT_THRESHOLDS",
    "assess", "AssessResult", "DepthOutcome", "historical_windows", "DEPTHS",
    "classify_region", "current_dataset_for",
]
