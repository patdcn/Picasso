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

# Pedestal flange -> Picasso main deck. Main deck is 6 m below slew bearing; the
# booklet's "boom tip range" notes height is measured from slew-ring centre with
# main deck 6000 mm below. TP_z_m is referenced such that adding 6.0 gives height
# above main deck.
DECK_OFFSET = 6.0

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


_GRID_CACHE = {}


def contour_grid(key, nx=120, ny=120):
    """
    Resample the curvilinear 50x50 SWL field onto a regular (radius x height) grid
    so Plotly's Contour renders it instantly. Points outside the data hull are NaN,
    which gives the natural load-chart envelope. Cached per mode.
    """
    ck = (key, nx, ny)
    if ck in _GRID_CACHE:
        return _GRID_CACHE[ck]
    from scipy.interpolate import griddata  # server-side, once per mode
    d = load_mode(key)
    R = d["TP_y_m"].ravel()
    H = d["height_deck"].ravel()
    P = d["Pmax"].ravel()
    xi = np.linspace(float(np.nanmin(R)), float(np.nanmax(R)), nx)
    yi = np.linspace(float(np.nanmin(H)), float(np.nanmax(H)), ny)
    Xi, Yi = np.meshgrid(xi, yi)
    Zi = griddata((R, H), P, (Xi, Yi), method="linear")
    out = {"x": xi, "y": yi, "z": Zi, "swl_max": float(np.nanmax(d["Pmax"]))}
    _GRID_CACHE[ck] = out
    return out
