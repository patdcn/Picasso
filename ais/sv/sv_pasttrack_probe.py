"""
Past Track entitlement probe - READ ONLY, writes nothing.

Answers one question: does our SeaVantage subscription include
GET /ship/past-track (60-day position history per shipId)?

Run inside the ais-sv-poller container (Dokploy terminal):

    python /app/sv_pasttrack_probe.py

Uses the Picasso's shipId from sv_ship (or the first available one) and
requests the last 48 hours. Interpretation:
  HTTP 200 + points  -> included; we can build the historical backfill
  HTTP 403           -> not in the trial; ask SeaVantage (Ann / cx@) to
                        enable the Past Track API
  HTTP 401           -> credential problem (unlikely; poller works)
"""
import datetime
import json
import os
import sys

import psycopg2
import requests

BASE = os.environ.get("SV_BASE_URL", "").rstrip("/")
DSN = os.environ.get("AIS_DSN", "")
if not BASE or not DSN:
    sys.exit("SV_BASE_URL and AIS_DSN must be set (they are in this container)")

with psycopg2.connect(DSN) as conn, conn.cursor() as cur:
    cur.execute("""SELECT imo, ship_name, ship_id FROM sv_ship
                   WHERE ship_id <> '' ORDER BY (imo = 9698783) DESC LIMIT 1""")
    row = cur.fetchone()
if not row:
    sys.exit("no shipIds in sv_ship yet - register a vessel first")
imo, name, ship_id = row
print(f"probing with {name or imo} (shipId {ship_id})")

now = datetime.datetime.now(datetime.timezone.utc)
frm = (now - datetime.timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
to = now.strftime("%Y-%m-%dT%H:%M:%SZ")

s = requests.Session()
s.auth = (os.environ.get("SV_USER", ""), os.environ.get("SV_PASSWORD", ""))
s.headers.update({"Accept": "application/json", "Connection": "close"})
r = s.get(f"{BASE}/ship/past-track",
          params={"shipId": ship_id, "from": frm, "to": to}, timeout=60)
print(f"\nGET /ship/past-track ({frm} .. {to}) -> HTTP {r.status_code}")
try:
    data = r.json()
except ValueError:
    print(r.text[:400]); sys.exit(1)

pts = data.get("response") or []
print(f"envelope code={data.get('code')} error={data.get('error')} "
      f"message={data.get('message')!r}")
print(f"points returned: {len(pts)}")
if pts:
    first, last = pts[0], pts[-1]
    print(f"  first: {first.get('timestamp')}  ({first.get('latitude')}, {first.get('longitude')})")
    print(f"  last : {last.get('timestamp')}  ({last.get('latitude')}, {last.get('longitude')})")
    print("\nCONCLUSIE: Past Track zit in het abonnement -> backfill kan gebouwd worden.")
elif r.status_code == 200:
    print("\nCONCLUSIE: endpoint toegankelijk maar leeg venster; probeer een "
          "actieve vessel of groter venster.")
elif r.status_code == 403:
    print("\nCONCLUSIE: geen toegang op dit abonnement -> vraag SeaVantage om "
          "de Past Track API te activeren (cx@seavantage.com).")
