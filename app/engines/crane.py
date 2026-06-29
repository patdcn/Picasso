"""
Crane load-chart engine for the DSV Picasso 140 t main winch (GPOKa 5000-140-36).

Pure maths, no Dash imports. Data comes from per-mode .npz grids (50x50) extracted
from the MacGregor .mat files. Each grid is indexed [folding_row, main_col].

Fields per mode:
  VMm     main jib angle grid    [deg]  (varies along columns, 0..84)
  VFm     folding jib angle grid [deg]  (varies along rows, 0..102)
  TP_y_m  outreach / radius      [m]    (horizontal dist from slew centre to tip)
  TP_z_m  height above pedestal flange [m]
  Pmax    displayed SWL          [t]    (the colour-bar value; validated vs booklet)
  Cdyn_m  dynamic amplification factor (DAF)
  StMjib  main-jib stiffness     [t/m]
  Cat     limiting-component code (int 1..5)

Height datum: the tool reports height above the Picasso main deck, which sits
6.0 m below the slew bearing. The booklet TP_z_m is referenced to the pedestal
flange; DECK_OFFSET converts to "above main deck".
"""
import os
import json
import numpy as np

# Data lives bundled in the repo; a volume copy at /data/tools/crane overrides it.
_REPO_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "crane")
_VOLUME_DIR = os.getenv("CRANE_DATA_DIR", "/data/tools/crane")

# Pedestal flange -> Picasso main deck. TP_z_m is referenced to the pedestal flange;
# the MacGregor app references height to the main deck. The flange-to-deck offset is
# 8.75 m, confirmed against two MacGregor readouts (harbour Height 12.87 at TP_z 4.12,
# and STS Height 26.08 at TP_z 17.33 — both give exactly 8.75). The booklet's "main
# deck 6000 mm below slew bearing" is a different reference (slew bearing, not flange).
DECK_OFFSET = 8.75

# Crane linkage geometry, derived by least-squares fit of a two-jib kinematic model
# to the .mat tip positions (RMS tip error 0.18 m across the envelope). Coordinates
# are in the booklet frame: radius from slew centre, height above pedestal flange.
# tip = pivot + L1*dir(main+PM) + L2*dir(main+PM-(pi-fold)+PF)
LINKAGE = {
    "pivot_r": 0.99,
    "pivot_z": 4.55,   # above pedestal flange
    "L1": 25.55,       # main jib length [m]
    "L2": 11.90,       # folding jib length [m]
    "phase_main": 0.002,
    "phase_fold": 0.447,
}


def linkage_points(main_deg, fold_deg):
    """
    Return the schematic joint coordinates (radius, height-above-deck) for the
    pedestal pivot, the main/folding elbow, and the jib tip, at the given angles.
    Heights are referenced to the Picasso main deck (pivot_z is above the flange,
    so DECK_OFFSET is added). Used to draw the moving crane schematic.
    """
    import math
    g = LINKAGE
    am = math.radians(main_deg)
    a1 = am + g["phase_main"]
    a2 = am + g["phase_main"] - (math.pi - math.radians(fold_deg)) + g["phase_fold"]
    pr, pz = g["pivot_r"], g["pivot_z"] + DECK_OFFSET
    er = pr + g["L1"] * math.cos(a1)
    ez = pz + g["L1"] * math.sin(a1)
    tr = er + g["L2"] * math.cos(a2)
    tz = ez + g["L2"] * math.sin(a2)
    return {
        "pivot": (pr, pz),
        "elbow": (er, ez),
        "tip": (tr, tz),
        "deck_z": DECK_OFFSET - DECK_OFFSET,   # main deck is z=0 in deck frame
        "pedestal_base": (pr, 0.0),
    }

# Limiting-component code -> label. Code 2 = Main Hinge is confirmed against two
# MacGregor readouts at known positions. The others are labelled by character
# (refine the strings here if exact MacGregor names become available).
CAT_LABELS = {
    1: "Rated-load cap",
    2: "Main Hinge",
    3: "Structural limit",
    4: "Dynamic limit (STS)",
    5: "Flexibility limit",
}


def _data_dir():
    """Prefer the volume copy if present, else the bundled repo copy."""
    if os.path.isdir(_VOLUME_DIR) and os.path.exists(os.path.join(_VOLUME_DIR, "harbour.npz")):
        return _VOLUME_DIR
    return _REPO_DIR


def list_modes():
    """Return the lift-mode manifest (ordered)."""
    with open(os.path.join(_data_dir(), "modes.json")) as fh:
        return json.load(fh)


_CACHE = {}


def load_mode(key):
    """Load and cache a mode's grids. Returns a dict of numpy arrays."""
    if key in _CACHE:
        return _CACHE[key]
    path = os.path.join(_data_dir(), f"{key}.npz")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Crane data for mode '{key}' not found at {path}")
    z = np.load(path)
    d = {k: z[k] for k in z.files}
    d["main_axis"] = d["VMm"][0, :]      # 50 main angles 0..84
    d["fold_axis"] = d["VFm"][:, 0]      # 50 folding angles 0..102
    d["height_deck"] = d["TP_z_m"] + DECK_OFFSET  # height above Picasso main deck
    _CACHE[key] = d
    return d


# --------------------------------------------------------------------------- #
# Load-geometry offset
# --------------------------------------------------------------------------- #
def hook_drop(wire_a=0.0, rigging_c=0.0, load_d=0.0):
    """
    Vertical drop from the crane tip down to the bottom of the load, used to
    compute the 'lowest point' height. Mirrors the MacGregor load-geometry panel:
      a = wire length (tip -> top of hook)
      c = rigging height (bottom of hook -> top of load)
      d = load height
    Lowest point = tip height - (a + c + d).  (hook height b is built into the data.)
    """
    return float(wire_a) + float(rigging_c) + float(load_d)


# --------------------------------------------------------------------------- #
# Query by jib angles (exact)
# --------------------------------------------------------------------------- #
def query_angles(key, main_deg, fold_deg, geom=None):
    """
    Look up the crane state at a main/folding jib angle pair (nearest grid node).
    Returns a readout dict. geom = dict(wire_a, rigging_c, load_d) optional.
    """
    d = load_mode(key)
    c = int(np.argmin(np.abs(d["main_axis"] - float(main_deg))))
    r = int(np.argmin(np.abs(d["fold_axis"] - float(fold_deg))))
    return _readout(d, r, c, geom)


# --------------------------------------------------------------------------- #
# Query by radius + height (ambiguous -> rule)
# --------------------------------------------------------------------------- #
def query_point(key, radius, height_above_deck, rule="best", geom=None):
    """
    Find a crane state reaching (radius, height_above_deck).

    rule = "best"    -> among nodes near the point, the one with the highest SWL
    rule = "nearest" -> the single nearest valid grid node (geometrically closest)

    Returns a readout dict, or None if the point is far outside the envelope.
    """
    d = load_mode(key)
    R = d["TP_y_m"]
    H = d["height_deck"]
    P = d["Pmax"]

    dist = np.sqrt((R - float(radius)) ** 2 + (H - float(height_above_deck)) ** 2)
    valid = np.isfinite(dist) & np.isfinite(P)
    if not valid.any():
        return None

    if rule == "nearest":
        idx = np.unravel_index(np.nanargmin(np.where(valid, dist, np.inf)), dist.shape)
        r, c = int(idx[0]), int(idx[1])
        return _readout(d, r, c, geom, snapped=True)

    # rule == "best": consider nodes within a small radius of the click, pick max SWL.
    # Tolerance scales with the grid spacing so we always capture a few candidates.
    tol = max(0.75, 1.5 * _median_spacing(R, H))
    near = valid & (dist <= tol)
    if not near.any():
        # nothing within tolerance: fall back to nearest node
        idx = np.unravel_index(np.nanargmin(np.where(valid, dist, np.inf)), dist.shape)
        r, c = int(idx[0]), int(idx[1])
        return _readout(d, r, c, geom, snapped=True)
    Pn = np.where(near, P, -np.inf)
    idx = np.unravel_index(np.nanargmax(Pn), Pn.shape)
    r, c = int(idx[0]), int(idx[1])
    return _readout(d, r, c, geom)


def _median_spacing(R, H):
    """Approximate grid node spacing in metres, for the best-lift tolerance."""
    dr = np.diff(R, axis=1)
    dz = np.diff(H, axis=0)
    vals = np.concatenate([np.abs(dr[np.isfinite(dr)]).ravel(),
                           np.abs(dz[np.isfinite(dz)]).ravel()])
    return float(np.median(vals)) if vals.size else 1.0


# --------------------------------------------------------------------------- #
# Readout assembly
# --------------------------------------------------------------------------- #
def _readout(d, r, c, geom, snapped=False):
    geom = geom or {}
    swl = float(d["Pmax"][r, c])
    radius = float(d["TP_y_m"][r, c])
    height = float(d["height_deck"][r, c])
    daf = float(d["Cdyn_m"][r, c])
    stiff = float(d["Ctot_m"][r, c]) if np.isfinite(d["Ctot_m"][r, c]) else None
    cat = int(d["Cat"][r, c])
    drop = hook_drop(geom.get("wire_a", 0.0), geom.get("rigging_c", 0.0), geom.get("load_d", 0.0))
    return {
        "main_deg": round(float(d["main_axis"][c]), 2),
        "fold_deg": round(float(d["fold_axis"][r]), 2),
        "swl_t": round(swl, 1),
        "radius_m": round(radius, 2),
        "height_m": round(height, 2),
        "daf": round(daf, 2),
        "stiffness_tm": round(stiff, 1) if stiff is not None else None,
        "limit_code": cat,
        "limit_label": CAT_LABELS.get(cat, f"Code {cat}"),
        "lowest_point_m": round(height - drop, 2),
        "snapped": snapped,
    }


# --------------------------------------------------------------------------- #
# Plot data: contour field + envelope
# --------------------------------------------------------------------------- #
def contour_field(key):
    """
    Raw scattered grid for the SWL field (50x50 curvilinear). Mostly used by
    contour_grid() below; kept for callers that want the native nodes.
    """
    d = load_mode(key)
    return {
        "radius": d["TP_y_m"],
        "height": d["height_deck"],
        "swl": d["Pmax"],
        "swl_max": float(np.nanmax(d["Pmax"])),
    }


_SPAN_CACHE = {}
_GRID_CACHE = {}


def _envelope_mask(key, n=160):
    """A boolean reachability grid (regular radius x height) for the mode, cached."""
    g = contour_grid(key, nx=n, ny=n)
    import numpy as np
    return g["x"], g["y"], np.isfinite(g["z"])


def reachable_radius_span(key, height):
    """Min/max radius the crane can reach at the given height-above-deck, or None."""
    import numpy as np
    x, y, mask = _envelope_mask(key)
    j = int(np.argmin(np.abs(y - float(height))))
    row = mask[j, :]
    if not row.any():
        return None
    cols = np.where(row)[0]
    return float(x[cols.min()]), float(x[cols.max()])


def reachable_height_span(key, radius):
    """Min/max height the crane can reach at the given radius, or None."""
    import numpy as np
    x, y, mask = _envelope_mask(key)
    i = int(np.argmin(np.abs(x - float(radius))))
    col = mask[:, i]
    if not col.any():
        return None
    rows = np.where(col)[0]
    return float(y[rows.min()]), float(y[rows.max()])


def full_span(key):
    """Overall radius and height envelope bounds for a mode."""
    import numpy as np
    x, y, mask = _envelope_mask(key)
    cols = np.where(mask.any(axis=0))[0]
    rows = np.where(mask.any(axis=1))[0]
    return {
        "r_min": float(x[cols.min()]), "r_max": float(x[cols.max()]),
        "h_min": float(y[rows.min()]), "h_max": float(y[rows.max()]),
    }


def contour_grid(key, nx=140, ny=140):
    """
    Resample the curvilinear 50x50 SWL field onto a regular (radius x height) grid
    so Plotly's Contour renders it instantly. Pure numpy (no scipy) so the page has
    no heavy runtime dependency. Points outside the data hull are NaN, which gives
    the natural load-chart envelope. Cached per mode.

    Method: the native grid is a structured quad mesh in (R, H). For each regular
    target cell we find the native quad containing it and bilinearly interpolate
    SWL. To keep it simple and fast with numpy only, we rasterise each native quad
    onto the regular grid (scan-fill) using barycentric interpolation over the two
    triangles of the quad.
    """
    ck = (key, nx, ny)
    if ck in _GRID_CACHE:
        return _GRID_CACHE[ck]

    d = load_mode(key)
    R = d["TP_y_m"]
    H = d["height_deck"]
    P = d["Pmax"]

    r_min, r_max = float(np.nanmin(R)), float(np.nanmax(R))
    h_min, h_max = float(np.nanmin(H)), float(np.nanmax(H))
    xi = np.linspace(r_min, r_max, nx)
    yi = np.linspace(h_min, h_max, ny)
    Z = np.full((ny, nx), np.nan)

    inv_dx = (nx - 1) / (r_max - r_min)
    inv_dy = (ny - 1) / (h_max - h_min)

    def _fill_tri(p0, p1, p2, v0, v1, v2):
        # rasterise triangle (p=(r,h)) into Z with barycentric-interpolated SWL
        rs = [p0[0], p1[0], p2[0]]
        hs = [p0[1], p1[1], p2[1]]
        cmin = max(int(np.floor((min(rs) - r_min) * inv_dx)), 0)
        cmax = min(int(np.ceil((max(rs) - r_min) * inv_dx)), nx - 1)
        rmin_ = max(int(np.floor((min(hs) - h_min) * inv_dy)), 0)
        rmax_ = min(int(np.ceil((max(hs) - h_min) * inv_dy)), ny - 1)
        if cmax < cmin or rmax_ < rmin_:
            return
        denom = ((p1[1] - p2[1]) * (p0[0] - p2[0]) + (p2[0] - p1[0]) * (p0[1] - p2[1]))
        if abs(denom) < 1e-12:
            return
        for rr in range(rmin_, rmax_ + 1):
            hy = yi[rr]
            for cc in range(cmin, cmax + 1):
                rx = xi[cc]
                a = ((p1[1] - p2[1]) * (rx - p2[0]) + (p2[0] - p1[0]) * (hy - p2[1])) / denom
                b = ((p2[1] - p0[1]) * (rx - p2[0]) + (p0[0] - p2[0]) * (hy - p2[1])) / denom
                c = 1 - a - b
                if a >= -1e-9 and b >= -1e-9 and c >= -1e-9:
                    Z[rr, cc] = a * v0 + b * v1 + c * v2

    ni, nj = R.shape
    for i in range(ni - 1):
        for j in range(nj - 1):
            p00 = (R[i, j], H[i, j]); v00 = P[i, j]
            p01 = (R[i, j + 1], H[i, j + 1]); v01 = P[i, j + 1]
            p10 = (R[i + 1, j], H[i + 1, j]); v10 = P[i + 1, j]
            p11 = (R[i + 1, j + 1], H[i + 1, j + 1]); v11 = P[i + 1, j + 1]
            if not (np.isfinite(v00) and np.isfinite(v01) and np.isfinite(v10) and np.isfinite(v11)):
                continue
            _fill_tri(p00, p01, p11, v00, v01, v11)
            _fill_tri(p00, p11, p10, v00, v11, v10)

    out = {"x": xi, "y": yi, "z": Z, "swl_max": float(np.nanmax(P))}
    _GRID_CACHE[ck] = out
    return out
