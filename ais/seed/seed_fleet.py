"""
One-off fleet seed - DSV Picasso Engineering Portal AIS tracker
================================================================
Loads seed/fleet_seed.csv (58 DSVs from Patrick's Excel) into the fleet
table. Upserts on IMO, so it is safe to re-run; existing rows are updated,
manual edits to columns not in the CSV are preserved (only listed columns
are overwritten).

Run inside the ais-collector container (Dokploy terminal):

  python seed/seed_fleet.py

AIS_DSN is inherited from the container environment.
"""

import csv
import os
import sys

import psycopg2

CSV_PATH = os.environ.get("FLEET_CSV", os.path.join(os.path.dirname(__file__), "fleet_seed.csv"))
AIS_DSN = os.environ.get("AIS_DSN", "")

UPSERT = """
INSERT INTO fleet (imo, mmsi, name, owner, operator, built, flag, region, tier, notes, active)
VALUES (%(imo)s, %(mmsi)s, %(name)s, %(owner)s, %(operator)s, %(built)s,
        %(flag)s, %(region)s, %(tier)s, %(notes)s, %(active)s)
ON CONFLICT (imo) DO UPDATE SET
    mmsi = EXCLUDED.mmsi,
    name = EXCLUDED.name,
    owner = EXCLUDED.owner,
    operator = EXCLUDED.operator,
    built = EXCLUDED.built,
    flag = EXCLUDED.flag,
    region = EXCLUDED.region,
    tier = EXCLUDED.tier,
    notes = EXCLUDED.notes,
    active = EXCLUDED.active,
    updated_at = now()
"""


def main():
    if not AIS_DSN:
        print("AIS_DSN must be set", file=sys.stderr)
        sys.exit(1)

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        r["imo"] = int(r["imo"])
        r["mmsi"] = int(r["mmsi"]) if r["mmsi"].strip() else None
        r["active"] = r["active"].strip() == "1"
        for k in ("owner", "operator", "built", "flag", "region", "tier", "notes"):
            r[k] = r[k].strip() or None

    conn = psycopg2.connect(AIS_DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(UPSERT, r)
            cur.execute("SELECT count(*), count(*) FILTER (WHERE active) FROM fleet")
            total, active = cur.fetchone()
        conn.commit()
        print(f"seeded {len(rows)} rows -> fleet now holds {total} vessels ({active} active)")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
