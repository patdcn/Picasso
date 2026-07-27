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
