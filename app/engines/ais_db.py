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


# ---------------------------------------------------------------------------
# Position QC browser (Database page)

QC_SORTS = {
    "ts_desc":    "ts DESC",
    "ts":         "ts",
    "speed_desc": "impl_kn DESC NULLS LAST",
    "dist_desc":  "dist_nm DESC NULLS LAST",
    "vessel":     "name NULLS LAST, ts DESC",
    "lat":        "lat", "lat_desc": "lat DESC",
    "lon":        "lon", "lon_desc": "lon DESC",
    "sog_desc":   "sog DESC NULLS LAST",
}


def _eq_dist_nm(lat1, lon1, lat2, lon2):
    """Equirectangular distance in NM (plenty for gating)."""
    import math
    mid = math.radians((lat1 + lat2) / 2.0)
    return 60.0 * math.sqrt((lat2 - lat1) ** 2
                            + (math.cos(mid) * (lon2 - lon1)) ** 2)


_CHAIN_ASSOC_NM = 10.0        # reject fixes near a just-rejected fix...
_CHAIN_ASSOC_FLOOR_NM = 20.0  # ...but only when far from the anchor.
# Without the floor the association cascades along a genuine transit: one
# rejected mini-glitch near the cluster, and every subsequent real fix
# (3-4 NM from its rejected predecessor) chains into rejection. The rule
# is meant for time-diluted fixes sitting OUT at a bogus excursion
# location - hence the far-from-anchor requirement.


def _chain_flags(fixes, thr):
    """Patrick's cluster-reference validation: every fix is gated against
    the last ACCEPTED fix (the anchor), never against a possibly-corrupt
    predecessor. A rejected fix does not advance the anchor, so a whole
    excursion of internally-consistent corrupt fixes is rejected fix by
    fix against the same trusted reference. Two robustness additions:
    the anchor seeds at the first mutually-plausible PAIR (a corrupt
    first fix cannot poison the chain), and a fix that sits FAR from the
    anchor (> _CHAIN_ASSOC_FLOOR_NM) yet within _CHAIN_ASSOC_NM of a
    just-rejected fix is rejected by association (long excursions dilute
    the speed-vs-anchor as time passes; the far-from-anchor floor stops
    the association from cascading along a genuine transit).
    fixes: list of (ts, lat, lon); returns list of
    (suspect, dist_nm_vs_anchor, dt_min_vs_anchor, impl_kn_vs_anchor)."""
    n = len(fixes)
    out = [None] * n
    if n == 0:
        return out
    if n == 1:
        return [(False, None, None, None)]

    def leg(a, b):
        d = _eq_dist_nm(a[1], a[2], b[1], b[2])
        dt = (b[0] - a[0]).total_seconds() / 60.0
        v = d / (dt / 60.0) if dt > 0 else None
        return d, dt, v

    # seed: first consecutive pair with a plausible leg
    seed = 0
    for i in range(n - 1):
        _d, _dt, v = leg(fixes[i], fixes[i + 1])
        if v is not None and v <= thr:
            seed = i
            break
    # fixes before the seed: gate retrospectively against the seed fix
    for i in range(seed):
        d, dt, v = leg(fixes[i], fixes[seed])
        out[i] = (bool(v is not None and v > thr), d, dt, v)
    anchor = fixes[seed]
    out[seed] = (False, None, None, None)
    last_rejected = None
    for i in range(seed + 1, n):
        d, dt, v = leg(anchor, fixes[i])
        assoc = (last_rejected is not None
                 and d is not None and d > _CHAIN_ASSOC_FLOOR_NM
                 and _eq_dist_nm(last_rejected[1], last_rejected[2],
                                 fixes[i][1], fixes[i][2]) < _CHAIN_ASSOC_NM)
        if (v is not None and v > thr) or assoc:
            out[i] = (True, d, dt, v)
            last_rejected = fixes[i]
        else:
            out[i] = (False, d, dt, v)
            anchor = fixes[i]
            last_rejected = None
    return out


_QC_PY_SORTS = {
    "ts_desc":    (lambda r: r[0], True),
    "ts":         (lambda r: r[0], False),
    "speed_desc": (lambda r: (r[10] is not None, r[10]), True),
    "dist_desc":  (lambda r: (r[8] is not None, r[8]), True),
    "vessel":     (lambda r: (r[2] or "\uffff", r[0]), False),
    "lat":        (lambda r: r[3], False),
    "lat_desc":   (lambda r: r[3], True),
    "lon":        (lambda r: r[4], False),
    "lon_desc":   (lambda r: r[4], True),
    "sog_desc":   (lambda r: (r[5] is not None, r[5]), True),
}


def _positions_qc_chain(mmsi=None, t_from=None, t_to=None, source=None,
                        threshold_kn=30.0, suspect_only=False, bbox=None,
                        sort="ts_desc", page=1, page_size=200):
    """Chain-mode listing (see _chain_flags). Fetches the ordered fixes
    for the filter window, runs the per-vessel chain in Python and pages
    the result. dist/dt/implied columns are versus the ANCHOR at
    evaluation time - for accepted fixes that is the previous accepted
    fix, for rejected fixes the trusted reference they failed against."""
    thr = float(threshold_kn or 30.0)
    where, params = ["TRUE"], []
    if t_from is not None:
        where.append("p.ts >= %s"); params.append(t_from)
    if t_to is not None:
        where.append("p.ts < %s"); params.append(t_to)
    if mmsi:
        where.append("p.mmsi = %s"); params.append(int(mmsi))
    if source:
        where.append("p.source = %s"); params.append(source)
    raw = q(f"""SELECT p.ts, p.mmsi, f.name, p.lat, p.lon, p.sog,
                       p.nav_status, p.source
                FROM positions p LEFT JOIN fleet f ON f.mmsi = p.mmsi
                WHERE {' AND '.join(where)}
                ORDER BY p.mmsi, p.ts""", params)
    rows = []
    i = 0
    while i < len(raw):
        j = i
        while j < len(raw) and raw[j][1] == raw[i][1]:
            j += 1
        group = raw[i:j]
        flags = _chain_flags([(r[0], r[3], r[4]) for r in group], thr)
        for r, (susp, d, dt, v) in zip(group, flags):
            rows.append((r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7],
                         d, dt, v, susp))
        i = j
    if suspect_only:
        rows = [r for r in rows if r[11]]
    if bbox:
        la0, la1, lo0, lo1 = bbox
        rows = [r for r in rows
                if la0 <= r[3] <= la1 and lo0 <= r[4] <= lo1]
    key, rev = _QC_PY_SORTS.get(sort) or _QC_PY_SORTS["ts_desc"]
    rows.sort(key=key, reverse=rev)
    total = len(rows)
    page = max(1, int(page or 1))
    start = (page - 1) * page_size
    return rows[start:start + page_size], total


def qc_vessels():
    """(mmsi, display-name) for every vessel with stored positions."""
    return q("""SELECT p.mmsi,
                       COALESCE(min(f.name), min(l.ship_name),
                                p.mmsi::text) AS name
                FROM (SELECT DISTINCT mmsi FROM positions) p
                LEFT JOIN fleet f  ON f.mmsi = p.mmsi
                LEFT JOIN latest l ON l.mmsi = p.mmsi
                GROUP BY p.mmsi ORDER BY 2""")


def qc_sources():
    return [r[0] for r in q(
        "SELECT DISTINCT source FROM positions ORDER BY 1")]


def positions_qc(mmsi=None, t_from=None, t_to=None, source=None,
                 threshold_kn=30.0, suspect_only=False, mode="chain",
                 bbox=None, sort="ts_desc", page=1, page_size=200):
    """Paged QC listing of raw position fixes. Each row carries distance,
    time gap and implied speed versus the vessel's PREVIOUS fix inside the
    filter window (equirectangular approx). A row is flagged SUSPECT via
    the spike rule: implied speed both INTO the fix (vs previous) and OUT
    of it (vs next) exceed threshold_kn - the classic outlier signature.
    The good fix right after a glitch only has a suspect incoming leg and
    is therefore NOT flagged, so one glitch marks exactly one row. At the
    window edges (no prev or no next) the single known leg decides, so a
    corrupt LAST fix - the one poisoning the live map - still flags.
    Two limitations, both by the nature of local tests: (1) an
    ALTERNATING zigzag (good/bad/good/bad) flags the whole disturbed
    stretch, because the good fixes bounce too - which alternation is real
    is locally undecidable; judge by the coordinate clusters. (2) Two
    consecutive corrupt fixes at the same wrong spot look calm in between;
    the implied-speed sort is the safety net there.
    mode selects the flag rule: "chain" (default) gates every fix against
    the last ACCEPTED fix - see _chain_flags; "spike" requires BOTH legs over
    the threshold - one isolated glitch marks exactly one row; "any"
    flags every fix touching a single too-fast leg, which marks the entry
    and exit of a multi-fix excursion (satellite gaps dilute implied
    speeds, and sequences look calm inside - deleting the flagged entry
    re-exposes the next corrupt fix, so a sequence peels off row by row).
    suspect_only filters to flagged rows. bbox=(lat_min, lat_max, lon_min,
    lon_max) limits the LISTING to the map viewport - flags are always
    computed over the full filtered set first, so zooming the map can
    never change the verdict. Sort via QC_SORTS whitelist.
    Returns (rows, total): rows are (ts, mmsi, name, lat, lon, sog,
    nav_status, source, dist_nm, dt_min, impl_kn, suspect)."""
    if mode == "chain":
        return _positions_qc_chain(mmsi=mmsi, t_from=t_from, t_to=t_to,
                                   source=source, threshold_kn=threshold_kn,
                                   suspect_only=suspect_only, bbox=bbox,
                                   sort=sort, page=page, page_size=page_size)
    order = QC_SORTS.get(sort) or QC_SORTS["ts_desc"]
    thr = float(threshold_kn or 30.0)
    any_mode = "TRUE" if mode == "any" else "FALSE"
    where, params = ["TRUE"], []
    if t_from is not None:
        where.append("p.ts >= %s"); params.append(t_from)
    if t_to is not None:
        where.append("p.ts < %s"); params.append(t_to)
    if mmsi:
        where.append("p.mmsi = %s"); params.append(int(mmsi))
    if source:
        where.append("p.source = %s"); params.append(source)
    sql = f"""
        WITH base AS (
            SELECT p.ts, p.mmsi, p.lat, p.lon, p.sog, p.nav_status, p.source,
                   lag(p.ts)   OVER w AS pts,
                   lag(p.lat)  OVER w AS plat,
                   lag(p.lon)  OVER w AS plon,
                   lead(p.ts)  OVER w AS nts,
                   lead(p.lat) OVER w AS nlat,
                   lead(p.lon) OVER w AS nlon
            FROM positions p
            WHERE {' AND '.join(where)}
            WINDOW w AS (PARTITION BY p.mmsi ORDER BY p.ts)
        ), calc AS (
            SELECT b.*, f.name,
                   CASE WHEN b.pts IS NOT NULL THEN
                       60.0 * sqrt(power(b.lat - b.plat, 2)
                           + power(cos(radians((b.lat + b.plat) / 2.0))
                                   * (b.lon - b.plon), 2))
                   END AS dist_nm,
                   CASE WHEN b.pts IS NOT NULL THEN
                       EXTRACT(EPOCH FROM (b.ts - b.pts)) / 60.0
                   END AS dt_min,
                   CASE WHEN b.nts IS NOT NULL THEN
                       60.0 * sqrt(power(b.nlat - b.lat, 2)
                           + power(cos(radians((b.nlat + b.lat) / 2.0))
                                   * (b.nlon - b.lon), 2))
                   END AS ndist_nm,
                   CASE WHEN b.nts IS NOT NULL THEN
                       EXTRACT(EPOCH FROM (b.nts - b.ts)) / 60.0
                   END AS ndt_min
            FROM base b LEFT JOIN fleet f ON f.mmsi = b.mmsi
        ), final AS (
            SELECT ts, mmsi, name, lat, lon, sog, nav_status, source,
                   dist_nm, dt_min,
                   CASE WHEN dt_min > 0 THEN dist_nm / (dt_min / 60.0)
                   END AS impl_in,
                   CASE WHEN ndt_min > 0 THEN ndist_nm / (ndt_min / 60.0)
                   END AS impl_out
            FROM calc
        ), flagged AS (
            SELECT ts, mmsi, name, lat, lon, sog, nav_status, source,
                   dist_nm, dt_min, impl_in AS impl_kn,
                   CASE
                     WHEN {any_mode}
                          THEN (COALESCE(impl_in, 0) > {thr}
                                OR COALESCE(impl_out, 0) > {thr})
                     WHEN impl_in IS NOT NULL AND impl_out IS NOT NULL
                          THEN (impl_in > {thr} AND impl_out > {thr})
                     WHEN impl_in IS NOT NULL THEN impl_in > {thr}
                     WHEN impl_out IS NOT NULL THEN impl_out > {thr}
                     ELSE FALSE
                   END AS suspect
            FROM final
        )
        SELECT ts, mmsi, name, lat, lon, sog, nav_status, source,
               dist_nm, dt_min, impl_kn, suspect,
               count(*) OVER () AS total_rows
        FROM flagged"""
    outer = []
    if suspect_only:
        outer.append("suspect")
    if bbox:
        outer.append("lat BETWEEN %s AND %s AND lon BETWEEN %s AND %s")
        la0, la1, lo0, lo1 = bbox
        params += [la0, la1, lo0, lo1]
    if outer:
        sql += " WHERE " + " AND ".join(outer)
    page = max(1, int(page or 1))
    sql += f" ORDER BY {order} LIMIT %s OFFSET %s"
    params += [page_size, (page - 1) * page_size]
    rows = q(sql, params)
    total = rows[0][-1] if rows else 0
    return [r[:-1] for r in rows], total


def position_delete(mmsi, ts, source):
    """Delete one stored fix (QC cleanup of corrupt AIS decodes). If the
    `latest` snapshot pointed at the deleted fix, rewind it to the newest
    remaining position so the live map heals immediately."""
    q("DELETE FROM positions WHERE mmsi=%s AND ts=%s AND source=%s",
      (mmsi, ts, source))
    q("""UPDATE latest SET ts=p.ts, lat=p.lat, lon=p.lon, sog=p.sog,
                cog=p.cog, heading=p.heading, nav_status=p.nav_status
         FROM (SELECT ts, lat, lon, sog, cog, heading, nav_status
               FROM positions WHERE mmsi=%s
               ORDER BY ts DESC LIMIT 1) p
         WHERE latest.mmsi=%s AND latest.ts=%s""", (mmsi, mmsi, ts))


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
                  l.ship_name AS ais_name, l.lat, l.lon, f.vessel_type,
                  f.length_m, f.beam_m
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


# --- fleet editing -----------------------------------------------------------
_FLEET_EDITABLE = ("name", "owner", "operator", "built", "flag", "region",
                   "tier", "notes", "mmsi", "imo", "vessel_type")


def fleet_update(imo, updates):
    """Update whitelisted fleet columns for one vessel. Changing IMO (the
    primary key) also moves the sv_ship mapping along."""
    fields = {k: v for k, v in updates.items() if k in _FLEET_EDITABLE}
    if not fields:
        return
    new_imo = fields.pop("imo", None)
    if fields:
        cols = ", ".join(f"{k}=%s" for k in fields)
        q(f"UPDATE fleet SET {cols}, updated_at=now() WHERE imo=%s",
          (*fields.values(), imo))
    if new_imo and int(new_imo) != int(imo):
        q("UPDATE fleet SET imo=%s, updated_at=now() WHERE imo=%s", (new_imo, imo))
        q("UPDATE sv_ship SET imo=%s WHERE imo=%s", (new_imo, imo))


def fleet_ais_name(mmsi):
    """AIS-broadcast name for a vessel, if any collector has heard it."""
    rows = q("SELECT ship_name FROM latest WHERE mmsi=%s", (mmsi,))
    return rows[0][0] if rows and rows[0][0] else None


# --- region classification ---------------------------------------------------
def region_from_position(lat, lon):
    """Map a position to the fleet's region vocabulary:
    Americas, Caspian, AG, ME, Europe, Africa, Asia. Rough bounding boxes,
    checked in a deliberate order (Caspian before AG/Europe, etc.)."""
    if lat is None or lon is None:
        return None
    if lon < -30:
        return "Americas"
    if 36 <= lat <= 47.5 and 46 <= lon <= 55.5:
        return "Caspian"
    if 22 <= lat <= 31 and 46 <= lon <= 60:
        return "AG"
    if 11 <= lat <= 30 and 32 <= lon <= 45:
        return "ME"           # Red Sea corridor
    if lat >= 35 and -12 <= lon <= 42:
        return "Europe"       # North Sea, Med, Black Sea
    if lat < 36 and -20 <= lon <= 52:
        return "Africa"
    return "Asia"


def fleet_backfill_mmsi():
    """Fill fleet.mmsi from the SeaVantage mapping (sv_ship) for vessels
    that were added by IMO only. The tracker joins latest<->fleet on MMSI,
    so a NULL fleet.mmsi hides the vessel's type/name from the map pages
    even though SeaVantage already told us the MMSI. Fills NULLs only,
    never overwrites, and skips an MMSI already claimed by another fleet
    row (fleet.mmsi is UNIQUE). Returns the number of rows filled."""
    rows = q("""UPDATE fleet f SET mmsi = s.mmsi
                FROM sv_ship s
                WHERE s.imo = f.imo AND f.mmsi IS NULL
                  AND s.mmsi IS NOT NULL AND s.mmsi > 0
                  AND NOT EXISTS (SELECT 1 FROM fleet f2
                                  WHERE f2.mmsi = s.mmsi)
                RETURNING f.imo""")
    return len(rows or [])


def fleet_auto_update_regions():
    """Refresh fleet.region from each vessel's last known position.
    Returns the number of vessels whose region changed."""
    rows = q(
        """SELECT f.imo, f.region, l.lat, l.lon
           FROM fleet f JOIN latest l ON l.mmsi = f.mmsi
           WHERE f.active"""
    )
    changed = 0
    for imo, region, lat, lon in rows:
        new = region_from_position(lat, lon)
        if new and new != region:
            q("UPDATE fleet SET region=%s, updated_at=now() WHERE imo=%s",
              (new, imo))
            changed += 1
    return changed


def latest_positions():
    """All vessels present in the track database (latest fix per vessel),
    with the fleet name as primary label. Ordered by name."""
    return q(
        """SELECT l.mmsi,
                  COALESCE(f.name, initcap(lower(l.ship_name)), l.mmsi::text) AS name,
                  l.ts, l.lat, l.lon, l.sog, l.nav_status, l.destination,
                  f.vessel_type, l.heading, l.cog, l.length_m
           FROM latest l
           LEFT JOIN fleet f ON f.mmsi = l.mmsi
           ORDER BY name"""
    )


def latest_info(mmsi):
    """All fields the map info-popup shows for one vessel: current fix,
    voyage data (destination/ETA/draught) and fleet metadata. Returns a
    dict or None."""
    rows = q(
        """SELECT l.mmsi,
                  COALESCE(f.name, initcap(lower(l.ship_name)),
                           l.mmsi::text)               AS name,
                  l.ts, l.lat, l.lon, l.sog, l.cog, l.heading, l.nav_status,
                  l.destination, l.eta, l.draught, l.callsign,
                  f.vessel_type, f.flag, f.imo, l.length_m, l.beam_m
           FROM latest l
           LEFT JOIN fleet f ON f.mmsi = l.mmsi
           WHERE l.mmsi = %s""", (mmsi,))
    if not rows:
        return None
    r = rows[0]
    keys = ("mmsi", "name", "ts", "lat", "lon", "sog", "cog", "heading",
            "nav_status", "destination", "eta", "draught", "callsign",
            "vessel_type", "flag", "imo", "length_m", "beam_m")
    return dict(zip(keys, r))


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


def fleet_insert(fields):
    """Add a new vessel. Name and IMO are mandatory; IMO must be unique.
    Returns an error string, or None on success."""
    name = (fields.get("name") or "").strip()
    imo = (fields.get("imo") or "").strip()
    if not name or not imo or not (fields.get("vessel_type") or "").strip():
        return "Name, IMO and vessel type are mandatory."
    if not (imo.isdigit() and len(imo) == 7):
        return f"IMO must be 7 digits, got '{imo}'."
    if q("SELECT 1 FROM fleet WHERE imo=%s", (int(imo),)):
        return f"IMO {imo} already exists in the fleet."
    mmsi = (fields.get("mmsi") or "").strip()
    if mmsi and not mmsi.isdigit():
        return f"MMSI must be numeric, got '{mmsi}'."
    if mmsi and q("SELECT 1 FROM fleet WHERE mmsi=%s", (int(mmsi),)):
        return f"MMSI {mmsi} already exists in the fleet."
    q("""INSERT INTO fleet (imo, mmsi, name, owner, operator, built, flag,
                            region, tier, notes, vessel_type, active)
         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)""",
      (int(imo), int(mmsi) if mmsi else None, name,
       fields.get("owner") or None, fields.get("operator") or None,
       fields.get("built") or None, fields.get("flag") or None,
       fields.get("region") or None, fields.get("tier") or None,
       fields.get("notes") or None, fields.get("vessel_type") or None))
    return None


def fleet_import_from_sv(imo, mmsi, name):
    """Insert a vessel discovered in the SeaVantage workspace but missing
    from our fleet. vessel_type stays NULL on purpose: the mandatory-type
    rule is enforced on the next manual edit. Returns True if inserted."""
    if q("SELECT 1 FROM fleet WHERE imo=%s", (int(imo),)):
        return False
    if mmsi and q("SELECT 1 FROM fleet WHERE mmsi=%s", (int(mmsi),)):
        return False
    q("""INSERT INTO fleet (imo, mmsi, name, notes, active)
         VALUES (%s,%s,%s,'imported from SeaVantage workspace',TRUE)""",
      (int(imo), int(mmsi) if mmsi else None, name))
    return True


def fleet_auto_update_dims():
    """Copy AIS-derived dimensions (latest.length_m/beam_m) onto the fleet.
    AIS is authoritative here: values are overwritten whenever they differ.
    Returns the number of vessels updated."""
    rows = q(
        """UPDATE fleet f SET length_m=l.length_m, beam_m=l.beam_m,
                              updated_at=now()
           FROM latest l
           WHERE l.mmsi = f.mmsi AND l.length_m IS NOT NULL
             AND (f.length_m IS DISTINCT FROM l.length_m
                  OR f.beam_m IS DISTINCT FROM l.beam_m)
           RETURNING 1"""
    )
    return len(rows)
