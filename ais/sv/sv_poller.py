"""
SeaVantage poller - second AIS source for the DSV Picasso vessel tracker
=========================================================================
Runs alongside the aisstream websocket collector and fills its biggest gap:
vessels beyond terrestrial AIS range (satellite-backed positions).

Every POLL_SECONDS (default 900 = 15 min):
  1. Load active fleet (imo, mmsi) from the shared `fleet` table.
  2. Resolve missing SeaVantage shipIds via GET /ship/search (cached in
     `sv_ship`; each vessel is resolved once).
  3. GET /ship/snapshot for all known shipIds (batched, with per-ship
     fallback) and store results:
       positions : INSERT with source='seavantage'; the unique index
                   (mmsi, ts, source) absorbs unchanged repeats, so a
                   vessel that did not move/update costs no extra rows.
       latest    : conditional upsert - only when this fix is NEWER than
                   what is already there, so a stale satellite position
                   never overwrites a fresh terrestrial one.
       voyage    : change-detection on (callsign, destination, eta,
                   draught), shared semantics with the aisstream collector
                   (ETA normalised to the same 'MM-DD HH:MM' format) so the
                   two sources do not ping-pong duplicate rows.

Authentication: Basic Auth (SVMP account/password), per SeaVantage docs.

Environment:
  AIS_DSN          postgres DSN (shared with the aisstream collector)
  SV_USER          SeaVantage account
  SV_PASSWORD      SeaVantage password
  SV_BASE_URL      default https://api.seavantage.com
  SV_SEARCH_PATH   default /ship/search      (query param SV_SEARCH_PARAM)
  SV_SEARCH_PARAM  default imoNo
  SV_SNAPSHOT_PATH default /ship/snapshot    (query param SV_SNAPSHOT_PARAM)
  SV_SNAPSHOT_PARAM default shipId
  POLL_SECONDS     default 900
  SV_BATCH         default 20 shipIds per snapshot call

If the endpoint paths/params in your Postman docs differ from these
defaults, override them via env vars - no code change needed. Use
sv_probe.py to verify quickly.
"""

import logging
import os
import re
import sys
import time
from datetime import datetime, timezone

import psycopg2
import requests

AIS_DSN      = os.environ.get("AIS_DSN", "")
SV_USER      = os.environ.get("SV_USER", "")
SV_PASSWORD  = os.environ.get("SV_PASSWORD", "")
SV_BASE_URL  = os.environ.get("SV_BASE_URL", "https://api.seavantage.com").rstrip("/")
SEARCH_PATH  = os.environ.get("SV_SEARCH_PATH", "/ship/search")
SEARCH_PARAM = os.environ.get("SV_SEARCH_PARAM", "imoNo")
SNAP_PATH    = os.environ.get("SV_SNAPSHOT_PATH", "/ship/snapshot")
SNAP_PARAM   = os.environ.get("SV_SNAPSHOT_PARAM", "shipId")
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "900"))
SV_BATCH     = int(os.environ.get("SV_BATCH", "20"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("sv-poller")


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable)
# ---------------------------------------------------------------------------
def normalise_eta(raw):
    """SeaVantage aisEta 'MMDDHHmm' -> 'MM-DD HH:MM' (same format the
    aisstream collector stores), honouring AIS not-available conventions."""
    if not raw:
        return None
    raw = str(raw).strip()
    if not re.fullmatch(r"\d{8}", raw):
        return None
    month, day = int(raw[0:2]), int(raw[2:4])
    hour, minute = int(raw[4:6]), int(raw[6:8])
    if month == 0 or day == 0 or month > 12 or day > 31:
        return None
    if hour >= 24:
        hour = 0
    if minute >= 60:
        minute = 0
    return f"{month:02d}-{day:02d} {hour:02d}:{minute:02d}"


def clean_text(v):
    v = (str(v) if v is not None else "").replace("@", "").strip()
    return v or None


def parse_iso_ts(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_snapshot_item(item):
    """One {ship:{...}, position:{...}} element -> (pos_dict, voyage_dict)
    or (None, None) if unusable. Tolerates flat items without 'ship'."""
    ship = item.get("ship", item) or {}
    pos = item.get("position") or {}
    if not pos:
        return None, None

    mmsi = pos.get("mmsi") or ship.get("mmsi")
    lat, lon = pos.get("latitude"), pos.get("longitude")
    ts = parse_iso_ts(pos.get("timestamp"))
    if mmsi is None or lat is None or lon is None or ts is None:
        return None, None
    lat, lon = float(lat), float(lon)
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return None, None
    if abs(lat) < 1e-9 and abs(lon) < 1e-9:
        return None, None

    heading = pos.get("trueHeading")
    if heading is not None and int(heading) >= 511:
        heading = None
    sog = pos.get("speedOverGround")
    if sog is not None and float(sog) >= 102.2:
        sog = None
    cog = pos.get("courseOverGround")
    if cog is not None and float(cog) >= 360.0:
        cog = None

    draught = None
    for key in ("maxDraught", "draught", "aisDraught", "maximumStaticDraught"):
        if pos.get(key) is not None:
            draught = pos[key]
            break
        if ship.get(key) is not None:
            draught = ship[key]
            break
    if draught is not None and float(draught) <= 0:
        draught = None

    p = {
        "mmsi": int(mmsi),
        "ts": ts,
        "lat": lat,
        "lon": lon,
        "sog": float(sog) if sog is not None else None,
        "cog": float(cog) if cog is not None else None,
        "heading": int(heading) if heading is not None else None,
        "nav_status": (int(pos["nvgStatus"])
                       if pos.get("nvgStatus") is not None else None),
        "ship_name": clean_text(pos.get("shipName") or ship.get("shipName")),
    }
    v = {
        "mmsi": p["mmsi"],
        "ts": ts,
        "callsign": clean_text(pos.get("callSign") or ship.get("callSign")),
        "destination": clean_text(pos.get("aisDestination")
                                  or ship.get("destination")),
        "eta": normalise_eta(pos.get("aisEta")),
        "draught": float(draught) if draught is not None else None,
        "ship_name": p["ship_name"],
    }
    return p, v


def voyage_key(v):
    """Same normalisation as the aisstream collector - shared semantics."""
    dest = (v["destination"] or "").upper().strip()
    return (v["callsign"] or "", dest, v["eta"] or "",
            round(v["draught"], 1) if v["draught"] is not None else None)


# ---------------------------------------------------------------------------
# SeaVantage API
# ---------------------------------------------------------------------------
class SvError(RuntimeError):
    pass


def api_get(session, path, params):
    url = SV_BASE_URL + path
    r = session.get(url, params=params, timeout=30)
    if r.status_code == 401:
        raise SvError("401 Unauthorized - check SV_USER / SV_PASSWORD")
    if r.status_code == 429:
        raise SvError("429 rate limited")
    r.raise_for_status()
    data = r.json()
    # SVMP envelope: {code, message, error, response}
    if isinstance(data, dict) and "response" in data:
        if data.get("error") or (data.get("code") not in (None, 200)):
            raise SvError(f"API error {data.get('code')}: {data.get('message')}")
        return data["response"]
    return data


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def q(sql, params=None, fetch=False):
    with psycopg2.connect(AIS_DSN, connect_timeout=10) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if fetch else None


def load_fleet():
    return q("SELECT imo, mmsi, name FROM fleet WHERE active AND mmsi IS NOT NULL",
             fetch=True)


def load_ship_ids():
    return {imo: (ship_id, mmsi) for imo, ship_id, mmsi in
            q("SELECT imo, ship_id, mmsi FROM sv_ship", fetch=True)}


def load_last_voyages():
    out = {}
    for mmsi, callsign, dest, eta, draught in q(
        """SELECT DISTINCT ON (mmsi) mmsi, callsign, destination, eta, draught
           FROM voyage ORDER BY mmsi, ts DESC, ctid DESC""", fetch=True):
        out[mmsi] = (callsign or "", (dest or "").upper().strip(), eta or "",
                     round(draught, 1) if draught is not None else None)
    return out


def insert_position(p):
    q("""INSERT INTO positions (ts, mmsi, lat, lon, sog, cog, heading, nav_status, source)
         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'seavantage')
         ON CONFLICT (mmsi, ts, source) DO NOTHING""",
      (p["ts"], p["mmsi"], p["lat"], p["lon"], p["sog"], p["cog"],
       p["heading"], p["nav_status"]))


def upsert_latest_if_newer(p, v):
    """Insert vessel into latest, or update ONLY when this fix is newer than
    the stored one - protects fresh terrestrial data from stale satellite."""
    q("""INSERT INTO latest (mmsi, ts, lat, lon, sog, cog, heading, nav_status,
                             ship_name, callsign, destination, eta, draught)
         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
         ON CONFLICT (mmsi) DO UPDATE SET
           ts=EXCLUDED.ts, lat=EXCLUDED.lat, lon=EXCLUDED.lon,
           sog=EXCLUDED.sog, cog=EXCLUDED.cog, heading=EXCLUDED.heading,
           nav_status=EXCLUDED.nav_status,
           ship_name=COALESCE(EXCLUDED.ship_name, latest.ship_name),
           callsign=COALESCE(EXCLUDED.callsign, latest.callsign),
           destination=COALESCE(EXCLUDED.destination, latest.destination),
           eta=COALESCE(EXCLUDED.eta, latest.eta),
           draught=COALESCE(EXCLUDED.draught, latest.draught)
         WHERE latest.ts IS NULL OR EXCLUDED.ts > latest.ts""",
      (p["mmsi"], p["ts"], p["lat"], p["lon"], p["sog"], p["cog"],
       p["heading"], p["nav_status"], p["ship_name"],
       v["callsign"], v["destination"], v["eta"], v["draught"]))


def insert_voyage(v):
    q("""INSERT INTO voyage (ts, mmsi, callsign, destination, eta, draught,
                             ship_name, source)
         VALUES (%s,%s,%s,%s,%s,%s,%s,'seavantage')""",
      (v["ts"], v["mmsi"], v["callsign"], v["destination"], v["eta"],
       v["draught"], v["ship_name"]))


# ---------------------------------------------------------------------------
# Poll cycle
# ---------------------------------------------------------------------------
def resolve_ship_ids(session, fleet, known):
    """Look up SeaVantage shipIds for fleet vessels not yet in sv_ship."""
    for imo, mmsi, name in fleet:
        if imo in known:
            continue
        try:
            resp = api_get(session, SEARCH_PATH, {SEARCH_PARAM: str(imo)})
        except (SvError, requests.RequestException) as exc:
            log.warning("search %s (%s) failed: %s", name, imo, exc)
            continue
        items = resp if isinstance(resp, list) else [resp]
        match = None
        for it in items:
            ship = it.get("ship", it) if isinstance(it, dict) else {}
            if str(ship.get("imoNo", "")).strip() == str(imo):
                match = ship
                break
        if match is None and len(items) == 1 and isinstance(items[0], dict):
            match = items[0].get("ship", items[0])
        if not match or not match.get("shipId"):
            log.warning("no shipId match for %s (IMO %s)", name, imo)
            continue
        q("""INSERT INTO sv_ship (imo, mmsi, ship_id, ship_name)
             VALUES (%s,%s,%s,%s)
             ON CONFLICT (imo) DO UPDATE SET ship_id=EXCLUDED.ship_id,
                 mmsi=EXCLUDED.mmsi, ship_name=EXCLUDED.ship_name,
                 matched_at=now()""",
          (imo, mmsi, match["shipId"], clean_text(match.get("shipName")) or name))
        known[imo] = (match["shipId"], mmsi)
        log.info("resolved %s (IMO %s) -> shipId %s", name, imo, match["shipId"])
        time.sleep(0.3)  # be polite on the search endpoint


def fetch_snapshots(session, ship_ids):
    """Batched snapshot fetch with per-ship fallback."""
    items = []
    for i in range(0, len(ship_ids), SV_BATCH):
        batch = ship_ids[i:i + SV_BATCH]
        try:
            resp = api_get(session, SNAP_PATH, {SNAP_PARAM: ",".join(batch)})
            items.extend(resp if isinstance(resp, list) else [resp])
            continue
        except (SvError, requests.RequestException) as exc:
            log.warning("batch snapshot failed (%s); falling back per ship", exc)
        for sid in batch:
            try:
                resp = api_get(session, SNAP_PATH, {SNAP_PARAM: sid})
                items.extend(resp if isinstance(resp, list) else [resp])
            except (SvError, requests.RequestException) as exc:
                log.warning("snapshot %s failed: %s", sid, exc)
            time.sleep(0.3)
    return items


def cycle(session, voyage_last):
    fleet = load_fleet()
    known = load_ship_ids()
    resolve_ship_ids(session, fleet, known)
    ship_ids = [sid for sid, _ in known.values()]
    if not ship_ids:
        log.warning("no shipIds resolved yet; nothing to poll")
        return
    fleet_mmsis = {m for _, m, _ in fleet}

    items = fetch_snapshots(session, ship_ids)
    stored = updated = voyages = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        p, v = parse_snapshot_item(item)
        if p is None or p["mmsi"] not in fleet_mmsis:
            continue
        insert_position(p)
        stored += 1
        upsert_latest_if_newer(p, v)
        updated += 1
        key = voyage_key(v)
        has_data = any(key[:3]) or key[3] is not None
        if has_data and voyage_last.get(p["mmsi"]) != key:
            voyage_last[p["mmsi"]] = key
            insert_voyage(v)
            voyages += 1
    log.info("cycle done: %d snapshot items, %d positions written (dupes "
             "absorbed by index), %d voyage changes", len(items), stored, voyages)


def main():
    missing = [n for n, v in [("AIS_DSN", AIS_DSN), ("SV_USER", SV_USER),
                              ("SV_PASSWORD", SV_PASSWORD)] if not v]
    if missing:
        log.error("missing env vars: %s", ", ".join(missing))
        sys.exit(1)
    log.info("starting: base=%s poll=%ds batch=%d", SV_BASE_URL, POLL_SECONDS,
             SV_BATCH)
    session = requests.Session()
    session.auth = (SV_USER, SV_PASSWORD)
    session.headers["Accept"] = "application/json"

    voyage_last = None
    backoff = 60
    while True:
        started = time.time()
        try:
            if voyage_last is None:
                voyage_last = load_last_voyages()
            cycle(session, voyage_last)
            backoff = 60
        except psycopg2.OperationalError as exc:
            log.warning("database unavailable: %s", exc)
            voyage_last = None   # reload state once DB is back
        except Exception:
            log.exception("cycle failed; retrying next interval")
            backoff = min(backoff * 2, POLL_SECONDS)
        elapsed = time.time() - started
        time.sleep(max(30.0, POLL_SECONDS - elapsed))


if __name__ == "__main__":
    main()
