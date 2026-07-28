"""
AIS database access for the Vessel Tracker module.

The AIS stack (TimescaleDB + collector) runs as a separate Dokploy project
("ais-db"); the portal reaches it over the shared docker network using the
AIS_DSN environment variable, e.g.:

    AIS_DSN=postgresql://ais:<password>@ais-db:5432/ais

Design notes
------------
- A fresh connection is opened per query. The portal runs Gunicorn with
  threads, and psycopg2 connections must not be shared across threads;
  at this query volume the ~ms connection setup on the local docker
  network is irrelevant.
- Every public function raises AisDbError with a human-readable message
  when the DB is unreachable or AIS_DSN is missing; pages catch this and
  render an explanatory card instead of crashing.
"""
import os

import psycopg2

AIS_DSN = os.environ.get("AIS_DSN", "")

# AIS navigational status codes (ITU-R M.1371) - the ones that matter here.
NAV_STATUS = {
    0: "Underway (engine)",
    1: "At anchor",
    2: "Not under command",
    3: "Restricted manoeuvrability",
    4: "Constrained by draught",
    5: "Moored",
    6: "Aground",
    7: "Fishing",
    8: "Underway (sailing)",
    11: "Towing astern",
    12: "Pushing ahead",
    14: "AIS-SART",
    15: "Undefined",
}


class AisDbError(RuntimeError):
    pass


def nav_status_label(code):
    if code is None:
        return "—"
    return NAV_STATUS.get(int(code), f"Code {code}")


def q(sql, params=None):
    """Run a query on a fresh connection; return list of tuples."""
    if not AIS_DSN:
        raise AisDbError(
            "AIS_DSN is not configured. Add it to the portal's environment "
            "variables in Dokploy (postgresql://ais:<password>@ais-db:5432/ais)."
        )
    try:
        with psycopg2.connect(AIS_DSN, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if cur.description is None:   # INSERT/UPDATE: no result set
                    return []
                return cur.fetchall()
    except psycopg2.Error as exc:
        raise AisDbError(f"AIS database unreachable: {exc}") from exc


def summary():
    """Headline numbers for the Database page."""
    rows = q(
        """SELECT
             (SELECT count(*) FROM fleet WHERE active)                AS fleet_active,
             (SELECT count(*) FROM latest)                            AS vessels_heard,
             (SELECT count(*) FROM positions)                         AS position_rows,
             (SELECT count(*) FROM voyage)                            AS voyage_rows,
             (SELECT max(ts)  FROM latest)                            AS last_message"""
    )
    keys = ("fleet_active", "vessels_heard", "position_rows", "voyage_rows", "last_message")
    return dict(zip(keys, rows[0]))


def per_vessel():
    """One row per active fleet vessel with track stats and latest state.

    Vessels never heard appear with NULL stats so the page can grey them out -
    that list doubles as the shopping list for a satellite AIS source.
    """
    return q(
        """SELECT f.name, f.mmsi, f.region,
                  s.n_points, s.first_seen, s.last_seen,
                  l.nav_status, l.sog, l.destination, l.eta
           FROM fleet f
           LEFT JOIN (SELECT mmsi, count(*) AS n_points,
                             min(ts) AS first_seen, max(ts) AS last_seen
                      FROM positions GROUP BY mmsi) s ON s.mmsi = f.mmsi
           LEFT JOIN latest l ON l.mmsi = f.mmsi
           WHERE f.active
           ORDER BY s.last_seen DESC NULLS LAST, f.name"""
    )


def recent_positions(limit=50):
    """Most recent stored track points, newest first, with fleet names."""
    return q(
        """SELECT p.ts, COALESCE(f.name, p.mmsi::text) AS vessel,
                  p.lat, p.lon, p.sog, p.nav_status, p.source
           FROM positions p
           LEFT JOIN fleet f ON f.mmsi = p.mmsi
           ORDER BY p.ts DESC
           LIMIT %s""",
        (limit,),
    )


def fleet_with_sv():
    """All fleet vessels (every Excel field) joined with their SeaVantage
    registration state. Ordered by name."""
    return q(
        """SELECT f.imo, f.mmsi, f.name, f.owner, f.operator, f.built, f.flag,
                  f.region, f.tier, f.notes, f.active,
                  s.ship_id, s.registered_at, s.match_result,
                  l.ship_name AS ais_name
           FROM fleet f
           LEFT JOIN sv_ship s ON s.imo = f.imo
           LEFT JOIN latest l ON l.mmsi = f.mmsi
           ORDER BY f.name"""
    )


def sv_registered_count():
    return q("SELECT count(*) FROM sv_ship WHERE registered_at IS NOT NULL")[0][0]


def sv_record_registration(imo, mmsi, ship_id, ship_name):
    q("""INSERT INTO sv_ship (imo, mmsi, ship_id, ship_name, registered_at, match_result)
         VALUES (%s,%s,%s,%s, now(), 'SUCCESS')
         ON CONFLICT (imo) DO UPDATE SET
           ship_id=EXCLUDED.ship_id, mmsi=EXCLUDED.mmsi,
           ship_name=COALESCE(EXCLUDED.ship_name, sv_ship.ship_name),
           registered_at=COALESCE(sv_ship.registered_at, now()),
           match_result='SUCCESS', matched_at=now()""",
      (imo, mmsi, ship_id, ship_name))


def sv_record_match_failure(imo, mmsi, result):
    q("""INSERT INTO sv_ship (imo, mmsi, ship_id, match_result)
         VALUES (%s,%s,'', %s)
         ON CONFLICT (imo) DO UPDATE SET match_result=EXCLUDED.match_result,
           matched_at=now()""",
      (imo, mmsi, result))


def sv_clear_registration(imo):
    q("UPDATE sv_ship SET registered_at=NULL WHERE imo=%s", (imo,))


def latest_positions():
    """All vessels present in the track database (latest fix per vessel),
    with the fleet name as primary label. Ordered by name."""
    return q(
        """SELECT l.mmsi,
                  COALESCE(f.name, initcap(lower(l.ship_name)), l.mmsi::text) AS name,
                  l.ts, l.lat, l.lon, l.sog, l.nav_status, l.destination
           FROM latest l
           LEFT JOIN fleet f ON f.mmsi = l.mmsi
           ORDER BY name"""
    )


def track(mmsi, days=30, max_points=1200):
    """Track points for one vessel over the given window (both sources,
    chronological). Thinned by striding to at most max_points, keeping the
    first and last point."""
    rows = q(
        """SELECT ts, lat, lon, sog, nav_status, source
           FROM positions
           WHERE mmsi=%s AND ts >= now() - make_interval(days => %s)
           ORDER BY ts""",
        (mmsi, days),
    )
    n = len(rows)
    if n <= max_points:
        return rows
    stride = -(-n // max_points)          # ceil
    thinned = rows[::stride]
    if thinned[-1] != rows[-1]:
        thinned.append(rows[-1])
    return thinned
