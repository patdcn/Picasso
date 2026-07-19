"""
Wind-sea consistency advisory — JONSWAP fetch relations.

The capability studies use JONSWAP as a spectral SHAPE at a fixed (Hs, Tp),
decoupled from the wind axis. In the underlying theory the parameters are
wind- and fetch-driven: for a fetch-limited wind sea,

    Hs = 0.0016 * sqrt(g * X) * U / g          (Hs ~ U * sqrt(fetch))
    Tp = 0.286 * (g X / U^2)^(1/3) * U / g

capped by the fully-developed Pierson-Moskowitz sea (Hs_FD ~ 0.0246 U^2,
reached at gX/U^2 ~ 2.2e4). This module flags when an assessed wind and an
entered Hs are inconsistent with those relations for the user's fetch — the
guardrail against reading the far radial reaches of a fixed-Hs envelope as
physical.

Limits, stated where the advisory is shown: deep-water relations (shallow
Gulf water limits Hs further, so the expectation errs high = conservative);
an entered Hs well above the wind-sea value usually means swell, whose Tp
the capability rescaling cannot represent.
"""
import math

G = 9.81
_FD_XTILDE = 2.2e4          # dimensionless fetch beyond which sea is fully developed
# advisory band: entered Hs within [1/RATIO, RATIO] x expected passes silently
RATIO = 1.6
MIN_ABS_DELTA_M = 0.5       # and ignore tiny absolute differences


def hs_fetch_m(wind_ms, fetch_km):
    """Fetch-limited wind-sea Hs [m], PM-capped. 0 for calm/zero fetch."""
    u = max(float(wind_ms), 0.0)
    x = max(float(fetch_km), 0.0) * 1000.0
    if u <= 0.1 or x <= 0.0:
        return 0.0
    hs = 0.0016 * math.sqrt(G * x) * u / G
    hs_fd = 0.0246 * u * u
    return min(hs, hs_fd)


def tp_fetch_s(wind_ms, fetch_km):
    """Fetch-limited wind-sea Tp [s], capped at the fully-developed value."""
    u = max(float(wind_ms), 0.0)
    x = max(float(fetch_km), 0.0) * 1000.0
    if u <= 0.1 or x <= 0.0:
        return 0.0
    xt = min(G * x / (u * u), _FD_XTILDE)
    return 0.286 * (xt ** (1.0 / 3.0)) * u / G


def advisory(wind_ms, hs_m, fetch_km):
    """None when the (wind, Hs) pair is a plausible wind sea for the fetch;
    otherwise a one-line advisory string for the verdict / printed sheet."""
    try:
        wind_ms = float(wind_ms)
        hs_m = float(hs_m)
        fetch_km = float(fetch_km)
    except (TypeError, ValueError):
        return None
    if wind_ms < 3.0 or hs_m <= 0.0 or fetch_km <= 0.0:
        return None                      # light airs: anything goes
    exp = hs_fetch_m(wind_ms, fetch_km)
    if exp <= 0.0:
        return None
    if abs(hs_m - exp) < MIN_ABS_DELTA_M:
        return None
    if exp / RATIO <= hs_m <= exp * RATIO:
        return None
    direction = ("well below" if hs_m < exp else "well above")
    tail = (" A much larger entered Hs usually means swell, whose period the "
            "rescaling cannot represent." if hs_m > exp else "")
    return (f"Wind\u2013wave consistency: at {wind_ms:.0f} m/s over "
            f"{fetch_km:.0f} km fetch a wind sea of \u2248 {exp:.1f} m is "
            f"expected (JONSWAP, deep water); the entered Hs {hs_m:.1f} m is "
            f"{direction} that. Verify against metocean joint wind\u2013wave "
            f"statistics.{tail}")
