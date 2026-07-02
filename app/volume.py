"""
Safe write access to the persistent /data volume, used by the Admin page's
"Data volume files" card (upload a file, create a folder).

Every path is resolved and confined to DATA_ROOT (default /data) so a caller can
never write outside the volume via absolute paths, "..", or symlinks. The Admin
callbacks additionally require an admin session before calling in here.
"""
import base64
import json
import os

DATA_ROOT = os.path.realpath(os.getenv("DATA_ROOT", "/data"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(30 * 1024 * 1024)))  # 30 MB


class VolumeError(ValueError):
    """Raised for an unsafe path or a rejected upload."""


def _resolve(rel_or_abs, default_name=None):
    """Resolve a user-supplied path to an absolute path guaranteed to sit inside
    DATA_ROOT. A trailing '/' (or an existing directory) means 'use default_name
    inside this folder'. Raises VolumeError on anything outside the volume."""
    raw = (rel_or_abs or "").strip()
    if not raw:
        raise VolumeError("Give a destination path.")
    raw = raw.replace("\\", "/")

    # Accept either an absolute path under /data, or a path relative to /data.
    if raw.startswith(DATA_ROOT):
        candidate = raw
    elif raw.startswith("/"):
        # absolute but not under DATA_ROOT -> treat the leading slash as data-relative
        candidate = os.path.join(DATA_ROOT, raw.lstrip("/"))
    else:
        candidate = os.path.join(DATA_ROOT, raw)

    wants_dir = raw.endswith("/") or os.path.isdir(candidate)
    if wants_dir:
        if not default_name:
            # this is a directory target on its own (make_dir)
            full = os.path.realpath(candidate)
        else:
            full = os.path.realpath(os.path.join(candidate, default_name))
    else:
        full = os.path.realpath(candidate)

    root = DATA_ROOT + os.sep
    if full != DATA_ROOT and not full.startswith(root):
        raise VolumeError("Path must be inside the data volume.")
    if full == DATA_ROOT and default_name is None:
        # allowed: making/refering to the root itself is a no-op for mkdir
        pass
    return full


def _decode_upload(contents):
    """dcc.Upload contents look like 'data:<mime>;base64,<payload>'. Return bytes."""
    if not contents or "," not in contents:
        raise VolumeError("No file received.")
    _header, payload = contents.split(",", 1)
    try:
        data = base64.b64decode(payload)
    except Exception:
        raise VolumeError("Could not decode the uploaded file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise VolumeError(f"File too large (limit {MAX_UPLOAD_BYTES // (1024*1024)} MB).")
    return data


def _rel(full):
    """Path shown to the user, relative to the volume root (e.g. tools/dcd/x.json)."""
    try:
        return os.path.relpath(full, DATA_ROOT)
    except ValueError:
        return full


def save_upload(contents, filename, target):
    """Write an uploaded file to `target` under /data, creating folders as needed.

    Returns (ok, message). `target` may be a full file path (…/x.json) or a folder
    (ends with '/', or an existing dir) in which case the uploaded filename is used.
    .json uploads are validated as parseable JSON before anything is written.
    """
    try:
        data = _decode_upload(contents)
        full = _resolve(target, default_name=(filename or "upload.bin"))
        name = os.path.basename(full)
        if name.lower().endswith(".json"):
            try:
                json.loads(data.decode("utf-8"))
            except Exception as e:
                raise VolumeError(f"Not valid JSON: {e}")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        tmp = full + ".part"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, full)  # atomic swap so readers never see a half file
    except VolumeError as e:
        return False, str(e)
    except OSError as e:
        return False, f"Write failed: {e}"
    kb = max(1, len(data) // 1024)
    return True, f"Saved {_rel(full)}  ({kb:,} KB)."


def make_dir(target):
    """Create a folder (and any parents) under /data. Returns (ok, message)."""
    try:
        full = _resolve(target, default_name=None)
        if full == DATA_ROOT:
            raise VolumeError("Give a folder name under the data volume.")
        os.makedirs(full, exist_ok=True)
    except VolumeError as e:
        return False, str(e)
    except OSError as e:
        return False, f"Could not create folder: {e}"
    return True, f"Folder ready: {_rel(full)}/"


def listing(target):
    """Return (rel_dir, [entries]) for a folder under /data, for a quick preview.
    Directories are suffixed with '/'. Returns (rel_dir, None) if it doesn't exist."""
    try:
        full = _resolve((target or "").rstrip("/") + "/", default_name=None)
    except VolumeError:
        return "", None
    if not os.path.isdir(full):
        return _rel(full), None
    out = []
    for name in sorted(os.listdir(full)):
        p = os.path.join(full, name)
        out.append(name + ("/" if os.path.isdir(p) else ""))
    return _rel(full), out


# --------------------------------------------------------------------------- #
# Explorer operations (browse / move / rename / delete). All confined to /data.
# --------------------------------------------------------------------------- #
import shutil
import datetime


def _entry(full):
    try:
        st = os.stat(full)
        is_dir = os.path.isdir(full)
        mtime = datetime.datetime.utcfromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
        size = 0 if is_dir else st.st_size
    except OSError:
        is_dir, mtime, size = False, "", 0
    return {"name": os.path.basename(full), "is_dir": is_dir, "size": size,
            "mtime": mtime, "rel": _rel(full)}


def _resolve_dir(rel):
    """Resolve a directory path (rel to /data). Empty -> the volume root."""
    rel = (rel or "").strip().strip("/")
    if not rel:
        return DATA_ROOT
    return _resolve(rel + "/", default_name=None)


def list_dir(rel=""):
    """(rel_dir, [entries]) for a folder under /data; folders first, then files.
    Missing/!dir -> (rel_dir, None)."""
    try:
        base = _resolve_dir(rel)
    except VolumeError:
        return "", None
    if not os.path.isdir(base):
        return _rel(base), None
    names = os.listdir(base)
    names.sort(key=lambda n: (not os.path.isdir(os.path.join(base, n)), n.lower()))
    return _rel(base), [_entry(os.path.join(base, n)) for n in names]


def list_all_dirs():
    """Every folder under /data as relative paths (for a 'move to' picker)."""
    out = [""]
    for dirpath, dirs, _files in os.walk(DATA_ROOT):
        dirs.sort()
        for d in dirs:
            out.append(_rel(os.path.join(dirpath, d)))
    seen, uniq = set(), []
    for r in out:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq


def delete(rel):
    """Delete a file or folder (recursively) under /data. Never the root."""
    try:
        full = _resolve(rel, default_name=None)
        if full == DATA_ROOT:
            raise VolumeError("Refusing to delete the volume root.")
        if not os.path.exists(full):
            raise VolumeError("Not found.")
        if os.path.isdir(full):
            shutil.rmtree(full)
        else:
            os.remove(full)
    except VolumeError as e:
        return False, str(e)
    except OSError as e:
        return False, f"Delete failed: {e}"
    return True, f"Deleted {_rel(full)}."


def move(src_rel, dst_dir_rel):
    """Move a file/folder into another folder under /data."""
    try:
        src = _resolve(src_rel, default_name=None)
        if src == DATA_ROOT:
            raise VolumeError("Cannot move the volume root.")
        if not os.path.exists(src):
            raise VolumeError("Source not found.")
        dst_dir = _resolve_dir(dst_dir_rel)
        os.makedirs(dst_dir, exist_ok=True)
        dest = os.path.realpath(os.path.join(dst_dir, os.path.basename(src)))
        root = DATA_ROOT + os.sep
        if dest != DATA_ROOT and not dest.startswith(root):
            raise VolumeError("Destination outside the data volume.")
        if dest == src:
            return True, "Already there."
        if os.path.isdir(src) and dest.startswith(src + os.sep):
            raise VolumeError("Cannot move a folder into itself.")
        if os.path.exists(dest):
            raise VolumeError(f"'{os.path.basename(src)}' already exists in the destination.")
        shutil.move(src, dest)
    except VolumeError as e:
        return False, str(e)
    except OSError as e:
        return False, f"Move failed: {e}"
    return True, f"Moved to {_rel(dst_dir)}/."


def rename(rel, new_name):
    """Rename a file/folder in place (new_name is a bare name, no path parts)."""
    new_name = (new_name or "").strip()
    if not new_name or "/" in new_name or "\\" in new_name or ".." in new_name:
        return False, "Enter a valid name (no slashes)."
    try:
        src = _resolve(rel, default_name=None)
        if src == DATA_ROOT:
            raise VolumeError("Cannot rename the volume root.")
        dst = os.path.realpath(os.path.join(os.path.dirname(src), new_name))
        root = DATA_ROOT + os.sep
        if not dst.startswith(root):
            raise VolumeError("Name resolves outside the data volume.")
        if os.path.exists(dst):
            raise VolumeError("A file with that name already exists.")
        os.rename(src, dst)
    except VolumeError as e:
        return False, str(e)
    except OSError as e:
        return False, f"Rename failed: {e}"
    return True, f"Renamed to {new_name}."
