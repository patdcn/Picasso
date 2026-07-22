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
# Grants
# ========================================================================== #
def get_grant(user_email, division):
    """Effective level for a user in a division: 'edit', 'read' or None.
    A '*' division grant applies to all divisions. Portal admins are resolved
    by the caller (pages pass is_admin through)."""
    c = conn()
    try:
        r = _row(c, "SELECT level, lib_admin FROM calc_grants WHERE user=? AND division IN (?, '*') "
                    "ORDER BY CASE division WHEN ? THEN 0 ELSE 1 END LIMIT 1",
                 (user_email, division, division))
        return r
    finally:
        c.close()


def visible_divisions(user_email, is_admin=False):
    if is_admin:
        return ["CIV", "OFF", "HYD"]
    c = conn()
    try:
        rows = _rows(c, "SELECT division FROM calc_grants WHERE user=?", (user_email,))
        divs = {r["division"] for r in rows}
        return ["CIV", "OFF", "HYD"] if "*" in divs else sorted(divs)
    finally:
        c.close()


def is_lib_admin(user_email, is_admin=False):
    if is_admin:
        return True
    c = conn()
    try:
        r = c.execute("SELECT 1 FROM calc_grants WHERE user=? AND lib_admin=1 LIMIT 1",
                      (user_email,)).fetchone()
        return bool(r)
    finally:
        c.close()


def list_grants():
    c = conn()
    try:
        return _rows(c, "SELECT * FROM calc_grants ORDER BY user, division")
    finally:
        c.close()


def set_grant(user_email, division, level, lib_admin=False):
    c = conn()
    try:
        c.execute("INSERT INTO calc_grants (user, division, level, lib_admin) VALUES (?,?,?,?) "
                  "ON CONFLICT(user, division) DO UPDATE SET level=excluded.level, "
                  "lib_admin=excluded.lib_admin",
                  (user_email, division, level, 1 if lib_admin else 0))
        c.commit()
    finally:
        c.close()


def delete_grant(user_email, division):
    c = conn()
    try:
        c.execute("DELETE FROM calc_grants WHERE user=? AND division=?", (user_email, division))
        c.commit()
    finally:
        c.close()


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
            c.execute("INSERT INTO equipment_rates (item_uuid, rate_set_id, region, currency, rate) "
                      "SELECT item_uuid, ?, region, currency, rate FROM equipment_rates WHERE rate_set_id=?",
                      (new_id, copy_from_id))
            c.execute("INSERT INTO personnel_rates (item_uuid, rate_set_id, region, currency, "
                      "office_rate, yard_rate, offshore_rate) "
                      "SELECT item_uuid, ?, region, currency, office_rate, yard_rate, offshore_rate "
                      "FROM personnel_rates WHERE rate_set_id=?", (new_id, copy_from_id))
            c.execute("INSERT INTO misc_rates (item_uuid, rate_set_id, region, currency, rate) "
                      "SELECT item_uuid, ?, region, currency, rate FROM misc_rates WHERE rate_set_id=?",
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


def list_currencies():
    c = conn()
    try:
        return _rows(c, "SELECT * FROM currencies ORDER BY code")
    finally:
        c.close()


def list_items(lib, division=None, active_only=True, with_rates_for=None):
    """Library items, optionally joined with rates for (rate_set_id, region)."""
    it, rt = _ITEM_TABLES[lib]
    c = conn()
    try:
        where, args = [], []
        if division:
            where.append("i.division=?"); args.append(division)
        if active_only:
            where.append("i.active=1")
        w = ("WHERE " + " AND ".join(where)) if where else ""
        if with_rates_for:
            rs, region = with_rates_for
            items = _rows(c, f"SELECT i.* FROM {it} i {w} ORDER BY i.code", args)
            rate_fields = (("office_rate", "yard_rate", "offshore_rate")
                           if lib == "personnel" else ("rate",))
            for i in items:
                r = _rate_for(c, lib, i["uuid"], rs, region) or {}
                i["currency"] = r.get("currency")
                i["rate_region"] = r.get("region")     # 'ALL' marks the fallback
                for f in rate_fields:
                    i[f] = r.get(f)
            return items
        return _rows(c, f"SELECT i.* FROM {it} i {w} ORDER BY i.code", args)
    finally:
        c.close()


def find_item_by_code(lib, code=None, erp_no=None):
    """Existing item with this code or ERP number (any division), or None.
    Used to catch duplicates at check-in submission, before they reach the
    moderation queue - the DB UNIQUE constraints remain the hard backstop."""
    it, _ = _ITEM_TABLES[lib]
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


CODE_PREFIX = {"personnel": "P", "equipment": "E", "misc": "M"}
DIV_LETTER = {"CIV": "C", "OFF": "O", "HYD": "H"}
OWN_LETTER = {"internal": "I", "external": "E"}


def suggest_code(lib, division, ownership="internal", counterpart_uuid=None):
    """Suggest the next code.

    Format: P-O-I-0001 = library (P/E/M) - division (C/O/H) - ownership (I/E)
    - concept number. Misc has no ownership segment: M-O-0001. Region is NOT
    part of the code: one item carries rates per region (incl. ALL), so the
    same Diver stays one entry per division/ownership.

    The 4-digit number identifies the CONCEPT across divisions and ownership
    variants (Diver = 0012 in OFF, CIV and HYD, internal or agency alike):
    with a counterpart chosen its number is reused; otherwise the next free
    number across the whole library is allocated."""
    it, _ = _ITEM_TABLES[lib]
    seg = [CODE_PREFIX[lib], DIV_LETTER.get(division, division)]
    if lib != "misc":
        seg.append(OWN_LETTER.get(ownership or "internal", "I"))
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


def counterpart_options(lib, division):
    """Items of the same library in OTHER divisions - candidates for
    'same concept, new division' number reuse."""
    it, _ = _ITEM_TABLES[lib]
    c = conn()
    try:
        rows = _rows(c, f"SELECT uuid, code, division, "
                        f"{'function' if lib == 'personnel' else 'description'} AS label "
                        f"FROM {it} WHERE division<>? AND active=1 ORDER BY code",
                     (division,))
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
    it, _ = _ITEM_TABLES[lib]
    u = data.get("uuid") or new_uuid()
    if lib in ("personnel", "equipment") and not data.get("ownership"):
        data = {**data, "ownership": "internal"}
    cols = {"equipment": ("erp_no", "code", "division", "description", "unit", "ownership", "notes"),
            "personnel": ("erp_no", "code", "division", "function", "ownership", "notes"),
            "misc": ("erp_no", "code", "division", "category", "description", "unit")}[lib]
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


def set_item_rate(lib, item_uuid, rate_set_id, region, currency, **kw):
    _, rt = _ITEM_TABLES[lib]
    c = conn()
    try:
        if lib == "personnel":
            c.execute(f"INSERT INTO {rt} (item_uuid, rate_set_id, region, currency, "
                      "office_rate, yard_rate, offshore_rate) VALUES (?,?,?,?,?,?,?) "
                      "ON CONFLICT(item_uuid, rate_set_id, region) DO UPDATE SET "
                      "currency=excluded.currency, office_rate=excluded.office_rate, "
                      "yard_rate=excluded.yard_rate, offshore_rate=excluded.offshore_rate",
                      (item_uuid, rate_set_id, region, currency,
                       kw.get("office_rate"), kw.get("yard_rate"), kw.get("offshore_rate")))
        else:
            c.execute(f"INSERT INTO {rt} (item_uuid, rate_set_id, region, currency, rate) "
                      "VALUES (?,?,?,?,?) "
                      "ON CONFLICT(item_uuid, rate_set_id, region) DO UPDATE SET "
                      "currency=excluded.currency, rate=excluded.rate",
                      (item_uuid, rate_set_id, region, currency, kw.get("rate")))
        c.commit()
    finally:
        c.close()


def _rate_for(c, lib, item_uuid, rate_set_id, region):
    """Rate row for an item: exact region first, else the ALL region."""
    _, rt = _ITEM_TABLES[lib]
    r = _row(c, f"SELECT * FROM {rt} WHERE item_uuid=? AND rate_set_id=? AND region=?",
             (item_uuid, rate_set_id, region))
    if r:
        return r
    return _row(c, f"SELECT * FROM {rt} WHERE item_uuid=? AND rate_set_id=? "
                   "AND region='ALL'", (item_uuid, rate_set_id))


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
    if kind in ("equipment_item", "personnel_item", "misc_item"):
        lib = kind.split("_")[0]
        item = dict(payload.get("item") or {})
        item["division"] = division
        u = upsert_item(lib, item)
        rs = (active_rate_set() or {}).get("id")
        rate_keys = ("rate", "office_rate", "yard_rate", "offshore_rate")
        for rr in payload.get("rates") or []:
            set_item_rate(lib, u, rr.get("rate_set_id") or rs, rr["region"],
                          rr.get("currency", "USD"),
                          **{k: rr.get(k) for k in rate_keys})
    elif kind == "rate_change":
        lib = payload["lib"]
        rate_keys = ("rate", "office_rate", "yard_rate", "offshore_rate")
        for rr in payload.get("rates") or []:
            set_item_rate(lib, payload["item_uuid"],
                          rr.get("rate_set_id") or (active_rate_set() or {}).get("id"),
                          rr["region"], rr.get("currency", "USD"),
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


def snapshot_item(rev_id, lib, item_uuid, region, user):
    """Embed one library item's CURRENT active-set rate into the revision.
    If already embedded, returns the existing snap id (a calc never re-reads
    the library implicitly)."""
    c = conn()
    try:
        ex = c.execute("SELECT id FROM snap_items WHERE revision_id=? AND item_uuid=?",
                       (rev_id, item_uuid)).fetchone()
        if ex:
            return ex["id"]
        rs = active_rate_set()
        it_t, rt_t = _ITEM_TABLES[lib]
        i = _row(c, f"SELECT * FROM {it_t} WHERE uuid=?", (item_uuid,))
        r = _rate_for(c, lib, item_uuid, rs["id"] if rs else -1, region) or {}
        c.execute("INSERT INTO snap_items (revision_id, lib, item_uuid, erp_no, code, description, "
                  "unit, ownership, currency, rate, office_rate, yard_rate, offshore_rate, "
                  "rate_set_label) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (rev_id, lib, item_uuid, i.get("erp_no"), i["code"],
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


def diff_snapshot(rev_id, region):
    """Compare embedded rates against the current ACTIVE rate set.
    Returns [{snap_id, code, description, field, old, new, currency}]."""
    rs = active_rate_set()
    if not rs:
        return []
    out = []
    c = conn()
    try:
        for s in c.execute("SELECT * FROM snap_items WHERE revision_id=?", (rev_id,)).fetchall():
            cur = _rate_for(c, s["lib"], s["item_uuid"], rs["id"], region)
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


def refresh_snapshot(rev_id, region, snap_ids, user):
    """Explicitly update selected embedded items to the current active set.
    Journaled per item so it is undoable."""
    rs = active_rate_set()
    c = conn()
    try:
        for sid in snap_ids:
            s = _row(c, "SELECT * FROM snap_items WHERE id=? AND revision_id=?", (sid, rev_id))
            if not s:
                continue
            cur = _rate_for(c, s["lib"], s["item_uuid"], rs["id"], region)
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
