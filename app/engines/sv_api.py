"""
SeaVantage Insight API client for the Fleet page.

Confirmed endpoints (Basic Auth, envelope {code, message, error, response}):
  POST /ship/match   body [{"imoNo": "...", "shipName": "..."}]
                     -> [{imoNo, shipName, shipId, result}]
                        result: SUCCESS | IMO_NO_NOT_FOUND | SHIP_NAME_NOT_FOUND
                        (shipId only returned when BOTH imo and name match)
  POST /fleet        body ["<shipId>", ...]  -> 204 (register in workspace)
  DELETE /fleet      body ["<shipId>", ...]  -> 204 (deregister; only allowed
                                                7 days after registration)

Rate limit: 100 req/min (we do a handful per user action).
"""
import os

import requests

SV_BASE_URL = os.environ.get("SV_BASE_URL", "").rstrip("/")
SV_USER = os.environ.get("SV_USER", "")
SV_PASSWORD = os.environ.get("SV_PASSWORD", "")
SV_MAX_SHIPS = int(os.environ.get("SV_MAX_SHIPS", "250"))


class SvApiError(RuntimeError):
    pass


def _session():
    if not (SV_BASE_URL and SV_USER and SV_PASSWORD):
        raise SvApiError(
            "SeaVantage API is not configured: set SV_BASE_URL, SV_USER and "
            "SV_PASSWORD in the portal environment (Dokploy + compose pass-through)."
        )
    s = requests.Session()
    s.auth = (SV_USER, SV_PASSWORD)
    s.headers["Accept"] = "application/json"
    return s


def _check(r):
    if r.status_code == 401:
        raise SvApiError("401 Unauthorized: check SV_USER / SV_PASSWORD")
    if r.status_code == 429:
        raise SvApiError("429 rate limited by SeaVantage; try again in a minute")
    if r.status_code == 204:
        return None
    try:
        data = r.json()
    except ValueError:
        r.raise_for_status()
        raise SvApiError(f"unexpected non-JSON response (HTTP {r.status_code})")
    if isinstance(data, dict) and data.get("error"):
        raise SvApiError(f"API error {data.get('code')}: {data.get('message')}")
    r.raise_for_status()
    return data.get("response") if isinstance(data, dict) else data


def match(pairs):
    """pairs: [{'imoNo': '9698783', 'shipName': 'PICASSO'}] ->
    [{'imoNo', 'shipName', 'shipId', 'result'}]"""
    with _session() as s:
        r = s.post(SV_BASE_URL + "/ship/match", json=pairs, timeout=30)
        return _check(r) or []


def register(ship_ids):
    with _session() as s:
        r = s.post(SV_BASE_URL + "/fleet", json=list(ship_ids), timeout=30)
        _check(r)


def deregister(ship_ids):
    with _session() as s:
        r = s.delete(SV_BASE_URL + "/fleet", json=list(ship_ids), timeout=30)
        _check(r)


def snapshot():
    """GET /fleet/snapshot: every vessel registered in the SVMP workspace,
    with its latest position (may be null)."""
    with _session() as s:
        r = s.get(SV_BASE_URL + "/fleet/snapshot", timeout=30)
        return _check(r) or []
