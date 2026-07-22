"""
DCN Calculation Module - .qcalc file export/import + backup.

A .qcalc file is a self-contained JSON serialization of ONE revision:
calc metadata, revision metadata, the full embedded rate snapshot (fx,
markups, items) and the complete block tree. Because the snapshot travels
with the file, an imported calc prices identically regardless of what the
library has done since - the snapshot principle, on disk.

FORMAT_VERSION guards forward compatibility: import refuses newer files
with a clear message instead of silently mis-reading them.

Backup = a ZIP holding one .qcalc per revision of every calc, plus a
manifest. The raw calc.db copy (the second backup layer) is handled by the
admin page directly.
"""
import io
import json
import zipfile
import datetime

from app.calcmod import repo
from app.calcmod.db import conn

FORMAT_VERSION = 1


def export_revision(qnumber, rev_no=None):
    """Serialize one revision to a .qcalc dict (caller json.dumps it)."""
    calc = repo.get_calc(qnumber)
    rev = repo.get_revision(qnumber, rev_no)
    if not calc or not rev:
        raise ValueError(f"{qnumber} rev {rev_no} not found")
    tree = repo.get_tree(rev["id"])
    snap = repo.load_snapshot(rev["id"])
    return {
        "format": "qcalc", "format_version": FORMAT_VERSION,
        "exported_at": datetime.datetime.utcnow().isoformat(timespec="seconds"),
        "calc": {k: calc[k] for k in ("qnumber", "title", "client", "division",
                                      "region", "created_by", "created_at")},
        "revision": {k: rev[k] for k in ("rev_no", "status", "remark",
                                         "rate_set_label", "created_by", "created_at",
                                         "issued_by", "issued_at")},
        "snapshot": {
            "fx": snap["fx"],
            "markups": {k: v for k, v in (snap["markups"] or {}).items()
                        if k not in ("id", "revision_id")},
            "items": [{k: v for k, v in s.items() if k not in ("id", "revision_id")}
                      | {"_old_id": sid} for sid, s in snap["items"].items()],
        },
        "blocks": tree["blocks"], "lines": tree["lines"], "refs": tree["refs"],
    }


def export_filename(qnumber, rev_no):
    return f"{qnumber}_rev{rev_no}.qcalc"


def import_qcalc(data, user, as_new_qnumber=None):
    """Import a .qcalc dict.

    - as_new_qnumber given  -> becomes rev 0 of that (new) Q number.
    - otherwise             -> if the file's Q exists: next revision of it;
                               if not: created under its own Q number, rev 0.
    Embedded rates are kept verbatim (imported = still priced as exported).
    Returns (qnumber, rev_no).
    """
    if data.get("format") != "qcalc":
        raise ValueError("Not a .qcalc file")
    if int(data.get("format_version", 0)) > FORMAT_VERSION:
        raise ValueError("File was made by a newer portal version - update the portal first")

    src_calc, src_rev = data["calc"], data["revision"]
    target_q = as_new_qnumber or src_calc["qnumber"]
    existing = repo.get_calc(target_q)

    c = conn()
    try:
        if existing and not as_new_qnumber:
            latest = repo.get_revision(target_q)
            rev_no = latest["rev_no"] + 1
        elif existing:
            raise ValueError(f"{target_q} already exists - import as a new revision instead")
        else:
            c.execute("INSERT INTO calculations (qnumber, title, client, division, region, "
                      "created_by) VALUES (?,?,?,?,?,?)",
                      (target_q, src_calc["title"], src_calc.get("client"),
                       src_calc["division"], src_calc["region"], user))
            rev_no = 0
        remark = (f"Imported from file ({src_calc['qnumber']} rev {src_rev['rev_no']})"
                  + (f" - {src_rev['remark']}" if src_rev.get("remark") else ""))
        c.execute("INSERT INTO revisions (qnumber, rev_no, created_by, remark, rate_set_label) "
                  "VALUES (?,?,?,?,?)",
                  (target_q, rev_no, user, remark, src_rev.get("rate_set_label")))
        rev_id = c.execute("SELECT id FROM revisions WHERE qnumber=? AND rev_no=?",
                           (target_q, rev_no)).fetchone()["id"]

        for cur, r in (data["snapshot"]["fx"] or {}).items():
            c.execute("INSERT INTO snap_fx (revision_id, currency, rate_to_usd) VALUES (?,?,?)",
                      (rev_id, cur, r))
        mk = data["snapshot"]["markups"] or {}
        c.execute("INSERT INTO snap_markups (revision_id, levy_local_pct, levy_expat_pct, "
                  "profit_pct, risk_pct, overhead_pct, margin_pct) VALUES (?,?,?,?,?,?,?)",
                  (rev_id, mk.get("levy_local_pct", 0), mk.get("levy_expat_pct", 0),
                   mk.get("profit_pct", 0), mk.get("risk_pct", 0),
                   mk.get("overhead_pct", 0), mk.get("margin_pct", 0)))
        snap_map = {}
        for s in data["snapshot"]["items"]:
            c.execute("INSERT INTO snap_items (revision_id, lib, item_uuid, erp_no, code, "
                      "description, unit, ownership, currency, rate, office_rate, yard_rate, "
                      "offshore_rate, rate_set_label, imported_from) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (rev_id, s["lib"], s["item_uuid"], s.get("erp_no"), s["code"],
                       s["description"], s.get("unit"), s.get("ownership"), s["currency"],
                       s.get("rate"), s.get("office_rate"), s.get("yard_rate"),
                       s.get("offshore_rate"), s.get("rate_set_label"),
                       s.get("imported_from") or src_calc["qnumber"]))
            snap_map[s["_old_id"]] = c.execute("SELECT last_insert_rowid()").fetchone()[0]

        block_map = {}
        for b in data["blocks"]:
            c.execute("INSERT INTO blocks (revision_id, parent_id, kind, name, unit_label, "
                      "sort_order, start_date, end_date, notes) VALUES (?,?,?,?,?,?,?,?,?)",
                      (rev_id, None, b["kind"], b["name"], b["unit_label"], b["sort_order"],
                       b.get("start_date"), b.get("end_date"), b.get("notes")))
            block_map[b["id"]] = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        for b in data["blocks"]:
            if b.get("parent_id"):
                c.execute("UPDATE blocks SET parent_id=? WHERE id=?",
                          (block_map[b["parent_id"]], block_map[b["id"]]))
        for ln in data["lines"]:
            c.execute("INSERT INTO block_lines (block_id, element, snap_item_id, description, "
                      "qty, duration, rate_basis, unit_rate_override, origin, sort_order) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (block_map[ln["block_id"]], ln["element"],
                       snap_map.get(ln.get("snap_item_id")), ln.get("description"),
                       ln["qty"], ln["duration"], ln["rate_basis"],
                       ln.get("unit_rate_override"), ln["origin"], ln["sort_order"]))
        for rf in data["refs"]:
            c.execute("INSERT INTO block_refs (host_block_id, ref_block_id, qty, sort_order) "
                      "VALUES (?,?,?,?)", (block_map[rf["host_block_id"]],
                                           block_map[rf["ref_block_id"]],
                                           rf["qty"], rf["sort_order"]))
        c.commit()
        return target_q, rev_no
    finally:
        c.close()


def backup_zip_bytes():
    """All revisions of all calcs as .qcalc files in one ZIP (in memory)."""
    buf = io.BytesIO()
    manifest = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for cal in repo.list_calcs(["CIV", "OFF", "HYD"], include_archived=True):
            for rev in repo.get_revisions(cal["qnumber"]):
                name = export_filename(cal["qnumber"], rev["rev_no"])
                z.writestr(name, json.dumps(
                    export_revision(cal["qnumber"], rev["rev_no"]), indent=1))
                manifest.append({"file": name, "qnumber": cal["qnumber"],
                                 "rev": rev["rev_no"], "status": rev["status"],
                                 "title": cal["title"]})
        z.writestr("manifest.json", json.dumps(
            {"created_at": datetime.datetime.utcnow().isoformat(timespec="seconds"),
             "revisions": manifest}, indent=1))
    return buf.getvalue()
