"""
SeaVantage endpoint probe - verify base URL + credentials in one run.
From the ais-sv-poller container (Dokploy terminal):

    python /app/sv_probe.py

Requires SV_BASE_URL (incl. /api), SV_USER, SV_PASSWORD in the environment.
Calls /fleet/categories (parameter-free auth check) and /fleet/snapshot,
printing status + a response sample.
"""
import json
import os
import sys

import requests

BASE = os.environ.get("SV_BASE_URL", "").rstrip("/")
if not BASE:
    sys.exit("SV_BASE_URL is not set (must include /api, e.g. https://<host>/api)")

s = requests.Session()
s.auth = (os.environ.get("SV_USER", ""), os.environ.get("SV_PASSWORD", ""))
s.headers["Accept"] = "application/json"

for label, path in [("categories (auth check)", "/fleet/categories"),
                    ("workspace snapshot", "/fleet/snapshot")]:
    url = BASE + path
    try:
        r = s.get(url, timeout=30)
        print(f"\n=== {label}: GET {url} -> HTTP {r.status_code}")
        try:
            print(json.dumps(r.json(), indent=2)[:1200])
        except Exception:
            print(r.text[:600])
    except requests.RequestException as exc:
        print(f"\n=== {label}: GET {url} -> FAILED: {exc}")

print("\nInterpretatie: 200 + code 200 = goed; 401 = credentials; "
      "lege response bij snapshot = vloot nog niet geregistreerd in SVMP workspace.")
