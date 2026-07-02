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
