"""
Saturation depth-excursion limits — U.S. Navy Diving Manual (Rev 7), Chapter 13.

From a given storage (living) depth, how far a saturated diver may excurse DOWN
or UP without incurring a decompression obligation on return to storage depth
("Unlimited-Duration Excursion Limits"). Two tables:

  * Table 13-7  Unlimited-Duration DOWNWARD Excursion Limits.
  * Table 13-8  Unlimited-Duration UPWARD   Excursion Limits.

These are the same tables Rev 6 carried as Table 15-7 / 15-8; Rev 7 renumbered
the saturation chapter from 15 to 13, the values are unchanged. The upward table
is the tabulation of the U.S. Navy 1989 empirical formula (Thalmann, "Testing of
revised unlimited-duration upward excursions during helium-oxygen saturation
dives", Undersea Biomed Res 1989; validated for storage depths 36-1100 fsw):

      UEXD = ( sqrt(0.1574 * D1 + 6.197) - 1 ) / 0.0787

with D1 = storage depth (fsw) and UEXD = upward excursion distance (fsw). The
tabulated integer values below are the controlling figures and are used directly.

All table math is done in feet of seawater (fsw), the native unit of the tables.
Metres are a DISPLAY convenience only (1 m = 3.280839895 ft), matching sat_deco.

Manual lookup rules (13-21):
  * DOWNWARD: if storage depth falls between listed rows, use the NEXT SHALLOWER
    listed row (e.g. 295 -> read at 290).
  * UPWARD:   if storage depth falls between listed rows, use the NEXT DEEPER
    listed row (e.g. 295 -> read at 300).

The resulting excursion depth is the actual storage depth +/- the tabulated
excursion distance (per the manual's worked examples, e.g. 400 fsw storage +
105 fsw = 505 fsw deepest). Excursions carry a 4-hour in-water limit and an
ascent rate <= 60 fsw/min; upward excursions additionally require >= 48 h of
stabilisation at storage depth and the chamber ppO2 conditions of 13-14/13-23.
INDICATIVE PLANNING ONLY.
"""

FT_PER_M = 3.280839895

# --------------------------------------------------------------------------- #
# Table 13-7 — Unlimited-Duration Downward Excursion Limits.
# storage_depth_fsw -> deepest excursion DISTANCE (ft) below storage depth.
# --------------------------------------------------------------------------- #
DOWNWARD = {
    0: 29, 10: 33, 20: 37, 30: 40, 40: 43, 50: 46, 60: 48, 70: 51, 80: 53,
    90: 56, 100: 58, 110: 60, 120: 62, 130: 64, 140: 66, 150: 68, 160: 70,
    170: 72, 180: 73, 190: 75, 200: 77, 210: 78, 220: 80, 230: 82, 240: 83,
    250: 85, 260: 86, 270: 88, 280: 89, 290: 90, 300: 92, 310: 93, 320: 95,
    330: 96, 340: 97, 350: 98, 360: 100, 370: 101, 380: 102, 390: 103,
    400: 105, 410: 106, 420: 107, 430: 108, 440: 109, 450: 111, 460: 112,
    470: 113, 480: 114, 490: 115, 500: 116, 510: 117, 520: 118, 530: 119,
    540: 120, 550: 122, 560: 123, 570: 124, 580: 125, 590: 126, 600: 127,
    610: 128, 620: 129, 630: 130, 640: 131, 650: 132, 660: 133, 670: 133,
    680: 134, 690: 135, 700: 136, 710: 137, 720: 138, 730: 139, 740: 140,
    750: 141, 760: 142, 770: 143, 780: 144, 790: 144, 800: 145, 810: 146,
    820: 147, 830: 148, 840: 149, 850: 150,
}

# --------------------------------------------------------------------------- #
# Table 13-8 — Unlimited-Duration Upward Excursion Limits.
# storage_depth_fsw -> shallowest excursion DISTANCE (ft) above storage depth.
# --------------------------------------------------------------------------- #
UPWARD = {
    29: 29, 30: 29, 40: 32, 50: 35, 60: 37, 70: 40, 80: 42, 90: 44, 100: 47,
    110: 49, 120: 51, 130: 53, 140: 55, 150: 56, 160: 58, 170: 60, 180: 62,
    190: 63, 200: 65, 210: 67, 220: 68, 230: 70, 240: 71, 250: 73, 260: 74,
    270: 76, 280: 77, 290: 79, 300: 80, 310: 81, 320: 83, 330: 84, 340: 85,
    350: 87, 360: 88, 370: 89, 380: 90, 390: 92, 400: 93, 410: 94, 420: 95,
    430: 96, 440: 97, 450: 99, 460: 100, 470: 101, 480: 102, 490: 103,
    500: 104, 510: 105, 520: 106, 530: 107, 540: 108, 550: 110, 560: 111,
    570: 112, 580: 113, 590: 114, 600: 115, 610: 116, 620: 117, 630: 118,
    640: 119, 650: 119, 660: 120, 670: 121, 680: 122, 690: 123, 700: 124,
    710: 125, 720: 126, 730: 127, 740: 128, 750: 129, 760: 130, 770: 131,
    780: 131, 790: 132, 800: 133, 810: 134, 820: 135, 830: 136, 840: 137,
    850: 137, 860: 138, 870: 139, 880: 140, 890: 141, 900: 142, 910: 142,
    920: 143, 930: 144, 940: 145, 950: 146, 960: 146, 970: 147, 980: 148,
    990: 149, 1000: 150,
}

# Combined domain where BOTH excursion directions are defined by the tables.
MIN_STORAGE_FSW = min(UPWARD)          # 29 fsw  (upward table's shallowest row)
MAX_STORAGE_FSW = max(DOWNWARD)        # 850 fsw (downward table's deepest row)
MAX_STORAGE_MSW = round(MAX_STORAGE_FSW / FT_PER_M, 1)   # ~259.1 msw


# --------------------------------------------------------------------------- #
# Unit helpers (display only; table math stays in fsw)
# --------------------------------------------------------------------------- #
def msw_to_fsw(msw):
    return float(msw) * FT_PER_M


def fsw_to_msw(fsw):
    return float(fsw) / FT_PER_M


def depth_in(fsw, unit):
    """fsw -> value in the requested display unit ('fsw' or 'msw')."""
    return float(fsw) if unit == "fsw" else fsw_to_msw(fsw)


# --------------------------------------------------------------------------- #
# Table lookups (with the manual's conservative row-rounding rules)
# --------------------------------------------------------------------------- #
def _downward_row(storage_fsw):
    """Next-SHALLOWER listed row <= storage_fsw. Returns (row_fsw, distance_ft)."""
    pick = None
    for r in sorted(DOWNWARD):
        if r <= storage_fsw + 1e-9:
            pick = r
    if pick is None:                    # below the table -> clamp to shallowest
        pick = min(DOWNWARD)
    return pick, DOWNWARD[pick]


def _upward_row(storage_fsw):
    """Next-DEEPER listed row >= storage_fsw. Returns (row_fsw, distance_ft)."""
    for r in sorted(UPWARD):
        if r >= storage_fsw - 1e-9:
            return r, UPWARD[r]
    r = max(UPWARD)                     # beyond the table -> clamp to deepest
    return r, UPWARD[r]


# --------------------------------------------------------------------------- #
# Envelope
# --------------------------------------------------------------------------- #
def envelope(storage_fsw):
    """
    Excursion envelope for a storage depth (fsw).

    Returns a dict (all depths/distances in fsw):
        storage_fsw
        down_dist_fsw, down_row_fsw, max_desc_fsw
        up_dist_fsw,   up_row_fsw,   max_asc_fsw
        in_range   : bool  (storage within the combined table domain)
    """
    storage_fsw = float(storage_fsw)
    in_range = (MIN_STORAGE_FSW - 1e-9) <= storage_fsw <= (MAX_STORAGE_FSW + 1e-9)

    down_row, down_dist = _downward_row(storage_fsw)
    up_row, up_dist = _upward_row(storage_fsw)

    return {
        "storage_fsw": storage_fsw,
        "down_dist_fsw": float(down_dist),
        "down_row_fsw": float(down_row),
        "max_desc_fsw": storage_fsw + down_dist,
        "up_dist_fsw": float(up_dist),
        "up_row_fsw": float(up_row),
        "max_asc_fsw": max(0.0, storage_fsw - up_dist),
        "in_range": in_range,
    }


def upward_formula_fsw(storage_fsw):
    """
    The 1989 U.S. Navy empirical upward-excursion distance (fsw), for reference/
    cross-check against the tabulated Table 13-8 values. Not used by envelope().
    """
    from math import sqrt
    d1 = float(storage_fsw)
    return (sqrt(0.1574 * d1 + 6.197) - 1.0) / 0.0787
