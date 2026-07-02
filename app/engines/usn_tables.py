"""
US Navy decompression tables - presentation reader.

Reads a finalized JSON from the /data volume (USN_TABLES_JSON, default
/data/tools/usn/usn_tables.json), cached on file mtime. The table data is not
bundled in the repo; stage the JSON on the volume via Admin -> Data volume.

Structure:
    {"meta": {...}, "tables": [ {code, kind, title, rules, columns, rows, ...} ]}
Each table is a simple column/row grid; a table may set "group_from" (+ optional
"group_label") to render a spanning header over the columns from that index on
(used by the no-decompression table's repetitive-group block).
"""
import json
import os

TABLES_JSON = os.getenv("USN_TABLES_JSON", "/data/tools/usn/usn_tables.json")
_CACHE = {"mtime": None, "data": None}


def load_tables(path=None):
    path = path or TABLES_JSON
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _CACHE.update(mtime=None, data=None)
        return None
    if _CACHE["mtime"] != mtime:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                _CACHE.update(mtime=mtime, data=json.load(fh))
        except (OSError, ValueError):
            return None
    return _CACHE["data"]


def ui_tables(path=None):
    data = load_tables(path)
    if not data:
        return []
    return [{"code": t["code"], "label": t.get("title", t["code"])} for t in data["tables"]]


def ui_table(code, path=None):
    data = load_tables(path)
    if not data:
        return None
    for t in data["tables"]:
        if t["code"] == code:
            return t
    return None
