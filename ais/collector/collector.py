"""
AIS collector daemon - DSV Picasso Engineering Portal
=====================================================
Long-running process that:
  1. Loads active MMSIs from the fleet table (refreshed periodically).
  2. Connects to wss://stream.aisstream.io/v0/stream and subscribes.
     aisstream caps FiltersShipMMSI at 50 MMSIs per subscription, so the
     fleet is split into chunks of <=50 and the subscription is rotated
     (swap-and-replace on the same socket) every ROTATE_SECONDS.
  3. Validates incoming PositionReports (bounds, AIS not-available codes,
     speed gate against teleports).
  4. Downsamples: a point is stored when >= SAMPLE_SECONDS since the last
     stored point for that vessel, OR when nav_status changes.
  5. Handles ShipStaticData (AIS type 5): callsign, destination, ETA and
     max draught are stored in the `voyage` table only when they CHANGE,
     and mirrored onto `latest` for the map popup.
  6. Upserts the `latest` table (throttled) so the map always has a fresh
     "where is everyone now" without touching the hypertable.

Environment:
  AIS_DSN          postgres DSN, e.g. postgresql://ais:pw@ais-db:5432/ais
  AISSTREAM_KEY    aisstream.io API key
  SAMPLE_SECONDS   downsample window        (default 1800 = 30 min)
  ROTATE_SECONDS   MMSI chunk rotation      (default 300  = 5 min)
  FLEET_REFRESH    fleet reload interval    (default 300  = 5 min)
  LATEST_THROTTLE  latest-upsert per vessel (default 60 s)
  SPEED_GATE_KN    implied-speed reject     (default 50 kn)
"""

import asyncio
import json
import logging
import math
import os
import signal
import sys
import time
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import websockets

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
AIS_DSN         = os.environ.get("AIS_DSN", "")
AISSTREAM_KEY   = os.environ.get("AISSTREAM_KEY", "")
SAMPLE_SECONDS  = int(os.environ.get("SAMPLE_SECONDS", "1800"))
ROTATE_SECONDS  = int(os.environ.get("ROTATE_SECONDS", "300"))
FLEET_REFRESH   = int(os.environ.get("FLEET_REFRESH", "300"))
LATEST_THROTTLE = int(os.environ.get("LATEST_THROTTLE", "60"))
SPEED_GATE_KN   = float(os.environ.get("SPEED_GATE_KN", "50"))
CHUNK_SIZE      = 50   # hard aisstream limit on FiltersShipMMSI
WS_URL          = "wss://stream.aisstream.io/v0/stream"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("ais-collector")


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable, no I/O)
# ---------------------------------------------------------------------------
def haversine_nm(lat1, lon1, lat2, lon2):
    """Great-circle distance in nautical miles."""
    r_nm = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r_nm * math.asin(math.sqrt(a))


def parse_position_report(msg):
    """
    Extract a clean position dict from an aisstream envelope, or None if the
    message is not a usable PositionReport. Applies AIS not-available codes:
      lat 91 / lon 181  -> position not available (reject row)
      heading 511       -> NULL
      sog 102.3         -> NULL
      cog 360           -> NULL
    """
    if msg.get("MessageType") != "PositionReport":
        return None
    body = msg.get("Message", {}).get("PositionReport", {})
    meta = msg.get("MetaData", {})

    mmsi = meta.get("MMSI") or body.get("UserID")
    lat = body.get("Latitude")
    lon = body.get("Longitude")
    if mmsi is None or lat is None or lon is None:
        return None
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return None
    if abs(lat) < 1e-9 and abs(lon) < 1e-9:
        return None  # 0,0 null island artefacts

    sog = body.get("Sog")
    if sog is not None and sog >= 102.2:
        sog = None
    cog = body.get("Cog")
    if cog is not None and cog >= 360.0:
        cog = None
    heading = body.get("TrueHeading")
    if heading is not None and heading >= 511:
        heading = None

    # aisstream metadata timestamp, e.g. "2026-07-27 10:15:00.123 +0000 UTC"
    ts = None
    raw_ts = meta.get("time_utc", "")
    if raw_ts:
        try:
            clean = raw_ts.replace(" UTC", "").strip()
            ts = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S.%f %z")
        except ValueError:
            ts = None
    if ts is None:
        ts = datetime.now(timezone.utc)

    return {
        "mmsi": int(mmsi),
        "ts": ts,
        "lat": float(lat),
        "lon": float(lon),
        "sog": sog,
        "cog": cog,
        "heading": int(heading) if heading is not None else None,
        "nav_status": body.get("NavigationalStatus"),
        "ship_name": (meta.get("ShipName") or "").strip() or None,
    }


def parse_ship_static(msg):
    """
    Extract voyage fields from a ShipStaticData (AIS type 5) envelope,
    or None if not usable. ETA in AIS has no year; kept as 'MM-DD HH:MM'.
    AIS not-available conventions: ETA month 0 / day 0, hour 24, minute 60;
    draught 0 = not available.
    """
    if msg.get("MessageType") != "ShipStaticData":
        return None
    body = msg.get("Message", {}).get("ShipStaticData", {})
    meta = msg.get("MetaData", {})
    mmsi = meta.get("MMSI") or body.get("UserID")
    if mmsi is None:
        return None

    def clean_text(v):
        v = (v or "").replace("@", "").strip()
        return v or None

    eta = None
    e = body.get("Eta") or {}
    month, day = e.get("Month", 0), e.get("Day", 0)
    hour, minute = e.get("Hour", 24), e.get("Minute", 60)
    if month and day:
        hh = hour if hour < 24 else 0
        mm = minute if minute < 60 else 0
        eta = f"{month:02d}-{day:02d} {hh:02d}:{mm:02d}"

    draught = body.get("MaximumStaticDraught")
    if draught is not None and draught <= 0:
        draught = None

    ts = None
    raw_ts = meta.get("time_utc", "")
    if raw_ts:
        try:
            ts = datetime.strptime(raw_ts.replace(" UTC", "").strip(),
                                   "%Y-%m-%d %H:%M:%S.%f %z")
        except ValueError:
            ts = None
    if ts is None:
        ts = datetime.now(timezone.utc)

    return {
        "mmsi": int(mmsi),
        "ts": ts,
        "callsign": clean_text(body.get("CallSign")),
        "destination": clean_text(body.get("Destination")),
        "eta": eta,
        "draught": float(draught) if draught is not None else None,
        "ship_name": clean_text(body.get("Name") or meta.get("ShipName")),
    }


def voyage_key(v):
    """Normalized comparison tuple: store only when one of these changes."""
    dest = (v["destination"] or "").upper().strip()
    return (v["callsign"] or "", dest, v["eta"] or "",
            round(v["draught"], 1) if v["draught"] is not None else None)


class DownsampleState:
    """
    Per-vessel decision logic. store() returns (accept, reason):
      accept=True  -> write to positions
      accept=False -> skip (but `latest` may still be updated by caller)
    Rejects teleports: implied speed between consecutive *seen* points
    above SPEED_GATE_KN.
    """

    def __init__(self, sample_seconds=SAMPLE_SECONDS, speed_gate_kn=SPEED_GATE_KN):
        self.sample_seconds = sample_seconds
        self.speed_gate_kn = speed_gate_kn
        self.last_stored = {}   # mmsi -> (ts_epoch, lat, lon, nav_status)
        self.last_seen = {}     # mmsi -> (ts_epoch, lat, lon)

    def decide(self, p):
        mmsi = p["mmsi"]
        t = p["ts"].timestamp()
        lat, lon = p["lat"], p["lon"]

        # speed gate vs last *seen* point (catches teleports early)
        seen = self.last_seen.get(mmsi)
        if seen is not None:
            dt_h = (t - seen[0]) / 3600.0
            if 0 < dt_h:
                dist_nm = haversine_nm(seen[1], seen[2], lat, lon)
                if dt_h > 1e-6 and dist_nm / dt_h > self.speed_gate_kn:
                    return False, "speed_gate"
            elif dt_h < 0:
                return False, "backwards_ts"
        self.last_seen[mmsi] = (t, lat, lon)

        stored = self.last_stored.get(mmsi)
        if stored is None:
            self.last_stored[mmsi] = (t, lat, lon, p["nav_status"])
            return True, "first"
        if p["nav_status"] is not None and p["nav_status"] != stored[3]:
            self.last_stored[mmsi] = (t, lat, lon, p["nav_status"])
            return True, "status_change"
        if t - stored[0] >= self.sample_seconds:
            self.last_stored[mmsi] = (t, lat, lon, p["nav_status"])
            return True, "interval"
        return False, "window"


def chunk_mmsis(mmsis, size=CHUNK_SIZE):
    mmsis = sorted(mmsis)
    return [mmsis[i:i + size] for i in range(0, len(mmsis), size)] or [[]]


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
class Db:
    def __init__(self, dsn):
        self.dsn = dsn
        self.conn = None

    def _connect(self):
        self.conn = psycopg2.connect(self.dsn)
        self.conn.autocommit = True

    def _cur(self):
        if self.conn is None or self.conn.closed:
            self._connect()
        return self.conn.cursor()

    def execute(self, sql, params=None):
        for attempt in (1, 2):
            try:
                with self._cur() as cur:
                    cur.execute(sql, params)
                    return
            except psycopg2.OperationalError:
                if attempt == 2:
                    raise
                log.warning("DB connection lost, reconnecting")
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None

    def fetch_active_mmsis(self):
        for attempt in (1, 2):
            try:
                with self._cur() as cur:
                    cur.execute(
                        "SELECT mmsi FROM fleet WHERE active AND mmsi IS NOT NULL"
                    )
                    return [str(r[0]) for r in cur.fetchall()]
            except psycopg2.OperationalError:
                if attempt == 2:
                    raise
                self.conn = None
        return []

    def insert_position(self, p):
        self.execute(
            """INSERT INTO positions (ts, mmsi, lat, lon, sog, cog, heading, nav_status, source)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'aisstream')
               ON CONFLICT (mmsi, ts, source) DO NOTHING""",
            (p["ts"], p["mmsi"], p["lat"], p["lon"],
             p["sog"], p["cog"], p["heading"], p["nav_status"]),
        )

    def load_last_voyages(self):
        """Last stored voyage row per vessel, so a collector restart does not
        re-store unchanged voyage data."""
        for attempt in (1, 2):
            try:
                with self._cur() as cur:
                    cur.execute(
                        """SELECT DISTINCT ON (mmsi)
                                  mmsi, callsign, destination, eta, draught
                           FROM voyage ORDER BY mmsi, ts DESC, ctid DESC"""
                    )
                    out = {}
                    for mmsi, callsign, dest, eta, draught in cur.fetchall():
                        out[mmsi] = (callsign or "", (dest or "").upper().strip(),
                                     eta or "",
                                     round(draught, 1) if draught is not None else None)
                    return out
            except psycopg2.OperationalError:
                if attempt == 2:
                    raise
                self.conn = None
        return {}

    def insert_voyage(self, v):
        self.execute(
            """INSERT INTO voyage (ts, mmsi, callsign, destination, eta, draught, ship_name, source)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'aisstream')""",
            (v["ts"], v["mmsi"], v["callsign"], v["destination"],
             v["eta"], v["draught"], v["ship_name"]),
        )

    def update_latest_static(self, v):
        self.execute(
            """UPDATE latest SET callsign=%s, destination=%s, eta=%s, draught=%s,
                                 ship_name=COALESCE(%s, ship_name)
               WHERE mmsi=%s""",
            (v["callsign"], v["destination"], v["eta"], v["draught"],
             v["ship_name"], v["mmsi"]),
        )

    def upsert_latest(self, p):
        self.execute(
            """INSERT INTO latest (mmsi, ts, lat, lon, sog, cog, heading, nav_status, ship_name)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (mmsi) DO UPDATE SET
                 ts=EXCLUDED.ts, lat=EXCLUDED.lat, lon=EXCLUDED.lon,
                 sog=EXCLUDED.sog, cog=EXCLUDED.cog, heading=EXCLUDED.heading,
                 nav_status=EXCLUDED.nav_status,
                 ship_name=COALESCE(EXCLUDED.ship_name, latest.ship_name)""",
            (p["mmsi"], p["ts"], p["lat"], p["lon"], p["sog"],
             p["cog"], p["heading"], p["nav_status"], p["ship_name"]),
        )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
class Collector:
    def __init__(self):
        self.db = Db(AIS_DSN)
        self.state = DownsampleState()
        self.mmsis = []
        self.chunks = [[]]
        self.chunk_idx = 0
        self.latest_sent = {}   # mmsi -> epoch of last `latest` upsert
        self.voyage_last = None  # mmsi -> voyage_key tuple; lazy-loaded from DB
        self.stats = {"rx": 0, "stored": 0, "latest": 0, "rejected": 0, "voyage": 0}
        self._stop = asyncio.Event()

    def refresh_fleet(self):
        mmsis = self.db.fetch_active_mmsis()
        if set(mmsis) != set(self.mmsis):
            log.info("fleet changed: %d active MMSIs (%d chunks)",
                     len(mmsis), max(1, math.ceil(len(mmsis) / CHUNK_SIZE)))
            self.mmsis = mmsis
            self.chunks = chunk_mmsis(mmsis)
            self.chunk_idx = self.chunk_idx % len(self.chunks)
            return True
        return False

    def subscription_message(self):
        sub = {
            "APIKey": AISSTREAM_KEY,
            "BoundingBoxes": [[[-90.0, -180.0], [90.0, 180.0]]],
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
        }
        chunk = self.chunks[self.chunk_idx]
        if chunk:
            sub["FiltersShipMMSI"] = chunk
        return json.dumps(sub)

    def handle(self, raw):
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        if msg.get("MessageType") == "ShipStaticData":
            self.handle_static(msg)
            return
        p = parse_position_report(msg)
        if p is None:
            return
        self.stats["rx"] += 1
        # defense in depth: only vessels on our list, whatever the filter did
        if str(p["mmsi"]) not in self.mmsis:
            return

        accept, reason = self.state.decide(p)
        if accept:
            self.db.insert_position(p)
            self.stats["stored"] += 1
            log.info("stored %s (%s) %.5f,%.5f status=%s [%s]",
                     p["ship_name"] or p["mmsi"], p["mmsi"],
                     p["lat"], p["lon"], p["nav_status"], reason)
        elif reason in ("speed_gate", "backwards_ts"):
            self.stats["rejected"] += 1
            log.warning("rejected %s (%s): %s", p["ship_name"] or "?", p["mmsi"], reason)
            return  # do not poison `latest` with a teleport either

        now = time.time()
        if now - self.latest_sent.get(p["mmsi"], 0) >= LATEST_THROTTLE:
            self.db.upsert_latest(p)
            self.latest_sent[p["mmsi"]] = now
            self.stats["latest"] += 1


    def handle_static(self, msg):
        v = parse_ship_static(msg)
        if v is None or str(v["mmsi"]) not in self.mmsis:
            return
        if self.voyage_last is None:
            self.voyage_last = self.db.load_last_voyages()
        key = voyage_key(v)
        if self.voyage_last.get(v["mmsi"]) == key:
            self.db.update_latest_static(v)  # keep latest fresh, no new history row
            return
        self.voyage_last[v["mmsi"]] = key
        self.db.insert_voyage(v)
        self.db.update_latest_static(v)
        self.stats["voyage"] += 1
        log.info("voyage %s (%s) dest=%s eta=%s draught=%s",
                 v["ship_name"] or v["mmsi"], v["mmsi"],
                 v["destination"], v["eta"], v["draught"])

    async def run_socket(self):
        async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
            await ws.send(self.subscription_message())
            log.info("subscribed: chunk %d/%d (%d MMSIs)",
                     self.chunk_idx + 1, len(self.chunks),
                     len(self.chunks[self.chunk_idx]))
            last_rotate = time.time()
            last_refresh = time.time()
            last_stats = time.time()
            while not self._stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    self.handle(raw)
                except asyncio.TimeoutError:
                    pass  # quiet stream is fine; keepalive pings handle liveness

                now = time.time()
                if now - last_refresh >= FLEET_REFRESH:
                    last_refresh = now
                    if self.refresh_fleet():
                        await ws.send(self.subscription_message())
                        log.info("resubscribed after fleet change")
                if len(self.chunks) > 1 and now - last_rotate >= ROTATE_SECONDS:
                    last_rotate = now
                    self.chunk_idx = (self.chunk_idx + 1) % len(self.chunks)
                    await ws.send(self.subscription_message())
                    log.info("rotated to chunk %d/%d",
                             self.chunk_idx + 1, len(self.chunks))
                if now - last_stats >= 900:
                    last_stats = now
                    log.info("stats: %s", self.stats)

    async def run(self):
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._stop.set)

        backoff = 5
        while not self._stop.is_set():
            try:
                self.refresh_fleet()
                if not self.mmsis:
                    log.warning("no active MMSIs in fleet; retry in 60 s")
                    await asyncio.sleep(60)
                    continue
                await self.run_socket()
                backoff = 5
            except (websockets.WebSocketException, OSError,
                    psycopg2.OperationalError) as exc:
                log.warning("connection error (%s); reconnect in %d s", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)
            except Exception:
                log.exception("unexpected error; reconnect in %d s", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)
        log.info("shutdown")


def main():
    if not AIS_DSN or not AISSTREAM_KEY:
        log.error("AIS_DSN and AISSTREAM_KEY must be set")
        sys.exit(1)
    log.info("starting: sample=%ds rotate=%ds refresh=%ds throttle=%ds gate=%.0fkn",
             SAMPLE_SECONDS, ROTATE_SECONDS, FLEET_REFRESH,
             LATEST_THROTTLE, SPEED_GATE_KN)
    asyncio.run(Collector().run())


if __name__ == "__main__":
    main()
