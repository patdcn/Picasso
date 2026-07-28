"""
SeaVantage endpoint probe - run once to verify base URL, auth and parameter
names before the poller goes live. From the ais-sv-poller container:

    python sv_probe.py 9698783        # probe with Picasso's IMO

Prints HTTP status + first part of each response so a mismatch with the
defaults is immediately obvious. Override any default via the same env vars
the poller uses (SV_BASE_URL, SV_SEARCH_PATH, ...).
"""
import json
import os
import sys

import requests

BASE = os.environ.get("SV_BASE_URL", "https://api.seavantage.com").rstrip("/")
AUTH = (os.environ.get("SV_USER", ""), os.environ.get("SV_PASSWORD", ""))
imo = sys.argv[1] if len(sys.argv) > 1 else "9698783"

tests = [
    ("search by imoNo",  os.environ.get("SV_SEARCH_PATH", "/ship/search"),
     {os.environ.get("SV_SEARCH_PARAM", "imoNo"): imo}),
    ("search by keyword", os.environ.get("SV_SEARCH_PATH", "/ship/search"),
     {"keyword": "PICASSO"}),
]

s = requests.Session()
s.auth = AUTH
s.headers["Accept"] = "application/json"

ship_id = None
for label, path, params in tests:
    url = BASE + path
    try:
        r = s.get(url, params=params, timeout=20)
        body = r.text[:600]
        print(f"\n=== {label}: GET {url} {params} -> HTTP {r.status_code}")
        print(body)
        if r.ok and ship_id is None:
            try:
                data = r.json().get("response", [])
                items = data if isinstance(data, list) else [data]
                for it in items:
                    ship = it.get("ship", it)
                    if ship.get("shipId"):
                        ship_id = ship["shipId"]
                        break
            except Exception:
                pass
    except requests.RequestException as exc:
        print(f"\n=== {label}: GET {url} -> FAILED: {exc}")

if ship_id:
    path = os.environ.get("SV_SNAPSHOT_PATH", "/ship/snapshot")
    param = os.environ.get("SV_SNAPSHOT_PARAM", "shipId")
    url = BASE + path
    r = s.get(url, params={param: ship_id}, timeout=20)
    print(f"\n=== snapshot: GET {url} {param}={ship_id} -> HTTP {r.status_code}")
    try:
        print(json.dumps(r.json(), indent=2)[:1500])
    except Exception:
        print(r.text[:800])
else:
    print("\n(no shipId found in search responses - snapshot probe skipped; "
          "paste the output above so the param names can be corrected)")
