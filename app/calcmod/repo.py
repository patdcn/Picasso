"""
DCN Calculation Module - repository layer.

All SQL lives here. Pages call these functions only; engine.py consumes the
plain dicts these return. Every mutating operation on a revision's content is
journaled (edit_journal) which gives undo, audit trail and the live read-only
view (readers poll last_seq) in one mechanism.

Concurrency model: one estimator per Q number via a soft lock with heartbeat;
WAL mode allows any number of readers alongside the single writer.
"""
import json
import datetime

from app.calcmod.db import conn, new_uuid, ELEMENTS

LOCK_STALE_MIN = 10          # minutes without heartbeat before a lock is stealable

_ITEM_TABLES = {"equipment": ("equipment_items", "equipment_rates"),
                "personnel": ("personnel_items", "personnel_rates"),
                "misc": ("misc_items", "misc_rates")}


def _now():
    return datetime.datetime.utcnow().isoformat(timespec="seconds")


def _rows(c, sql, args=()):
    return [dict(r) for r in c.execute(sql, args).fetchall()]


def _row(c, sql, args=()):
    r = c.execute(sql, args).fetchone()
    return dict(r) if r else None


# ========================================================================== #
# Roles (user / super) - portal admins are super implicitly
# ========================================================================== #
ALL_DIVISIONS = ["CIV", "OFF", "HYD"]


def get_role(user_email):
    c = conn()
    try:
        r = _row(c, "SELECT role FROM calc_roles WHERE user=?", (user_email,))
        return r["role"] if r else None
    finally:
        c.close()


def set_role(user_email, role):
    c = conn()
    try:
        if role in ("user", "super"):
            c.execute("INSERT INTO calc_roles (user, role) VALUES (?,?) "
                      "ON CONFLICT(user) DO UPDATE SET role=excluded.role",
                      (user_email, role))
        else:
            c.execute("DELETE FROM calc_roles WHERE user=?", (user_email,))
        c.commit()
    finally:
        c.close()


def list_roles():
    c = conn()
    try:
        return _rows(c, "SELECT * FROM calc_roles ORDER BY user")
    finally:
        c.close()


def get_grant(user_email, division):
    """Compat shim for the pages: derives the old grant shape from the role.
    Any role -> edit in every division; super carries the moderator flag.
    No role -> None (page access alone = read-only)."""
    role = get_role(user_email)
    if role is None:
        return None
    return {"level": "edit", "lib_admin": 1 if role == "super" else 0}


def visible_divisions(user_email, is_admin=False):
    if is_admin or get_role(user_email):
        return list(ALL_DIVISIONS)
    return list(ALL_DIVISIONS)      # read-only viewers still see all divisions


def is_lib_admin(user_email, is_admin=False):
    return bool(is_admin or get_role(user_email) == "super")


# ========================================================================== #
# Rate sets, FX, libraries, markups
# ========================================================================== #
def list_rate_sets():
    c = conn()
    try:
        return _rows(c, "SELECT * FROM rate_sets ORDER BY id DESC")
    finally:
        c.close()


def active_rate_set():
    c = conn()
    try:
        return _row(c, "SELECT * FROM rate_sets WHERE status='active' ORDER BY id DESC LIMIT 1")
    finally:
        c.close()


def create_rate_set(label, user, copy_from_id=None):
    """New DRAFT rate set; optionally bulk-copies all rates/fx/markups from an
    existing set so the admin only edits what changed. Activation is separate."""
    c = conn()
    try:
        c.execute("INSERT INTO rate_sets (label, status, created_by) VALUES (?,?,?)",
                  (label, "draft", user))
        new_id = c.execute("SELECT id FROM rate_sets WHERE label=?", (label,)).fetchone()["id"]
        if copy_from_id:
            c.execute("INSERT INTO exchange_rates (rate_set_id, currency, rate_to_usd) "
                      "SELECT ?, currency, rate_to_usd FROM exchange_rates WHERE rate_set_id=?",
                      (new_id, copy_from_id))
            c.execute("INSERT INTO equipment_rates (item_uuid, rate_set_id, currency, rate) "
                      "SELECT item_uuid, ?, currency, rate FROM equipment_rates WHERE rate_set_id=?",
                      (new_id, copy_from_id))
            c.execute("INSERT INTO personnel_rates (item_uuid, rate_set_id, currency, "
                      "office_rate, yard_rate, offshore_rate) "
                      "SELECT item_uuid, ?, currency, office_rate, yard_rate, offshore_rate "
                      "FROM personnel_rates WHERE rate_set_id=?", (new_id, copy_from_id))
            c.execute("INSERT INTO misc_rates (item_uuid, rate_set_id, currency, rate) "
                      "SELECT item_uuid, ?, currency, rate FROM misc_rates WHERE rate_set_id=?",
                      (new_id, copy_from_id))
            c.execute("INSERT INTO markup_sets (rate_set_id, division, region, levy_local_pct, "
                      "levy_expat_pct, profit_pct, risk_pct, overhead_pct, margin_pct) "
                      "SELECT ?, division, region, levy_local_pct, levy_expat_pct, profit_pct, "
                      "risk_pct, overhead_pct, margin_pct FROM markup_sets WHERE rate_set_id=?",
                      (new_id, copy_from_id))
        c.commit()
        return new_id
    finally:
        c.close()


def activate_rate_set(rate_set_id):
    """Moderated action: the new set becomes active, the previous active set
    is archived. Existing calcs are untouched (snapshot principle)."""
    c = conn()
    try:
        c.execute("UPDATE rate_sets SET status='archived' WHERE status='active'")
        c.execute("UPDATE rate_sets SET status='active' WHERE id=?", (rate_set_id,))
        c.commit()
    finally:
        c.close()


def get_fx(rate_set_id):
    c = conn()
    try:
        return {r["currency"]: r["rate_to_usd"] for r in
                c.execute("SELECT currency, rate_to_usd FROM exchange_rates WHERE rate_set_id=?",
                          (rate_set_id,))}
    finally:
        c.close()


def set_fx(rate_set_id, currency, rate_to_usd):
    c = conn()
    try:
        c.execute("INSERT INTO exchange_rates (rate_set_id, currency, rate_to_usd) VALUES (?,?,?) "
                  "ON CONFLICT(rate_set_id, currency) DO UPDATE SET rate_to_usd=excluded.rate_to_usd",
                  (rate_set_id, currency, rate_to_usd))
        c.commit()
    finally:
        c.close()


def add_currency(code, name, symbol=None):
    c = conn()
    try:
        c.execute("INSERT OR IGNORE INTO currencies VALUES (?,?,?)", (code, name, symbol))
        c.commit()
    finally:
        c.close()


def deactivate_item(lib, item_uuid):
    """Soft delete: the item disappears from library lists and pickers.
    Existing calcs are untouched (their snapshots are self-contained)."""
    tbl, _el = base_lib(lib)
    it, _ = _ITEM_TABLES[tbl]
    c = conn()
    try:
        c.execute(f"UPDATE {it} SET active=0 WHERE uuid=?", (item_uuid,))
        c.commit()
    finally:
        c.close()


def fetch_live_fx(rate_set_id, fetcher=None):
    """Update rate_to_usd for every non-USD currency in the currencies table
    from internet exchange rates (frankfurter.app, ECB data; no API key).

    Returns (updated: dict, errors: list). `fetcher` is injectable for tests.
    Interim solution as agreed - a curated FX table per rate set remains the
    system of record; this only fills it."""
    import json as _json
    import urllib.request

    ENDPOINTS = (        # tried in order; all free, no API key
        "https://api.frankfurter.dev/v1/latest?base=USD",
        "https://api.frankfurter.app/latest?from=USD",
        "https://open.er-api.com/v6/latest/USD",
    )

    def _default_fetcher():
        last_err = None
        for url in ENDPOINTS:
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "DCN-Picasso-Portal/1.0 (engineering tool)",
                    "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = _json.loads(r.read().decode())
                if data.get("rates"):
                    return data
                last_err = RuntimeError(f"{url}: no rates in response")
            except Exception as e:                      # try the next endpoint
                last_err = e
        raise last_err or RuntimeError("no FX endpoint reachable")

    try:
        data = (fetcher or _default_fetcher)()
        rates = data.get("rates") or {}
    except Exception as e:
        return {}, [f"Could not fetch live rates ({e}) - set rates manually below."]
    updated, errors = {}, []
    for cur in [c["code"] for c in list_currencies()]:
        if cur == "USD":
            set_fx(rate_set_id, "USD", 1.0)
            continue
        if cur in rates and rates[cur]:
            val = 1.0 / float(rates[cur])       # 1 CUR -> USD
            set_fx(rate_set_id, cur, round(val, 6))
            updated[cur] = round(val, 6)
        else:
            errors.append(f"No live rate for {cur}")
    return updated, errors


def list_currencies():
    c = conn()
    try:
        return _rows(c, "SELECT * FROM currencies ORDER BY code")
    finally:
        c.close()


def list_items(lib, division=None, active_only=True, with_rates_for=None,
               region=None, calc_region=None):
    """Library items (lib may be a virtual library: materials/subcontracting).

    with_rates_for: rate_set_id -> joins the single rate row per item.
    region: exact item-region filter. calc_region: items usable for a calc in
    that region (item region == calc_region or 'ALL')."""
    tbl, el = base_lib(lib)
    it, rt = _ITEM_TABLES[tbl]
    c = conn()
    try:
        where, args = [], []
        if division:
            where.append("i.division=?"); args.append(division)
        if active_only:
            where.append("i.active=1")
        if region:
            where.append("i.region=?"); args.append(region)
        if calc_region:
            where.append("i.region IN (?, 'ALL')"); args.append(calc_region)
        if el:
            where.append("i.category IN (SELECT name FROM misc_categories "
                         "WHERE element=?)")
            args.append(el)
        w = ("WHERE " + " AND ".join(where)) if where else ""
        items = _rows(c, f"SELECT i.* FROM {it} i {w} ORDER BY i.code", args)
        if with_rates_for:
            rs = with_rates_for if not isinstance(with_rates_for, tuple)                 else with_rates_for[0]
            rate_fields = (("office_rate", "yard_rate", "offshore_rate")
                           if tbl == "personnel" else ("rate",))
            for i in items:
                r = _rate_for(c, tbl, i["uuid"], rs) or {}
                i["currency"] = r.get("currency")
                for f in rate_fields:
                    i[f] = r.get(f)
        return items
    finally:
        c.close()


def find_item_by_code(lib, code=None, erp_no=None):
    """Existing item with this code or ERP number (any division), or None.
    Used to catch duplicates at check-in submission, before they reach the
    moderation queue - the DB UNIQUE constraints remain the hard backstop."""
    tbl, _el = base_lib(lib)
    it, _ = _ITEM_TABLES[tbl]
    c = conn()
    try:
        if code:
            r = _row(c, f"SELECT * FROM {it} WHERE code=?", (code,))
            if r:
                return r
        if erp_no:
            return _row(c, f"SELECT * FROM {it} WHERE erp_no=?", (erp_no,))
        return None
    finally:
        c.close()


def list_misc_categories(active_only=True):
    c = conn()
    try:
        w = "WHERE active=1" if active_only else ""
        return _rows(c, f"SELECT * FROM misc_categories {w} ORDER BY element, name")
    finally:
        c.close()


def set_misc_category(name, element, active=True):
    c = conn()
    try:
        c.execute("INSERT INTO misc_categories (name, element, active) VALUES (?,?,?) "
                  "ON CONFLICT(name) DO UPDATE SET element=excluded.element, "
                  "active=excluded.active", (name.strip().lower(), element,
                                             1 if active else 0))
        c.commit()
    finally:
        c.close()


CODE_PREFIX = {"personnel": "P", "equipment": "E",
               "materials": "M", "subcontracting": "S"}
DIV_LETTER = {"CIV": "C", "OFF": "O", "HYD": "H"}
OWN_LETTER = {"internal": "I", "external": "E"}
REGION_LETTER = {"EUR": "E", "WAF": "W", "UAE": "U", "SEA": "S", "ALL": "A"}

# The four user-facing libraries map to three tables: materials and
# subcontracting are virtual views on misc, distinguished by their
# sub-category's element mapping.
VIRTUAL_LIBS = {"materials": ("misc", "materials"),
                "subcontracting": ("misc", "subcontracting")}

_LBL_LIB = {"P": "Pers", "E": "Equip", "M": "Mat", "S": "Subc"}
_LBL_DIV = {"C": "Civ", "O": "Off", "H": "Hyd"}
_LBL_OWN = {"I": "Int", "E": "Ext"}
_LBL_REG = {"E": "Eur", "W": "Waf", "U": "Uae", "S": "Sea", "A": "AllReg"}


def code_label(code):
    """Human-readable expansion: E-O-E-E-0001 -> 'Equip-Off-Ext-Eur-0001'."""
    parts = (code or "").split("-")
    if len(parts) != 5:
        return ""
    lib, div, own, reg, num = parts
    bits = [_LBL_LIB.get(lib), _LBL_DIV.get(div), _LBL_OWN.get(own),
            _LBL_REG.get(reg), num]
    if any(b is None for b in bits):
        return ""
    return "-".join(bits)


def base_lib(lib):
    """(table_lib, element_filter) for a user-facing library name."""
    return VIRTUAL_LIBS.get(lib, (lib, None))


def suggest_code(lib, division, ownership="internal", region="ALL",
                 counterpart_uuid=None):
    """Suggest the next code.

    Format: P-O-I-A-0001 = library (P personnel / E equipment / M materials /
    S sub-contracting) - division (C/O/H) - ownership (I/E, personnel &
    equipment only) - region (E/W/U/S, A = all regions) - concept number.

    A Diver with genuinely different regional rates is separate items:
    P-O-I-E-0001 (EUR) and P-O-I-U-0001 (UAE) share the concept number 0001.
    With a counterpart chosen its number is reused; otherwise the next free
    number across the whole library table is allocated."""
    tbl, _el = base_lib(lib)
    it, _ = _ITEM_TABLES[tbl]
    seg = [CODE_PREFIX[lib], DIV_LETTER.get(division, division),
           OWN_LETTER.get(ownership or "internal", "I"),
           REGION_LETTER.get(region or "ALL", "A")]
    c = conn()
    try:
        num = None
        if counterpart_uuid:
            r = _row(c, f"SELECT code FROM {it} WHERE uuid=?", (counterpart_uuid,))
            if r:
                tail = r["code"].rsplit("-", 1)[-1]
                num = tail if tail.isdigit() else None
        if num is None:
            nums = [0]
            for r in c.execute(f"SELECT code FROM {it}").fetchall():
                tail = r["code"].rsplit("-", 1)[-1]
                if tail.isdigit():
                    nums.append(int(tail))
            num = f"{max(nums) + 1:04d}"
        return "-".join(seg + [num])
    finally:
        c.close()


def counterpart_options(lib, division, region="ALL"):
    """Items of the same library in another division OR region - candidates
    for 'same concept elsewhere' number reuse."""
    tbl, el = base_lib(lib)
    it, _ = _ITEM_TABLES[tbl]
    c = conn()
    try:
        lbl = "function" if tbl == "personnel" else "description"
        rows = _rows(c, f"SELECT i.uuid, i.code, i.division, i.region, i.{lbl} AS label "
                        f"FROM {it} i WHERE i.active=1 "
                        "AND NOT (i.division=? AND i.region=?) ORDER BY i.code",
                     (division, region))
        if el:
            cats = {r["name"] for r in _rows(
                c, "SELECT name FROM misc_categories WHERE element=?", (el,))}
            rows = [r for r in rows if _row(
                c, f"SELECT category FROM {it} WHERE uuid=?",
                (r["uuid"],))["category"] in cats]
        return rows
    finally:
        c.close()


def item_default_element(lib, item):
    """Element a library pick prefills in the editor: personnel -> labor,
    equipment -> equipment, misc -> its category's mapped element."""
    if lib == "personnel":
        return "labor", item.get("ownership") or "internal"
    if lib == "equipment":
        return "equipment", item.get("ownership") or "internal"
    cat = (item.get("category") or "").strip().lower()
    c = conn()
    try:
        r = _row(c, "SELECT element FROM misc_categories WHERE name=?", (cat,))
        return (r["element"] if r else "subcontracting"), None
    finally:
        c.close()


def upsert_item(lib, data):
    """Admin/moderation path only. data: dict of item columns; uuid generated
    when absent. Returns the uuid."""
    tbl, _el = base_lib(lib)
    it, _ = _ITEM_TABLES[tbl]
    u = data.get("uuid") or new_uuid()
    if not data.get("ownership"):
        data = {**data, "ownership": "internal"}
    if not data.get("region"):
        data = {**data, "region": "ALL"}
    cols = {"equipment": ("erp_no", "code", "division", "description", "unit",
                          "ownership", "region", "notes"),
            "personnel": ("erp_no", "code", "division", "function", "ownership",
                          "unit", "region", "notes"),
            "misc": ("erp_no", "code", "division", "category", "description",
                     "unit", "ownership", "region")}[tbl]
    if tbl == "personnel" and not data.get("unit"):
        data = {**data, "unit": "day"}
    c = conn()
    try:
        names = ", ".join(("uuid",) + cols)
        ph = ", ".join("?" * (len(cols) + 1))
        upd = ", ".join(f"{k}=excluded.{k}" for k in cols)
        c.execute(f"INSERT INTO {it} ({names}) VALUES ({ph}) "
                  f"ON CONFLICT(uuid) DO UPDATE SET {upd}",
                  [u] + [data.get(k) for k in cols])
        c.commit()
        return u
    finally:
        c.close()


def _num(v):
    """Normalize UI values: '' and None -> None; numeric strings -> float."""
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def set_item_rate(lib, item_uuid, rate_set_id, currency, **kw):
    tbl, _el = base_lib(lib)
    _, rt = _ITEM_TABLES[tbl]
    kw = {k: _num(v) for k, v in kw.items()}
    c = conn()
    try:
        if tbl == "personnel":
            c.execute(f"INSERT INTO {rt} (item_uuid, rate_set_id, currency, "
                      "office_rate, yard_rate, offshore_rate) VALUES (?,?,?,?,?,?) "
                      "ON CONFLICT(item_uuid, rate_set_id) DO UPDATE SET "
                      "currency=excluded.currency, office_rate=excluded.office_rate, "
                      "yard_rate=excluded.yard_rate, offshore_rate=excluded.offshore_rate",
                      (item_uuid, rate_set_id, currency, kw.get("office_rate"),
                       kw.get("yard_rate"), kw.get("offshore_rate")))
        else:
            c.execute(f"INSERT INTO {rt} (item_uuid, rate_set_id, currency, rate) "
                      "VALUES (?,?,?,?) "
                      "ON CONFLICT(item_uuid, rate_set_id) DO UPDATE SET "
                      "currency=excluded.currency, rate=excluded.rate",
                      (item_uuid, rate_set_id, currency, kw.get("rate")))
        c.commit()
    finally:
        c.close()


def _rate_for(c, lib, item_uuid, rate_set_id):
    """The item's rate row for a rate set (region lives on the item now)."""
    _, rt = _ITEM_TABLES[base_lib(lib)[0]]
    return _row(c, f"SELECT * FROM {rt} WHERE item_uuid=? AND rate_set_id=?",
                (item_uuid, rate_set_id))


def get_markups(rate_set_id, division, region):
    c = conn()
    try:
        return _row(c, "SELECT * FROM markup_sets WHERE rate_set_id=? AND division=? AND region=?",
                    (rate_set_id, division, region))
    finally:
        c.close()


def set_markups(rate_set_id, division, region, **pcts):
    keys = ("levy_local_pct", "levy_expat_pct", "profit_pct", "risk_pct",
            "overhead_pct", "margin_pct")
    c = conn()
    try:
        c.execute("INSERT INTO markup_sets (rate_set_id, division, region, "
                  + ", ".join(keys) + ") VALUES (?,?,?,?,?,?,?,?,?) "
                  "ON CONFLICT(rate_set_id, division, region) DO UPDATE SET "
                  + ", ".join(f"{k}=excluded.{k}" for k in keys),
                  [rate_set_id, division, region] + [float(pcts.get(k) or 0) for k in keys])
        c.commit()
    finally:
        c.close()


# ========================================================================== #
# Moderation (check-in requests)
# ========================================================================== #
def submit_request(kind, division, payload, user, note=None):
    c = conn()
    try:
        c.execute("INSERT INTO library_requests (kind, division, payload_json, note, submitted_by) "
                  "VALUES (?,?,?,?,?)", (kind, division, json.dumps(payload), note, user))
        c.commit()
    finally:
        c.close()


def list_requests(status="submitted"):
    c = conn()
    try:
        rows = _rows(c, "SELECT * FROM library_requests WHERE status=? ORDER BY id", (status,))
        for r in rows:
            r["payload"] = json.loads(r["payload_json"])
        return rows
    finally:
        c.close()


def review_request(req_id, approve, reviewer, note=None):
    """Approval is what actually writes to the library - nothing lands directly."""
    c = conn()
    try:
        r = _row(c, "SELECT * FROM library_requests WHERE id=? AND status='submitted'", (req_id,))
        if not r:
            return "Request not found or already handled"
        if approve:
            payload = json.loads(r["payload_json"])
            try:
                _apply_request(payload, r["kind"], r["division"])
            except Exception as e:
                # e.g. duplicate code / ERP no (UNIQUE constraint): leave the
                # request in the queue and tell the reviewer why.
                return f"Could not apply: {e}"
        c.execute("UPDATE library_requests SET status=?, reviewed_by=?, reviewed_at=?, review_note=? "
                  "WHERE id=?", ("approved" if approve else "rejected", reviewer, _now(), note, req_id))
        c.commit()
        return None
    finally:
        c.close()


def _apply_request(payload, kind, division):
    if kind.endswith("_item"):
        lib = kind[:-5]
        item = dict(payload.get("item") or {})
        item["division"] = division
        u = upsert_item(lib, item)
        rs = (active_rate_set() or {}).get("id")
        rate_keys = ("rate", "office_rate", "yard_rate", "offshore_rate")
        for rr in payload.get("rates") or []:
            set_item_rate(lib, u, rr.get("rate_set_id") or rs,
                          rr.get("currency", "USD"),
                          **{k: rr.get(k) for k in rate_keys})
    elif kind == "rate_change":
        lib = payload["lib"]
        rate_keys = ("rate", "office_rate", "yard_rate", "offshore_rate")
        for rr in payload.get("rates") or []:
            set_item_rate(lib, payload["item_uuid"],
                          rr.get("rate_set_id") or (active_rate_set() or {}).get("id"),
                          rr.get("currency", "USD"),
                          **{k: rr.get(k) for k in rate_keys})
    elif kind == "block_template":
        c = conn()
        try:
            c.execute("INSERT INTO block_templates (uuid, division, name, unit_label, "
                      "payload_json, source_qnumber, created_by) VALUES (?,?,?,?,?,?,?) "
                      "ON CONFLICT(division, name) DO UPDATE SET payload_json=excluded.payload_json, "
                      "unit_label=excluded.unit_label",
                      (new_uuid(), division, payload["name"], payload.get("unit_label", "day"),
                       json.dumps(payload["block"]), payload.get("source_qnumber"),
                       payload.get("submitted_by")))
            c.commit()
        finally:
            c.close()


def list_block_templates(division):
    c = conn()
    try:
        rows = _rows(c, "SELECT * FROM block_templates WHERE division=? AND active=1 ORDER BY name",
                     (division,))
        for r in rows:
            r["block"] = json.loads(r["payload_json"])
        return rows
    finally:
        c.close()


# ========================================================================== #
# Calculations & revisions
# ========================================================================== #
Q_PREFIX_REGIONS = {"EUR": "Q0", "SEA": "Q0", "WAF": "UQ0", "UAE": "UQ0"}


def validate_qnumber(qnumber, region):
    """Naming convention: EUR/SEA -> Q0XXXX, WAF/UAE -> UQ0XXXX.
    Returns an error message or None."""
    import re
    q = (qnumber or "").strip().upper()
    want = Q_PREFIX_REGIONS.get(region)
    if want is None:
        return f"Unknown region '{region}'."
    if not re.fullmatch(want + r"\d{4}", q):
        other = "UQ0XXXX (WAF/UAE)" if want == "Q0" else "Q0XXXX (EUR/SEA)"
        return (f"For region {region} the Q number must be {want}XXXX "
                f"(e.g. {want}1234) - not {other.split()[0]}-style.")
    return None


def list_calcs(divisions, include_archived=False):
    if not divisions:
        return []
    c = conn()
    try:
        ph = ",".join("?" * len(divisions))
        arch = "" if include_archived else "AND cal.archived=0"
        return _rows(c, f"""
            SELECT cal.*, MAX(r.rev_no) AS latest_rev,
                   (SELECT status FROM revisions r2 WHERE r2.qnumber=cal.qnumber
                     ORDER BY rev_no DESC LIMIT 1) AS latest_status,
                   l.user AS locked_by, l.heartbeat_at
            FROM calculations cal
            LEFT JOIN revisions r ON r.qnumber = cal.qnumber
            LEFT JOIN locks l ON l.qnumber = cal.qnumber
            WHERE cal.division IN ({ph}) {arch}
            GROUP BY cal.qnumber ORDER BY cal.qnumber DESC""", list(divisions))
    finally:
        c.close()


def get_calc(qnumber):
    c = conn()
    try:
        return _row(c, "SELECT * FROM calculations WHERE qnumber=?", (qnumber,))
    finally:
        c.close()


def get_revisions(qnumber):
    c = conn()
    try:
        return _rows(c, "SELECT * FROM revisions WHERE qnumber=? ORDER BY rev_no", (qnumber,))
    finally:
        c.close()


def get_revision(qnumber, rev_no=None):
    c = conn()
    try:
        if rev_no is None:
            return _row(c, "SELECT * FROM revisions WHERE qnumber=? ORDER BY rev_no DESC LIMIT 1",
                        (qnumber,))
        return _row(c, "SELECT * FROM revisions WHERE qnumber=? AND rev_no=?", (qnumber, rev_no))
    finally:
        c.close()


def create_calc(qnumber, title, client, division, region, user):
    """New calc -> revision 0 (working) with a master block and markups/fx
    snapshotted from the ACTIVE rate set. Q numbers come from Business Central
    and are entered, never generated here."""
    err = validate_qnumber(qnumber, region)
    if err:
        raise ValueError(err)
    rs = active_rate_set()
    c = conn()
    try:
        c.execute("INSERT INTO calculations (qnumber, title, client, division, region, created_by) "
                  "VALUES (?,?,?,?,?,?)", (qnumber, title, client, division, region, user))
        c.execute("INSERT INTO revisions (qnumber, rev_no, created_by, rate_set_label) "
                  "VALUES (?,0,?,?)", (qnumber, user, rs["label"] if rs else None))
        rev_id = c.execute("SELECT id FROM revisions WHERE qnumber=? AND rev_no=0",
                           (qnumber,)).fetchone()["id"]
        c.execute("INSERT INTO blocks (revision_id, kind, name, unit_label) "
                  "VALUES (?,'master',?, 'lump')", (rev_id, f"{qnumber} \u2014 {title}"))
        if rs:
            _snapshot_fx_markups(c, rev_id, rs["id"], division, region)
        c.commit()
        return rev_id
    finally:
        c.close()


def _snapshot_fx_markups(c, rev_id, rate_set_id, division, region):
    for cur, r in c.execute("SELECT currency, rate_to_usd FROM exchange_rates "
                            "WHERE rate_set_id=?", (rate_set_id,)).fetchall():
        c.execute("INSERT OR REPLACE INTO snap_fx (revision_id, currency, rate_to_usd) "
                  "VALUES (?,?,?)", (rev_id, cur, r))
    m = c.execute("SELECT * FROM markup_sets WHERE rate_set_id=? AND division=? AND region=?",
                  (rate_set_id, division, region)).fetchone()
    vals = (m["levy_local_pct"], m["levy_expat_pct"], m["profit_pct"], m["risk_pct"],
            m["overhead_pct"], m["margin_pct"]) if m else (0, 0, 0, 0, 0, 0)
    c.execute("INSERT OR REPLACE INTO snap_markups (revision_id, levy_local_pct, levy_expat_pct, "
              "profit_pct, risk_pct, overhead_pct, margin_pct) VALUES (?,?,?,?,?,?,?)",
              (rev_id,) + vals)


def _copy_revision_content(c, src_rev_id, dst_rev_id):
    """Copy snapshots + full block tree (+lines/refs) between revisions."""
    c.execute("INSERT INTO snap_fx (revision_id, currency, rate_to_usd) "
              "SELECT ?, currency, rate_to_usd FROM snap_fx WHERE revision_id=?",
              (dst_rev_id, src_rev_id))
    c.execute("INSERT INTO snap_markups (revision_id, levy_local_pct, levy_expat_pct, profit_pct, "
              "risk_pct, overhead_pct, margin_pct) "
              "SELECT ?, levy_local_pct, levy_expat_pct, profit_pct, risk_pct, overhead_pct, "
              "margin_pct FROM snap_markups WHERE revision_id=?", (dst_rev_id, src_rev_id))
    snap_map = {}
    for s in c.execute("SELECT * FROM snap_items WHERE revision_id=?", (src_rev_id,)).fetchall():
        c.execute("INSERT INTO snap_items (revision_id, lib, item_uuid, erp_no, code, description, "
                  "unit, ownership, currency, rate, office_rate, yard_rate, offshore_rate, "
                  "rate_set_label, imported_from) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (dst_rev_id, s["lib"], s["item_uuid"], s["erp_no"], s["code"], s["description"],
                   s["unit"], s["ownership"], s["currency"], s["rate"], s["office_rate"],
                   s["yard_rate"], s["offshore_rate"], s["rate_set_label"], s["imported_from"]))
        snap_map[s["id"]] = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    block_map = {}
    src_blocks = c.execute("SELECT * FROM blocks WHERE revision_id=? ORDER BY id",
                           (src_rev_id,)).fetchall()
    for b in src_blocks:
        c.execute("INSERT INTO blocks (revision_id, parent_id, kind, name, unit_label, sort_order, "
                  "start_date, end_date, notes) VALUES (?,?,?,?,?,?,?,?,?)",
                  (dst_rev_id, None, b["kind"], b["name"], b["unit_label"], b["sort_order"],
                   b["start_date"], b["end_date"], b["notes"]))
        block_map[b["id"]] = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    for b in src_blocks:                      # re-parent after ids are known
        if b["parent_id"]:
            c.execute("UPDATE blocks SET parent_id=? WHERE id=?",
                      (block_map[b["parent_id"]], block_map[b["id"]]))
    for ln in c.execute("SELECT * FROM block_lines WHERE block_id IN "
                        "(SELECT id FROM blocks WHERE revision_id=?)", (src_rev_id,)).fetchall():
        c.execute("INSERT INTO block_lines (block_id, element, snap_item_id, description, qty, "
                  "duration, rate_basis, unit_rate_override, origin, sort_order) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (block_map[ln["block_id"]], ln["element"],
                   snap_map.get(ln["snap_item_id"]), ln["description"], ln["qty"], ln["duration"],
                   ln["rate_basis"], ln["unit_rate_override"], ln["origin"], ln["sort_order"]))
    for rf in c.execute("SELECT * FROM block_refs WHERE host_block_id IN "
                        "(SELECT id FROM blocks WHERE revision_id=?)", (src_rev_id,)).fetchall():
        c.execute("INSERT INTO block_refs (host_block_id, ref_block_id, qty, sort_order) "
                  "VALUES (?,?,?,?)", (block_map[rf["host_block_id"]],
                                       block_map[rf["ref_block_id"]], rf["qty"], rf["sort_order"]))
    return block_map


def new_revision(qnumber, user, remark=None):
    """Amend: copy the latest revision into rev N+1 (working)."""
    src = get_revision(qnumber)
    c = conn()
    try:
        c.execute("INSERT INTO revisions (qnumber, rev_no, created_by, remark, rate_set_label) "
                  "VALUES (?,?,?,?,?)",
                  (qnumber, src["rev_no"] + 1, user, remark, src["rate_set_label"]))
        dst = c.execute("SELECT id FROM revisions WHERE qnumber=? AND rev_no=?",
                        (qnumber, src["rev_no"] + 1)).fetchone()["id"]
        _copy_revision_content(c, src["id"], dst)
        c.commit()
        return dst
    finally:
        c.close()


def duplicate_calc(src_qnumber, new_qnumber, title, client, user, src_rev_no=None):
    """Save-as-new-calculation: chosen (default latest) revision becomes rev 0
    of a fresh Q number. Embedded rates come along unchanged - updating against
    the current library is a separate, explicit action (diff dialog)."""
    src_calc = get_calc(src_qnumber)
    src_rev = get_revision(src_qnumber, src_rev_no)
    c = conn()
    try:
        c.execute("INSERT INTO calculations (qnumber, title, client, division, region, created_by) "
                  "VALUES (?,?,?,?,?,?)", (new_qnumber, title, client,
                                           src_calc["division"], src_calc["region"], user))
        c.execute("INSERT INTO revisions (qnumber, rev_no, created_by, remark, rate_set_label) "
                  "VALUES (?,0,?,?,?)",
                  (new_qnumber, user, f"Duplicated from {src_qnumber} rev {src_rev['rev_no']}",
                   src_rev["rate_set_label"]))
        dst = c.execute("SELECT id FROM revisions WHERE qnumber=? AND rev_no=0",
                        (new_qnumber,)).fetchone()["id"]
        _copy_revision_content(c, src_rev["id"], dst)
        c.commit()
        return dst
    finally:
        c.close()


def issue_revision(qnumber, rev_no, user):
    c = conn()
    try:
        c.execute("UPDATE revisions SET status='issued', issued_by=?, issued_at=? "
                  "WHERE qnumber=? AND rev_no=? AND status='working'",
                  (user, _now(), qnumber, rev_no))
        c.commit()
    finally:
        c.close()


def set_archived(qnumber, archived=True):
    c = conn()
    try:
        c.execute("UPDATE calculations SET archived=? WHERE qnumber=?",
                  (1 if archived else 0, qnumber))
        c.commit()
    finally:
        c.close()


# ========================================================================== #
# Snapshots
# ========================================================================== #
def load_snapshot(rev_id):
    c = conn()
    try:
        items = {r["id"]: dict(r) for r in
                 c.execute("SELECT * FROM snap_items WHERE revision_id=?", (rev_id,)).fetchall()}
        fx = {r["currency"]: r["rate_to_usd"] for r in
              c.execute("SELECT currency, rate_to_usd FROM snap_fx WHERE revision_id=?",
                        (rev_id,)).fetchall()}
        mk = _row(c, "SELECT * FROM snap_markups WHERE revision_id=?", (rev_id,))
        return {"items": items, "fx": fx, "markups": mk or {}}
    finally:
        c.close()


def snapshot_item(rev_id, lib, item_uuid, user):
    """Embed one library item's CURRENT active-set rate into the revision.
    If already embedded, returns the existing snap id (a calc never re-reads
    the library implicitly)."""
    tbl, _el = base_lib(lib)
    c = conn()
    try:
        ex = c.execute("SELECT id FROM snap_items WHERE revision_id=? AND item_uuid=?",
                       (rev_id, item_uuid)).fetchone()
        if ex:
            return ex["id"]
        rs = active_rate_set()
        it_t, rt_t = _ITEM_TABLES[tbl]
        i = _row(c, f"SELECT * FROM {it_t} WHERE uuid=?", (item_uuid,))
        r = _rate_for(c, tbl, item_uuid, rs["id"] if rs else -1) or {}
        c.execute("INSERT INTO snap_items (revision_id, lib, item_uuid, erp_no, code, description, "
                  "unit, ownership, currency, rate, office_rate, yard_rate, offshore_rate, "
                  "rate_set_label) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (rev_id, tbl, item_uuid, i.get("erp_no"), i["code"],
                   i.get("description") or i.get("function"), i.get("unit"), i.get("ownership"),
                   r.get("currency", "USD"), r.get("rate"),
                   r.get("office_rate"), r.get("yard_rate"), r.get("offshore_rate"),
                   rs["label"] if rs else None))
        snap_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        _journal(c, rev_id, user, "snapshot.add",
                 {"table": "snap_items", "pk": snap_id, "after": {"item_uuid": item_uuid}})
        c.commit()
        return snap_id
    finally:
        c.close()


def diff_snapshot(rev_id, region=None):
    """Compare embedded rates against the current ACTIVE rate set.
    Returns [{snap_id, code, description, field, old, new, currency}]."""
    rs = active_rate_set()
    if not rs:
        return []
    out = []
    c = conn()
    try:
        for s in c.execute("SELECT * FROM snap_items WHERE revision_id=?", (rev_id,)).fetchall():
            cur = _rate_for(c, s["lib"], s["item_uuid"], rs["id"])
            if not cur:
                continue
            fields = (("office_rate", "yard_rate", "offshore_rate")
                      if s["lib"] == "personnel" else ("rate",))
            for f in fields:
                old, new = s[f], cur.get(f)
                if new is not None and (old is None or abs((old or 0) - new) > 1e-9):
                    out.append({"snap_id": s["id"], "lib": s["lib"], "code": s["code"],
                                "description": s["description"], "field": f,
                                "old": old, "new": new,
                                "currency": cur.get("currency", s["currency"])})
        return out
    finally:
        c.close()


def refresh_snapshot(rev_id, snap_ids, user, region=None):
    """Explicitly update selected embedded items to the current active set.
    Journaled per item so it is undoable."""
    rs = active_rate_set()
    c = conn()
    try:
        for sid in snap_ids:
            s = _row(c, "SELECT * FROM snap_items WHERE id=? AND revision_id=?", (sid, rev_id))
            if not s:
                continue
            cur = _rate_for(c, s["lib"], s["item_uuid"], rs["id"])
            if not cur:
                continue
            before = {k: s[k] for k in ("currency", "rate", "office_rate", "yard_rate",
                                        "offshore_rate", "rate_set_label")}
            after = {"currency": cur.get("currency", "USD"), "rate": cur.get("rate"),
                     "office_rate": cur.get("office_rate"), "yard_rate": cur.get("yard_rate"),
                     "offshore_rate": cur.get("offshore_rate"), "rate_set_label": rs["label"]}
            c.execute("UPDATE snap_items SET currency=?, rate=?, office_rate=?, yard_rate=?, "
                      "offshore_rate=?, rate_set_label=? WHERE id=?",
                      (after["currency"], after["rate"], after["office_rate"],
                       after["yard_rate"], after["offshore_rate"], after["rate_set_label"], sid))
            _journal(c, rev_id, user, "snapshot.refresh",
                     {"table": "snap_items", "pk": sid, "before": before, "after": after})
        c.commit()
    finally:
        c.close()


# ========================================================================== #
# Blocks, lines, refs (all journaled)
# ========================================================================== #
_LINE_COLS = ("block_id", "element", "snap_item_id", "description", "qty", "duration",
              "rate_basis", "unit_rate_override", "origin", "ownership", "sort_order")
_BLOCK_COLS = ("revision_id", "parent_id", "kind", "name", "unit_label", "sort_order",
               "start_date", "end_date", "notes")


def _journal(c, rev_id, user, action, delta):
    c.execute("INSERT INTO edit_journal (revision_id, user, action, delta_json) VALUES (?,?,?,?)",
              (rev_id, user, action, json.dumps(delta)))


def last_seq(rev_id):
    c = conn()
    try:
        r = c.execute("SELECT MAX(seq) FROM edit_journal WHERE revision_id=?", (rev_id,)).fetchone()
        return r[0] or 0
    finally:
        c.close()


def get_tree(rev_id):
    """Blocks + lines + refs for a revision as flat lists (engine/pages nest)."""
    c = conn()
    try:
        blocks = _rows(c, "SELECT * FROM blocks WHERE revision_id=? ORDER BY sort_order, id",
                       (rev_id,))
        lines = _rows(c, "SELECT * FROM block_lines WHERE block_id IN "
                         "(SELECT id FROM blocks WHERE revision_id=?) ORDER BY sort_order, id",
                      (rev_id,))
        refs = _rows(c, "SELECT * FROM block_refs WHERE host_block_id IN "
                        "(SELECT id FROM blocks WHERE revision_id=?) ORDER BY sort_order, id",
                     (rev_id,))
        return {"blocks": blocks, "lines": lines, "refs": refs}
    finally:
        c.close()


def add_block(rev_id, parent_id, kind, name, unit_label, user):
    c = conn()
    try:
        c.execute("INSERT INTO blocks (revision_id, parent_id, kind, name, unit_label) "
                  "VALUES (?,?,?,?,?)", (rev_id, parent_id, kind, name, unit_label))
        bid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        _journal(c, rev_id, user, "block.add", {"table": "blocks", "pk": bid})
        c.commit()
        return bid
    finally:
        c.close()


def update_block(rev_id, block_id, fields, user):
    allowed = {"name", "unit_label", "sort_order", "start_date", "end_date", "notes", "parent_id"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    c = conn()
    try:
        before = _row(c, "SELECT * FROM blocks WHERE id=?", (block_id,))
        sets = ", ".join(f"{k}=?" for k in fields)
        c.execute(f"UPDATE blocks SET {sets} WHERE id=? AND revision_id=?",
                  list(fields.values()) + [block_id, rev_id])
        _journal(c, rev_id, user, "block.update",
                 {"table": "blocks", "pk": block_id,
                  "before": {k: before[k] for k in fields}, "after": fields})
        c.commit()
    finally:
        c.close()


def _serialize_subtree(c, block_id):
    b = _row(c, "SELECT * FROM blocks WHERE id=?", (block_id,))
    lines = _rows(c, "SELECT * FROM block_lines WHERE block_id=?", (block_id,))
    refs = _rows(c, "SELECT * FROM block_refs WHERE host_block_id=?", (block_id,))
    kids = [r["id"] for r in c.execute("SELECT id FROM blocks WHERE parent_id=?",
                                       (block_id,)).fetchall()]
    return {"block": b, "lines": lines, "refs": refs,
            "children": [_serialize_subtree(c, k) for k in kids]}


def _restore_subtree(c, node, rev_id, parent_id, keep_ids=True):
    b = node["block"]
    if keep_ids:
        c.execute("INSERT INTO blocks (id, revision_id, parent_id, kind, name, unit_label, "
                  "sort_order, start_date, end_date, notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (b["id"], rev_id, parent_id, b["kind"], b["name"], b["unit_label"],
                   b["sort_order"], b["start_date"], b["end_date"], b["notes"]))
        new_id = b["id"]
    else:
        c.execute("INSERT INTO blocks (revision_id, parent_id, kind, name, unit_label, sort_order, "
                  "start_date, end_date, notes) VALUES (?,?,?,?,?,?,?,?,?)",
                  (rev_id, parent_id, b["kind"], b["name"], b["unit_label"], b["sort_order"],
                   b["start_date"], b["end_date"], b["notes"]))
        new_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    for ln in node["lines"]:
        cols = [k for k in _LINE_COLS if k != "block_id"]
        if keep_ids:
            c.execute(f"INSERT INTO block_lines (id, block_id, {', '.join(cols)}) "
                      f"VALUES (?,?,{','.join('?' * len(cols))})",
                      [ln["id"], new_id] + [ln[k] for k in cols])
        else:
            c.execute(f"INSERT INTO block_lines (block_id, {', '.join(cols)}) "
                      f"VALUES (?,{','.join('?' * len(cols))})",
                      [new_id] + [ln[k] for k in cols])
    for rf in node["refs"]:
        c.execute("INSERT INTO block_refs (host_block_id, ref_block_id, qty, sort_order) "
                  "VALUES (?,?,?,?)", (new_id, rf["ref_block_id"], rf["qty"], rf["sort_order"]))
    for kid in node["children"]:
        _restore_subtree(c, kid, rev_id, new_id, keep_ids=keep_ids)
    return new_id


def delete_block(rev_id, block_id, user):
    """Deletes a block AND its subtree; the whole subtree is journaled so undo
    restores it, including incoming refs from other blocks."""
    c = conn()
    try:
        b = _row(c, "SELECT * FROM blocks WHERE id=? AND revision_id=?", (block_id, rev_id))
        if not b or b["kind"] == "master":
            return "Cannot delete the master block"
        sub = _serialize_subtree(c, block_id)
        incoming = _rows(c, "SELECT * FROM block_refs WHERE ref_block_id=?", (block_id,))
        c.execute("DELETE FROM block_refs WHERE ref_block_id=?", (block_id,))
        c.execute("DELETE FROM blocks WHERE id=?", (block_id,))   # cascades
        _journal(c, rev_id, user, "block.delete",
                 {"subtree": sub, "incoming_refs": incoming, "parent_id": b["parent_id"]})
        c.commit()
        return None
    finally:
        c.close()


def add_line(rev_id, block_id, element, user, snap_item_id=None, description=None,
             qty=1, duration=1, rate_basis="unit", origin="local", ownership=None):
    c = conn()
    try:
        c.execute("INSERT INTO block_lines (block_id, element, snap_item_id, description, qty, "
                  "duration, rate_basis, origin, ownership) VALUES (?,?,?,?,?,?,?,?,?)",
                  (block_id, element, snap_item_id, description, qty, duration, rate_basis,
                   origin, ownership))
        lid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        _journal(c, rev_id, user, "line.add", {"table": "block_lines", "pk": lid})
        c.commit()
        return lid
    finally:
        c.close()


def update_line(rev_id, line_id, fields, user):
    allowed = {"element", "description", "qty", "duration", "rate_basis",
               "unit_rate_override", "origin", "ownership", "sort_order"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    c = conn()
    try:
        before = _row(c, "SELECT * FROM block_lines WHERE id=?", (line_id,))
        if not before:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        c.execute(f"UPDATE block_lines SET {sets} WHERE id=?",
                  list(fields.values()) + [line_id])
        _journal(c, rev_id, user, "line.update",
                 {"table": "block_lines", "pk": line_id,
                  "before": {k: before[k] for k in fields}, "after": fields})
        c.commit()
    finally:
        c.close()


def delete_line(rev_id, line_id, user):
    c = conn()
    try:
        before = _row(c, "SELECT * FROM block_lines WHERE id=?", (line_id,))
        if not before:
            return
        c.execute("DELETE FROM block_lines WHERE id=?", (line_id,))
        _journal(c, rev_id, user, "line.delete", {"table": "block_lines", "row": before})
        c.commit()
    finally:
        c.close()


def would_create_cycle(rev_id, host_block_id, ref_block_id):
    """True if referencing ref from host would create a cycle (directly or via
    the structural parent chain combined with existing refs)."""
    tree = get_tree(rev_id)
    children = {}
    for b in tree["blocks"]:
        children.setdefault(b["parent_id"], []).append(b["id"])
    ref_out = {}
    for r in tree["refs"]:
        ref_out.setdefault(r["host_block_id"], []).append(r["ref_block_id"])
    ref_out.setdefault(host_block_id, []).append(ref_block_id)   # hypothetical

    def reachable(frm, seen):
        if frm in seen:
            return set()
        seen.add(frm)
        out = set(children.get(frm, [])) | set(ref_out.get(frm, []))
        acc = set(out)
        for n in out:
            acc |= reachable(n, seen)
        return acc

    return host_block_id in reachable(ref_block_id, set())


def add_ref(rev_id, host_block_id, ref_block_id, qty, user):
    if would_create_cycle(rev_id, host_block_id, ref_block_id):
        return None, "This reference would create a circular structure"
    c = conn()
    try:
        c.execute("INSERT INTO block_refs (host_block_id, ref_block_id, qty) VALUES (?,?,?)",
                  (host_block_id, ref_block_id, qty))
        rid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        _journal(c, rev_id, user, "ref.add", {"table": "block_refs", "pk": rid})
        c.commit()
        return rid, None
    finally:
        c.close()


def update_ref(rev_id, ref_id, qty, user):
    c = conn()
    try:
        before = _row(c, "SELECT * FROM block_refs WHERE id=?", (ref_id,))
        if not before:
            return
        c.execute("UPDATE block_refs SET qty=? WHERE id=?", (qty, ref_id))
        _journal(c, rev_id, user, "ref.update",
                 {"table": "block_refs", "pk": ref_id,
                  "before": {"qty": before["qty"]}, "after": {"qty": qty}})
        c.commit()
    finally:
        c.close()


def delete_ref(rev_id, ref_id, user):
    c = conn()
    try:
        before = _row(c, "SELECT * FROM block_refs WHERE id=?", (ref_id,))
        if not before:
            return
        c.execute("DELETE FROM block_refs WHERE id=?", (ref_id,))
        _journal(c, rev_id, user, "ref.delete", {"table": "block_refs", "row": before})
        c.commit()
    finally:
        c.close()


# ========================================================================== #
# Undo
# ========================================================================== #
def undo_last(rev_id, user):
    """Revert the most recent not-yet-undone journal entry. Returns a short
    human description of what was undone, or None if nothing to undo."""
    c = conn()
    try:
        e = _row(c, "SELECT * FROM edit_journal WHERE revision_id=? AND undone=0 "
                    "AND action <> 'undo' ORDER BY seq DESC LIMIT 1", (rev_id,))
        if not e:
            return None
        d = json.loads(e["delta_json"])
        act = e["action"]
        if act in ("line.add", "ref.add", "block.add", "snapshot.add"):
            c.execute(f"DELETE FROM {d['table']} WHERE id=?", (d["pk"],))
        elif act in ("line.update", "ref.update", "block.update", "snapshot.refresh"):
            sets = ", ".join(f"{k}=?" for k in d["before"])
            c.execute(f"UPDATE {d['table']} SET {sets} WHERE id=?",
                      list(d["before"].values()) + [d["pk"]])
        elif act in ("line.delete", "ref.delete"):
            row = d["row"]
            cols = [k for k in row if k != "id"]
            c.execute(f"INSERT INTO {('block_lines' if act == 'line.delete' else 'block_refs')} "
                      f"(id, {', '.join(cols)}) VALUES (?,{','.join('?' * len(cols))})",
                      [row["id"]] + [row[k] for k in cols])
        elif act == "block.delete":
            _restore_subtree(c, d["subtree"], rev_id, d["parent_id"], keep_ids=True)
            for rf in d["incoming_refs"]:
                c.execute("INSERT INTO block_refs (id, host_block_id, ref_block_id, qty, sort_order) "
                          "VALUES (?,?,?,?,?)", (rf["id"], rf["host_block_id"], rf["ref_block_id"],
                                                 rf["qty"], rf["sort_order"]))
        c.execute("UPDATE edit_journal SET undone=1 WHERE seq=?", (e["seq"],))
        _journal(c, rev_id, user, "undo", {"of_seq": e["seq"], "of_action": act})
        c.commit()
        return act
    finally:
        c.close()


# ========================================================================== #
# Locks (one estimator per Q number)
# ========================================================================== #
def lock_status(qnumber):
    c = conn()
    try:
        r = _row(c, "SELECT * FROM locks WHERE qnumber=?", (qnumber,))
        if not r:
            return None
        hb = datetime.datetime.fromisoformat(r["heartbeat_at"])
        r["stale"] = (datetime.datetime.utcnow() - hb).total_seconds() > LOCK_STALE_MIN * 60
        return r
    finally:
        c.close()


def acquire_lock(qnumber, user):
    """Returns (True, None) when this user holds the lock, else (False, holder)."""
    st = lock_status(qnumber)
    c = conn()
    try:
        if st and not st["stale"] and st["user"] != user:
            return False, st["user"]
        c.execute("INSERT INTO locks (qnumber, user) VALUES (?,?) "
                  "ON CONFLICT(qnumber) DO UPDATE SET user=excluded.user, "
                  "acquired_at=datetime('now'), heartbeat_at=datetime('now')",
                  (qnumber, user))
        c.commit()
        return True, None
    finally:
        c.close()


def heartbeat_lock(qnumber, user):
    c = conn()
    try:
        c.execute("UPDATE locks SET heartbeat_at=datetime('now') WHERE qnumber=? AND user=?",
                  (qnumber, user))
        c.commit()
    finally:
        c.close()


def release_lock(qnumber, user):
    c = conn()
    try:
        c.execute("DELETE FROM locks WHERE qnumber=? AND user=?", (qnumber, user))
        c.commit()
    finally:
        c.close()
