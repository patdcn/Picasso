"""
Unit helpers for the DP pages: wind in m/s / Beaufort / knots, current in
m/s / knots. Everything downstream of the UI stays in m/s; these convert at
the edge. Beaufort per the WMO relation v = 0.836 * B^1.5 (m/s).
"""
KN_PER_MS = 1.0 / 0.514444

WIND_UNITS = [{"label": " m/s", "value": "ms"},
              {"label": " Bft", "value": "bft"},
              {"label": " kn", "value": "kn"}]
CUR_UNITS = [{"label": " m/s", "value": "ms"},
             {"label": " kn", "value": "kn"}]


def to_ms(value, unit):
    """Convert a UI value in `unit` to m/s. None passes through."""
    if value is None:
        return None
    v = float(value)
    if unit == "kn":
        return v / KN_PER_MS
    if unit == "bft":
        return 0.836 * (max(v, 0.0) ** 1.5)
    return v


def from_ms(value_ms, unit):
    """Convert m/s to the UI unit. None passes through."""
    if value_ms is None:
        return None
    v = float(value_ms)
    if unit == "kn":
        return v * KN_PER_MS
    if unit == "bft":
        return (max(v, 0.0) / 0.836) ** (2.0 / 3.0)
    return v


def convert(value, unit_from, unit_to, ndigits=2):
    """Convert a displayed value between units, rounded for the input box."""
    if value is None or unit_from == unit_to:
        return value
    out = from_ms(to_ms(value, unit_from), unit_to)
    return None if out is None else round(out, ndigits)


def unit_suffix(unit):
    return {"ms": "m/s", "bft": "Bft", "kn": "kn"}.get(unit, unit)
