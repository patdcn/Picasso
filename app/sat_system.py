"""
SAT system definitions (physical plant) for the saturation gas calculator.

A "system" is a named saturation spread. Its floodable volume is built up from
named components (chambers, TUP, bell, HRL, hubs...) each with an include
toggle, alongside bell volume, bell configuration (single/twin) and default
operating depths + diver count. Definitions are stored as JSON documents on the
data volume via app.store, so the component list stays free-form and survives
redeploys.

Scope split (kept deliberately clean):
  - system *definitions* live here (this module, /admin/sat-system);
  - gas-calc *coefficients* are tunable parameters in app/params.py;
  - per-job figures (deco time, etc.) are entered on the gas page itself.
"""
import re

from app.store import JSONStore

_store = JSONStore("sat_system.db", env_var="SAT_SYSTEM_DB")

# Component template mirrors the ISS "System volume" build-up so a fresh system
# starts with the usual spread items; every volume is editable and rows can be
# added or removed on the admin page.
DEFAULT_COMPONENTS = [
    {"label": "Chamber 1", "vol_m3": 27.0, "include": True},
    {"label": "Chamber 2", "vol_m3": 27.0, "include": True},
    {"label": "Chamber 3", "vol_m3": 20.0, "include": True},
    {"label": "TUP", "vol_m3": 14.6, "include": True},
    {"label": "Bell 1", "vol_m3": 6.4, "include": True},
    {"label": "HRL & escape manway", "vol_m3": 7.3, "include": True},
    {"label": "Hubs, spools & regens", "vol_m3": 2.5, "include": True},
]

BELL_CONFIGS = ["single", "twin"]


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return s or "system"


def blank_system():
    """A fresh, unsaved system dict for the 'new system' path."""
    return {
        "name": "",
        "components": [dict(c) for c in DEFAULT_COMPONENTS],
        "bell_vol_m3": 6.4,
        "bell_config": "single",
        "default_storage_m": 27.0,
        "default_working_m": 40.0,
        "divers": 9,
    }


def init_db():
    _store.init_db()
    # Seed one system so the page and admin have something on a fresh volume.
    if not _store.list_ids():
        seed = blank_system()
        seed["name"] = "DSV Picasso SAT System"
        _store.put("picasso", seed)


def system_volume(system):
    """Total floodable volume = sum of the included components (m3)."""
    total = 0.0
    for c in (system or {}).get("components", []):
        if c.get("include", True):
            try:
                total += float(c.get("vol_m3") or 0)
            except (TypeError, ValueError):
                pass
    return round(total, 2)


def list_systems():
    return _store.list()


def get_system(id_):
    return _store.get(id_)


def new_id(name):
    """A unique slug id for a new system named `name`."""
    base = _slug(name)
    existing = set(_store.list_ids())
    candidate, n = base, 2
    while candidate in existing:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def save_system(id_, data):
    return _store.put(id_ or new_id(data.get("name")), data)


def delete_system(id_):
    _store.delete(id_)
