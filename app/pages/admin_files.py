"""
Admin - Data volume explorer (admins only; page guarded by /admin, writes guarded
inside every callback).

A file manager for the persistent /data volume: browse folders, drag-and-drop
files in to upload, create folders, and select files/folders to move, rename or
delete. Everything is confined to /data by app/volume.py.
"""
import os
import io
import time
import zipfile
import sqlite3
import tempfile
import dash
from dash import html, dcc, dash_table, Input, Output, State, callback, no_update, ALL
from dash.exceptions import PreventUpdate

from app import auth
from app import volume
from app.adminui import denied

dash.register_page(__name__, path="/admin/files", name="Data volume")

INK = "#1f2937"
MUTED = "#6b7280"
ACCENT = "#0f766e"
LINE = "#e5e7eb"


def _human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return (f"{int(n)} {unit}" if unit == "B" else f"{n:.1f} {unit}")
        n /= 1024


def _btn(label, id_, primary=True, danger=False):
    if danger:
        bg, fg, bd = "#fff", "#b91c1c", "1px solid #fecaca"
    elif primary:
        bg, fg, bd = ACCENT, "#fff", "none"
    else:
        bg, fg, bd = "#fff", INK, f"1px solid {LINE}"
    return html.Button(label, id=id_, n_clicks=0, style={
        "padding": "7px 13px", "borderRadius": "8px", "border": bd, "background": bg,
        "color": fg, "fontWeight": 600, "cursor": "pointer", "fontSize": "0.82rem"})


def _input(id_, ph, width="180px"):
    return dcc.Input(id=id_, type="text", placeholder=ph, debounce=False, style={
        "padding": "7px 10px", "borderRadius": "8px", "border": f"1px solid #d1d5db",
        "width": width, "fontSize": "0.82rem"})


def layout():
    if not _is_admin():
        return denied()
    return html.Div([
        html.H3("Data volume"),
        html.P(["Browse and manage the persistent ", html.Code("/data"),
                " volume. Drag files onto the drop zone to upload into the current folder. "
                "Select rows to move, rename or delete. Everything is confined to ",
                html.Code("/data"), "."],
               style={"color": MUTED, "maxWidth": "720px"}),
        dcc.Link("\u2190 Back to Admin", href="/admin",
                 style={"color": ACCENT, "fontWeight": 600, "fontSize": "0.85rem"}),

        html.Div([
            _btn("\u2b07  Download full backup (.zip)", "fx-backup", primary=True),
            html.Span(id="fx-backup-status",
                      style={"fontSize": "0.82rem", "color": MUTED, "marginLeft": "10px"}),
            html.Div("Downloads a single zip of the entire /data volume \u2014 all "
                     "reference files plus the databases (snapshotted consistently) "
                     "\u2014 with folder paths preserved. Store the file somewhere safe; "
                     "to restore, unzip it back into /data.",
                     style={"fontSize": "0.76rem", "color": MUTED, "marginTop": "6px",
                            "maxWidth": "720px"}),
        ], style={"margin": "14px 0 4px", "padding": "12px 14px",
                  "background": "#f8fafc", "border": f"1px solid {LINE}",
                  "borderRadius": "10px"}),
        dcc.Download(id="fx-backup-dl"),

        dcc.Store(id="fx-cwd", data=""),
        dcc.Store(id="fx-refresh", data=0),
        dcc.ConfirmDialog(id="fx-confirm-del"),

        html.Div(id="fx-crumbs", style={"margin": "14px 0 8px", "fontSize": "0.9rem"}),

        dcc.Upload(
            id="fx-upload", multiple=True,
            children=html.Div("Drag files here to upload into this folder, or click to browse",
                              style={"color": MUTED, "fontSize": "0.85rem"}),
            style={"border": "1.5px dashed #cbd5e1", "borderRadius": "10px",
                   "padding": "16px", "textAlign": "center", "background": "#f8fafc",
                   "cursor": "pointer", "marginBottom": "10px"}),

        html.Div([
            _input("fx-newdir", "new folder name", "160px"),
            _btn("Create folder", "fx-mkdir", primary=False),
            html.Span(style={"width": "10px", "display": "inline-block"}),
            _input("fx-rename", "rename selected to\u2026", "170px"),
            _btn("Rename", "fx-rename-btn", primary=False),
        ], style={"display": "flex", "gap": "6px", "alignItems": "center",
                  "flexWrap": "wrap", "marginBottom": "8px"}),

        html.Div([
            html.Span("Move selected to:", style={"fontSize": "0.82rem", "color": INK,
                                                  "fontWeight": 600}),
            dcc.Dropdown(id="fx-movedst", options=[], placeholder="destination folder",
                         style={"width": "260px", "fontSize": "0.82rem"}),
            _btn("Move", "fx-move", primary=False),
            html.Span(style={"flex": "1 1 auto"}),
            _btn("Delete selected", "fx-delete", danger=True),
        ], style={"display": "flex", "gap": "8px", "alignItems": "center",
                  "flexWrap": "wrap", "marginBottom": "10px"}),

        dash_table.DataTable(
            id="fx-table",
            columns=[
                {"name": "Name", "id": "disp"},
                {"name": "Type", "id": "kind"},
                {"name": "Size", "id": "sizeh"},
                {"name": "Modified (UTC)", "id": "mtime"},
            ],
            data=[],
            row_selectable="multi",
            selected_rows=[],
            page_size=100,
            style_as_list_view=True,
            style_cell={"fontSize": "0.85rem", "padding": "6px 10px",
                        "fontFamily": "system-ui", "textAlign": "left",
                        "whiteSpace": "nowrap", "overflow": "hidden",
                        "textOverflow": "ellipsis", "maxWidth": "340px"},
            style_header={"fontWeight": 700, "background": "#f8fafc",
                          "borderBottom": f"1px solid {LINE}"},
            style_data_conditional=[
                {"if": {"filter_query": "{is_dir} = 1", "column_id": "disp"},
                 "color": ACCENT, "fontWeight": 600, "cursor": "pointer"},
                {"if": {"state": "active"},
                 "backgroundColor": "#e6f2f1", "border": f"1px solid {ACCENT}"},
                {"if": {"state": "selected"},
                 "backgroundColor": "#e6f2f1", "border": f"1px solid {ACCENT}"},
            ],
            cell_selectable=True,
        ),
        html.Div(id="fx-status", style={"fontSize": "0.85rem", "marginTop": "10px",
                                        "minHeight": "1.1em"}),
    ], style={"maxWidth": "820px"})


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _is_admin():
    u = auth.current_user()
    return bool(u and u.get("is_admin"))


def _sqlite_backup(src_path, dst_path):
    """Consistent online snapshot of a SQLite DB (folds in WAL), read-only source."""
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True, timeout=5.0)
    try:
        dst = sqlite3.connect(dst_path)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _make_backup_zip():
    """Zip the entire /data volume, preserving relative paths. Returns (bytes,
    n_files, notes). SQLite .db files are snapshotted consistently via the backup
    API; their -wal/-shm sidecars are skipped (the snapshot already folds them in).
    Anything that can't be read is skipped and noted rather than aborting."""
    root = volume.DATA_ROOT
    bio = io.BytesIO()
    n_files = 0
    skipped = []
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirs, filenames in os.walk(root):
            for fn in sorted(filenames):
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root)
                # SQLite sidecars: skip; the .db snapshot below captures their data
                if fn.endswith(("-wal", "-shm", "-journal")):
                    continue
                if fn.endswith(".db"):
                    tmp = None
                    try:
                        fd, tmp = tempfile.mkstemp(suffix=".db")
                        os.close(fd)
                        _sqlite_backup(full, tmp)
                        zf.write(tmp, rel)
                        n_files += 1
                    except Exception:
                        # not a valid SQLite file (or locked): fall back to raw
                        # copy, including sidecars so the state stays recoverable
                        try:
                            zf.write(full, rel)
                            n_files += 1
                            for sc in ("-wal", "-shm"):
                                if os.path.exists(full + sc):
                                    zf.write(full + sc, rel + sc)
                        except Exception:
                            skipped.append(rel)
                    finally:
                        if tmp and os.path.exists(tmp):
                            try:
                                os.remove(tmp)
                            except OSError:
                                pass
                    continue
                try:
                    zf.write(full, rel)
                    n_files += 1
                except Exception:
                    skipped.append(rel)
    return bio.getvalue(), n_files, skipped


def _rows_for(cwd):
    rel, entries = volume.list_dir(cwd)
    if entries is None:
        return rel, []
    data = []
    for e in entries:
        data.append({
            "disp": e["name"] + ("/" if e["is_dir"] else ""),
            "kind": "folder" if e["is_dir"] else "file",
            "sizeh": "" if e["is_dir"] else _human(e["size"]),
            "mtime": e["mtime"],
            "rel": e["rel"],
            "is_dir": 1 if e["is_dir"] else 0,
        })
    return rel, data


def _crumbs(cwd):
    parts = [p for p in (cwd or "").split("/") if p]
    items = [html.Button("/data", id={"type": "fx-crumb", "rel": ""}, n_clicks=0,
                         style={"border": "none", "background": "none", "color": ACCENT,
                                "fontWeight": 700, "cursor": "pointer", "padding": "0",
                                "fontSize": "0.9rem"})]
    acc = ""
    for p in parts:
        acc = (acc + "/" + p) if acc else p
        items.append(html.Span(" / ", style={"color": MUTED}))
        items.append(html.Button(p, id={"type": "fx-crumb", "rel": acc}, n_clicks=0,
                                 style={"border": "none", "background": "none", "color": ACCENT,
                                        "fontWeight": 600, "cursor": "pointer", "padding": "0",
                                        "fontSize": "0.9rem"}))
    return items


def _dst_options():
    return [{"label": ("/data" if r == "" else "/data/" + r), "value": r}
            for r in volume.list_all_dirs()]


def _selected_rels(data, selected_rows):
    return [data[i]["rel"] for i in (selected_rows or []) if 0 <= i < len(data or [])]


@callback(
    Output("fx-backup-dl", "data"),
    Output("fx-backup-status", "children"),
    Input("fx-backup", "n_clicks"),
    prevent_initial_call=True,
)
def _backup(_n):
    if not _is_admin():
        raise PreventUpdate
    try:
        data, n_files, skipped = _make_backup_zip()
    except Exception as e:  # pragma: no cover - defensive
        return no_update, html.Span(f"Backup failed: {e}", style={"color": "#b91c1c"})
    stamp = time.strftime("%Y%m%d_%H%M")
    fname = f"picasso_data_backup_{stamp}.zip"
    size_mb = len(data) / (1024 * 1024)
    note = f"{n_files} file(s), {size_mb:.1f} MB."
    if skipped:
        note += f"  ({len(skipped)} unreadable, skipped.)"
    return (dcc.send_bytes(data, fname),
            html.Span(f"Backup ready \u2014 {note}", style={"color": ACCENT}))


# --------------------------------------------------------------------------- #
# render on navigate / refresh
# --------------------------------------------------------------------------- #
@callback(
    Output("fx-table", "data"),
    Output("fx-crumbs", "children"),
    Output("fx-movedst", "options"),
    Output("fx-table", "selected_rows"),
    Output("fx-table", "active_cell"),
    Input("fx-cwd", "data"),
    Input("fx-refresh", "data"),
)
def _render(cwd, _tick):
    if not _is_admin():
        raise PreventUpdate
    _rel, data = _rows_for(cwd or "")
    return data, _crumbs(cwd or ""), _dst_options(), [], None


# navigate by clicking a folder name
@callback(
    Output("fx-cwd", "data"),
    Input("fx-table", "active_cell"),
    State("fx-table", "data"),
    prevent_initial_call=True,
)
def _open_folder(active, data):
    if not active or active.get("column_id") != "disp":
        return no_update
    row = (data or [])[active["row"]] if active["row"] < len(data or []) else None
    if not row or not row.get("is_dir"):
        return no_update
    return row["rel"]


# navigate by breadcrumb
@callback(
    Output("fx-cwd", "data", allow_duplicate=True),
    Input({"type": "fx-crumb", "rel": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _crumb_nav(_clicks):
    trig = dash.callback_context.triggered_id
    if not trig or not any(c for c in (_clicks or []) if c):
        return no_update
    return trig.get("rel", "")


# upload into current folder
@callback(
    Output("fx-refresh", "data", allow_duplicate=True),
    Output("fx-status", "children"),
    Input("fx-upload", "contents"),
    State("fx-upload", "filename"),
    State("fx-cwd", "data"),
    State("fx-refresh", "data"),
    prevent_initial_call=True,
)
def _upload(contents, filenames, cwd, tick):
    if not _is_admin():
        return no_update, html.Span("Not authorized.", style={"color": "#b91c1c"})
    if not contents:
        return no_update, no_update
    contents = contents if isinstance(contents, list) else [contents]
    filenames = filenames if isinstance(filenames, list) else [filenames]
    ok_n, msgs = 0, []
    for c, fn in zip(contents, filenames):
        target = ((cwd + "/") if cwd else "") + (fn or "upload.bin")
        ok, msg = volume.save_upload(c, fn, target)
        ok_n += 1 if ok else 0
        if not ok:
            msgs.append(f"{fn}: {msg}")
    text = f"Uploaded {ok_n} file(s)." + ("  " + " ".join(msgs) if msgs else "")
    return (tick or 0) + 1, html.Span(text, style={"color": ACCENT if not msgs else "#b45309"})


# create folder
@callback(
    Output("fx-refresh", "data", allow_duplicate=True),
    Output("fx-status", "children", allow_duplicate=True),
    Output("fx-newdir", "value"),
    Input("fx-mkdir", "n_clicks"),
    State("fx-newdir", "value"),
    State("fx-cwd", "data"),
    State("fx-refresh", "data"),
    prevent_initial_call=True,
)
def _mkdir(_n, name, cwd, tick):
    if not _is_admin():
        return no_update, html.Span("Not authorized.", style={"color": "#b91c1c"}), no_update
    if not (name or "").strip():
        return no_update, html.Span("Enter a folder name.", style={"color": "#b91c1c"}), no_update
    target = ((cwd + "/") if cwd else "") + name.strip()
    ok, msg = volume.make_dir(target)
    return ((tick or 0) + 1 if ok else no_update,
            html.Span(msg, style={"color": ACCENT if ok else "#b91c1c"}),
            "" if ok else no_update)


# move selected
@callback(
    Output("fx-refresh", "data", allow_duplicate=True),
    Output("fx-status", "children", allow_duplicate=True),
    Input("fx-move", "n_clicks"),
    State("fx-table", "data"),
    State("fx-table", "selected_rows"),
    State("fx-movedst", "value"),
    State("fx-refresh", "data"),
    prevent_initial_call=True,
)
def _move(_n, data, selected, dst, tick):
    if not _is_admin():
        return no_update, html.Span("Not authorized.", style={"color": "#b91c1c"})
    rels = _selected_rels(data, selected)
    if not rels:
        return no_update, html.Span("Select something to move.", style={"color": "#b91c1c"})
    if dst is None:
        return no_update, html.Span("Pick a destination folder.", style={"color": "#b91c1c"})
    done, errs = 0, []
    for r in rels:
        ok, msg = volume.move(r, dst)
        done += 1 if ok else 0
        if not ok:
            errs.append(msg)
    text = f"Moved {done} item(s)." + ("  " + " ".join(errs) if errs else "")
    return (tick or 0) + 1, html.Span(text, style={"color": ACCENT if not errs else "#b45309"})


# rename selected (single)
@callback(
    Output("fx-refresh", "data", allow_duplicate=True),
    Output("fx-status", "children", allow_duplicate=True),
    Output("fx-rename", "value"),
    Input("fx-rename-btn", "n_clicks"),
    State("fx-table", "data"),
    State("fx-table", "selected_rows"),
    State("fx-rename", "value"),
    State("fx-refresh", "data"),
    prevent_initial_call=True,
)
def _rename(_n, data, selected, newname, tick):
    if not _is_admin():
        return no_update, html.Span("Not authorized.", style={"color": "#b91c1c"}), no_update
    rels = _selected_rels(data, selected)
    if len(rels) != 1:
        return no_update, html.Span("Select exactly one item to rename.",
                                    style={"color": "#b91c1c"}), no_update
    ok, msg = volume.rename(rels[0], newname or "")
    return ((tick or 0) + 1 if ok else no_update,
            html.Span(msg, style={"color": ACCENT if ok else "#b91c1c"}),
            "" if ok else no_update)


# delete -> confirm dialog
@callback(
    Output("fx-confirm-del", "displayed"),
    Output("fx-confirm-del", "message"),
    Input("fx-delete", "n_clicks"),
    State("fx-table", "data"),
    State("fx-table", "selected_rows"),
    prevent_initial_call=True,
)
def _ask_delete(_n, data, selected):
    rels = _selected_rels(data, selected)
    if not rels:
        return False, ""
    names = ", ".join(os.path.basename(r) for r in rels[:6]) + (" \u2026" if len(rels) > 6 else "")
    return True, f"Delete {len(rels)} item(s)? This cannot be undone.\n\n{names}"


@callback(
    Output("fx-refresh", "data", allow_duplicate=True),
    Output("fx-status", "children", allow_duplicate=True),
    Input("fx-confirm-del", "submit_n_clicks"),
    State("fx-table", "data"),
    State("fx-table", "selected_rows"),
    State("fx-refresh", "data"),
    prevent_initial_call=True,
)
def _do_delete(_submit, data, selected, tick):
    if not _is_admin():
        return no_update, html.Span("Not authorized.", style={"color": "#b91c1c"})
    rels = _selected_rels(data, selected)
    if not rels:
        return no_update, no_update
    done, errs = 0, []
    for r in rels:
        ok, msg = volume.delete(r)
        done += 1 if ok else 0
        if not ok:
            errs.append(msg)
    text = f"Deleted {done} item(s)." + ("  " + " ".join(errs) if errs else "")
    return (tick or 0) + 1, html.Span(text, style={"color": ACCENT if not errs else "#b45309"})
