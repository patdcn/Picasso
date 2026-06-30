"""
Saturation decompression engine — U.S. Navy Diving Manual (Rev 7), Chapter 13.

Implements the *standard* saturation decompression profile (storage depth ->
surface) per Table 13-9 and the rules in section 13-23. The chamber travels
upward at a depth-banded rate, halting for rest stops, then finishes with a
terminal 4 fsw hold before surfacing.

All computation is done in fsw (feet of seawater) — the native unit of the USN
tables. Metres-of-seawater (msw) is a *display* convenience only; the page
converts at the boundary using FT_PER_M. Nothing in the table is re-derived in
metric.

The profile is built as an exact piecewise-linear path: within a depth band the
rate is constant (so depth-vs-time is a straight line), and during a rest stop
depth is flat. Vertices are emitted only where the slope changes — at band
boundaries (200/100/50 fsw), at each rest-stop start/resume, and at the terminal
sequence. That makes the table and chart exact, not sampled.

Upward-excursion initiation (section 13-23.1-3) is PREPPED but not yet wired:
the constants and the `mode` argument are in place; `mode="excursion"` raises
NotImplementedError until Table 13-8 is transcribed and an excursion-depth input
is added to the page. See EXCURSION_* below.
"""
from datetime import datetime, timedelta

# --------------------------------------------------------------------------- #
# Constants — all straight from Chapter 13. Single source of truth.
# --------------------------------------------------------------------------- #

# Table 13-9, Saturation Decompression Rates. (lower_edge_fsw, rate_fsw_per_hr)
# Read as: while the chamber is in the band whose lower edge is `edge`, travel at
# `rate` ft/hr. The boundary depth itself belongs to the *shallower* (slower) band.
BANDS = [
    (200.0, 6.0),   # 1600 – 200 fsw : 6 ft/hr  (1 ft / 10 min)
    (100.0, 5.0),   #  200 – 100 fsw : 5 ft/hr  (1 ft / 12 min)
    (50.0,  4.0),   #  100 –  50 fsw : 4 ft/hr  (1 ft / 15 min)
    (0.0,   3.0),   #   50 –   0 fsw : 3 ft/hr  (1 ft / 20 min)
]

# Section 13-23.5 terminal sequence.
TERMINAL_STOP_FSW = 4.0       # last decompression stop before surfacing
TERMINAL_HOLD_MIN = 80.0      # held at 4 fsw for 80 minutes
FINAL_ASCENT_FPM = 1.0        # then direct ascent to surface at 1 fsw/min

# Section 13-23.4 rest stops: travel halts 8 h out of every 24 h, in >= 2 periods.
# Default windows reproduce the manual's example daily routine (whole-hour clock):
#   0000-0600 rest, 0600-1400 travel, 1400-1600 rest, 1600-2400 travel.
DEFAULT_REST_WINDOWS = [(0.0, 6.0), (14.0, 16.0)]

# Depth-input bounds. Table 13-9 tops out at 1600 fsw; per the project decision
# the planner caps storage depth at 300 msw (~984 fsw).
FT_PER_M = 3.280839895
MIN_FSW = 30.0
MAX_MSW = 300.0
MAX_FSW = round(MAX_MSW * FT_PER_M, 1)   # ~984.3 fsw

# --- Upward-excursion initiation (section 13-23.1-3) — PREPPED, not yet active.
EXCURSION_TRAVEL_FPM = 2.0            # 13-23.2: upward excursion travel rate
POST_EXCURSION_HOLD_MIN = 120.0      # 13-23.3: 2-hour post-excursion hold ...
POST_EXCURSION_HOLD_MAX_STORAGE_FSW = 200.0   # ... when storage depth <= 200 fsw
# Table 13-8 (Unlimited Duration Upward Excursion Limits) will live here when the
# excursion mode is built; the shallowest excursion depth is keyed on the deepest
# depth in the preceding 48 h (an operator-entered value), not on storage depth.


# --------------------------------------------------------------------------- #
# Unit helpers (display only; engine math stays in fsw)
# --------------------------------------------------------------------------- #
def msw_to_fsw(msw):
    return float(msw) * FT_PER_M


def fsw_to_msw(fsw):
    return float(fsw) / FT_PER_M


def depth_in(fsw, unit):
    """fsw -> value in the requested display unit ('fsw' or 'msw')."""
    return fsw if unit == "fsw" else fsw_to_msw(fsw)


def rate_in(fph, unit):
    """ft/hr -> rate value in the requested unit ('fsw' -> ft/hr, 'msw' -> m/hr)."""
    return fph if unit == "fsw" else fph / FT_PER_M


# --------------------------------------------------------------------------- #
# Core schedule rules
# --------------------------------------------------------------------------- #
def _band(d):
    """(lower_edge, rate_ft_per_hr) for travelling downward from depth d (fsw)."""
    for edge, rate in BANDS:
        if d > edge:
            return edge, rate
    return 0.0, BANDS[-1][1]


def _tod_hours(t):
    return t.hour + t.minute / 60.0 + t.second / 3600.0 + t.microsecond / 3.6e9


def _resting(t, windows):
    h = _tod_hours(t)
    for a, b in windows:
        if a <= b:
            if a <= h < b:
                return True
        else:                       # window wraps past midnight
            if h >= a or h < b:
                return True
    return False


def _next_state_change(t, windows):
    """Datetime of the next travel<->rest flip after t."""
    edges = sorted({e % 24.0 for w in windows for e in w})
    if not edges:
        return t + timedelta(days=3650)        # no windows -> never flips
    h = _tod_hours(t)
    base = t.replace(hour=0, minute=0, second=0, microsecond=0)
    for day in (0, 1):
        for e in edges:
            cand = base + timedelta(days=day, hours=e)
            if cand > t + timedelta(microseconds=1):
                return cand
    return base + timedelta(days=1, hours=edges[0])


# --------------------------------------------------------------------------- #
# Profile builder
# --------------------------------------------------------------------------- #
def simulate(storage_fsw, start_dt, rest_windows=None, terminal_4fsw=True,
             mode="standard"):
    """
    Build the saturation decompression profile.

    Returns a list of vertex dicts, each:
        {"elapsed_h": float, "depth_fsw": float, "clock": datetime,
         "event": str, "resting": bool}

    `mode="excursion"` is reserved for upward-excursion initiation and is not
    yet implemented.
    """
    if mode != "standard":
        raise NotImplementedError(
            "Upward-excursion initiation is not built yet (mode='%s')." % mode)

    windows = rest_windows if rest_windows is not None else DEFAULT_REST_WINDOWS
    storage_fsw = float(storage_fsw)
    target = TERMINAL_STOP_FSW if terminal_4fsw else 0.0

    t = start_dt
    d = storage_fsw
    out = [_vertex(0.0, d, t, "Start at storage depth", _resting(t, windows))]

    guard = 0
    while d > target + 1e-9:
        guard += 1
        if guard > 200000:                      # safety against any infinite loop
            break

        if _resting(t, windows):
            t = _next_state_change(t, windows)
            out.append(_vertex(_el(start_dt, t), d, t, "Travel resumes", False))
            continue

        lower, rate = _band(d)
        seg_target = max(lower, target)
        full_h = (d - seg_target) / rate
        t_seg_end = t + timedelta(hours=full_h)
        t_rest = _next_state_change(t, windows)   # currently travelling -> next rest start

        if t_rest < t_seg_end:                    # rest interrupts this segment
            dh = (t_rest - t).total_seconds() / 3600.0
            d -= rate * dh
            t = t_rest
            out.append(_vertex(_el(start_dt, t), d, t, "Rest stop begins", True))
        else:                                     # reach the segment's lower edge
            t = t_seg_end
            d = seg_target
            if d <= target + 1e-9:
                lbl = "Arrive surface" if target == 0.0 else "Arrive %g fsw" % target
            else:
                _, new_rate = _band(d - 1e-6)
                lbl = "Rate \u2192 %g ft/hr" % new_rate
            out.append(_vertex(_el(start_dt, t), d, t, lbl, False))

    # Terminal sequence (runs to completion; not interrupted by rest windows).
    if terminal_4fsw:
        t = t + timedelta(minutes=TERMINAL_HOLD_MIN)
        out.append(_vertex(_el(start_dt, t), TERMINAL_STOP_FSW, t,
                           "End %g-min hold at 4 fsw" % TERMINAL_HOLD_MIN, False))
        t = t + timedelta(minutes=TERMINAL_STOP_FSW / FINAL_ASCENT_FPM)
        out.append(_vertex(_el(start_dt, t), 0.0, t,
                           "Surface (1 fsw/min)", False))

    return out


def _vertex(elapsed_h, depth_fsw, clock, event, resting):
    return {"elapsed_h": round(elapsed_h, 4), "depth_fsw": round(depth_fsw, 2),
            "clock": clock, "event": event, "resting": resting}


def _el(start, t):
    return (t - start).total_seconds() / 3600.0


# --------------------------------------------------------------------------- #
# Convenience: summary + table rows in a chosen display unit
# --------------------------------------------------------------------------- #
def summary(vertices):
    """Headline figures for the summary cards."""
    total_h = vertices[-1]["elapsed_h"]
    rest_stops = sum(1 for v in vertices if v["event"] == "Rest stop begins")
    return {
        "total_h": total_h,
        "total_days": total_h / 24.0,
        "surface_dt": vertices[-1]["clock"],
        "rest_stops": rest_stops,
    }


def table_rows(vertices, unit="fsw"):
    """[(elapsed_h, clock, depth_display, event), ...] in the requested unit."""
    rows = []
    for v in vertices:
        rows.append((
            v["elapsed_h"],
            v["clock"],
            depth_in(v["depth_fsw"], unit),
            v["event"],
        ))
    return rows
