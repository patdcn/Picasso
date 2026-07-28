"""
SeaVantage poller - second AIS source for the DSV Picasso vessel tracker
=========================================================================
Runs alongside the aisstream websocket collector and fills its biggest gap:
vessels beyond terrestrial AIS range (satellite-backed positions).

Confirmed against the Insight SeaVantage OpenAPI spec:
- Basic Auth (SVMP account/password)
- GET {SV_BASE_URL}/fleet/snapshot  -> [{shipId, position:{...}}] for ALL
  vessels registered in the user's SVMP workspace (optionally filtered by
  categoryId). ONE request per cycle covers the whole fleet.
- Envelope: {code, message, error, timestamp, response}
- 429 responses carry a Retry-After header, which is honoured.

Prerequisite: register the vessels once in the SVMP web UI (workspace
fleet). The poller matches returned positions against our own `fleet`
table by IMO (fallback MMSI); anything else in the workspace is ignored.

Storage per cycle:
  positions : INSERT with source='seavantage'; unique index (mmsi, ts,
              source) absorbs repeats when a vessel has no fresh fix.
  latest    : conditional upsert - only when this fix is NEWER than the
              stored one, so stale satellite never overwrites fresh
              terrestrial data.
  voyage    : change-detection on (callsign, destination, eta, draught),
              shared semantics with the aisstream collector (ETA
              normalised to 'MM-DD HH:MM').
  sv_ship   : shipId <-> IMO mapping harvested from responses (needed
              later for the past-track API).

Environment:
  AIS_DSN          postgres DSN (shared with the aisstream collector)
  SV_USER          SVMP account
  SV_PASSWORD      SVMP password
  SV_BASE_URL      e.g. https://<host>/api   (REQUIRED - includes /api)
  SV_CATEGORY_ID   optional fleet category UUID; omit to poll the whole
                   workspace
  POLL_SECONDS     default 900 (15 min)
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
SV_BASE_URL  = os.environ.get("SV_BASE_URL", "").rstrip("/")
SV_CATEGORY  = os.environ.get("SV_CATEGORY_ID", "").strip()
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "900"))

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
    """ISO timestamp -> aware datetime; naive values are treated as UTC
    (the API mixes '...Z' and zone-less strings)."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_snapshot_item(item):
    """{shipId, position:{...}} (snapshot) or {ship:{...}, position:{...}}
    (/fleet) -> (pos_dict, voyage_dict, ship_meta) or (None, None, None).
    position may be null for vessels without a known location."""
    ship = item.get("ship") or {}
    pos = item.get("position") or {}
    ship_meta = {"ship_id": item.get("shipId") or ship.get("shipId"),
                 "imo": pos.get("imoNo") or ship.get("imoNo"),
                 "mmsi": pos.get("mmsi") or ship.get("mmsi"),
                 "name": clean_text(pos.get("shipName") or ship.get("shipName"))}
    if not pos:
        return None, None, ship_meta

    mmsi, lat, lon = pos.get("mmsi"), pos.get("latitude"), pos.get("longitude")
    ts = parse_iso_ts(pos.get("timestamp"))
    if mmsi is None or lat is None or lon is None or ts is None:
        return None, None, ship_meta
    lat, lon = float(lat), float(lon)
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return None, None, ship_meta
    if abs(lat) < 1e-9 and abs(lon) < 1e-9:
        return None, None, ship_meta

    heading = pos.get("trueHeading")
    if heading is not None and int(heading) >= 511:
        heading = None
    sog = pos.get("speedOverGround")
    if sog is not None and float(sog) >= 102.2:
        sog = None
    cog = pos.get("courseOverGround")
    if cog is not None and float(cog) >= 360.0:
        cog = None
    draught = pos.get("aisMaxDraught")
    if draught is None:
        draught = ship.get("maxDraught")
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
        "ship_name": ship_meta["name"],
    }
    v = {
        "mmsi": p["mmsi"],
        "ts": ts,
        "callsign": clean_text(pos.get("callSign") or ship.get("callSign")),
        "destination": clean_text(pos.get("aisDestination")),
        "eta": normalise_eta(pos.get("aisEta")),
        "draught": float(draught) if draught is not None else None,
        "ship_name": p["ship_name"],
    }
    return p, v, ship_meta


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


def api_get(session, path, params=None):
    r = session.get(SV_BASE_URL + path, params=params or {}, timeout=60)
    if r.status_code == 401:
        raise SvError("401 Unauthorized - check SV_USER / SV_PASSWORD")
    if r.status_code == 429:
        wait = int(r.headers.get("Retry-After", "60"))
        log.warning("429 rate limited; waiting %d s", wait)
        time.sleep(min(wait, 300))
        raise SvError("429 rate limited")
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "response" in data:
        if data.get("error"):
            raise SvError(f"API error {data.get('code')}: {data.get('message')}")
        return data["response"] or []
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


def load_fleet_keys():
    rows = q("SELECT imo, mmsi FROM fleet WHERE active", fetch=True)
    imos = {str(r[0]) for r in rows}
    mmsis = {r[1] for r in rows if r[1] is not None}
    return imos, mmsis


def load_last_voyages():
    out = {}
    for mmsi, callsign, dest, eta, draught in q(
        """SELECT DISTINCT ON (mmsi) mmsi, callsign, destination, eta, draught
           FROM voyage ORDER BY mmsi, ts DESC, ctid DESC""", fetch=True):
        out[mmsi] = (callsign or "", (dest or "").upper().strip(), eta or "",
                     round(draught, 1) if draught is not None else None)
    return out


def upsert_sv_ship(meta):
    if not meta.get("ship_id") or not meta.get("imo"):
        return
    try:
        q("""INSERT INTO sv_ship (imo, mmsi, ship_id, ship_name)
             VALUES (%s,%s,%s,%s)
             ON CONFLICT (imo) DO UPDATE SET ship_id=EXCLUDED.ship_id,
                 mmsi=EXCLUDED.mmsi,
                 ship_name=COALESCE(EXCLUDED.ship_name, sv_ship.ship_name),
                 matched_at=now()""",
          (int(meta["imo"]), int(meta["mmsi"]) if meta.get("mmsi") else None,
           str(meta["ship_id"]), meta.get("name")))
    except (ValueError, psycopg2.Error) as exc:
        log.warning("sv_ship upsert failed for %s: %s", meta, exc)


def insert_position(p):
    q("""INSERT INTO positions (ts, mmsi, lat, lon, sog, cog, heading, nav_status, source)
         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'seavantage')
         ON CONFLICT (mmsi, ts, source) DO NOTHING""",
      (p["ts"], p["mmsi"], p["lat"], p["lon"], p["sog"], p["cog"],
       p["heading"], p["nav_status"]))


def upsert_latest_if_newer(p, v):
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
def cycle(session, voyage_last):
    imos, mmsis = load_fleet_keys()
    params = {"categoryId": SV_CATEGORY} if SV_CATEGORY else {}
    items = api_get(session, "/fleet/snapshot", params)

    stored = voyages = skipped = nopos = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        p, v, meta = parse_snapshot_item(item)
        # match against OUR fleet by IMO first, MMSI as fallback
        ours = (str(meta.get("imo") or "") in imos or
                (p is not None and p["mmsi"] in mmsis))
        if not ours:
            skipped += 1
            continue
        upsert_sv_ship(meta)
        if p is None:
            nopos += 1
            continue
        insert_position(p)
        upsert_latest_if_newer(p, v)
        stored += 1
        key = voyage_key(v)
        has_data = any(key[:3]) or key[3] is not None
        if has_data and voyage_last.get(p["mmsi"]) != key:
            voyage_last[p["mmsi"]] = key
            insert_voyage(v)
            voyages += 1
    log.info("cycle: %d workspace items -> %d positions, %d voyage changes, "
             "%d without position, %d not in our fleet",
             len(items), stored, voyages, nopos, skipped)
    if len(items) == 0:
        log.warning("workspace snapshot is empty - register the vessels in "
                    "the SVMP web UI (workspace fleet) first")


def main():
    missing = [n for n, val in [("AIS_DSN", AIS_DSN), ("SV_USER", SV_USER),
                                ("SV_PASSWORD", SV_PASSWORD),
                                ("SV_BASE_URL", SV_BASE_URL)] if not val]
    if missing:
        log.error("missing env vars: %s", ", ".join(missing))
        sys.exit(1)
    log.info("starting: base=%s poll=%ds category=%s", SV_BASE_URL,
             POLL_SECONDS, SV_CATEGORY or "(whole workspace)")
    session = requests.Session()
    session.auth = (SV_USER, SV_PASSWORD)
    session.headers["Accept"] = "application/json"

    voyage_last = None
    while True:
        started = time.time()
        try:
            if voyage_last is None:
                voyage_last = load_last_voyages()
            cycle(session, voyage_last)
        except psycopg2.OperationalError as exc:
            log.warning("database unavailable: %s", exc)
            voyage_last = None
        except (SvError, requests.RequestException) as exc:
            log.warning("SeaVantage API problem: %s", exc)
        except Exception:
            log.exception("cycle failed; retrying next interval")
        time.sleep(max(30.0, POLL_SECONDS - (time.time() - started)))


if __name__ == "__main__":
    main()
