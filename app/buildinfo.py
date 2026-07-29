"""
Build identifier for kiosk auto-reload.

BUILD_ID is the newest mtime of the app's source files. Inside a Docker
image those mtimes are frozen at build time, so the value is identical
across Gunicorn workers and restarts of the same image, and changes on
every deploy. Long-running kiosk tabs compare their page-embedded id with
the server's current id (every 15-min tick) and reload themselves when a
deploy happened, instead of posting callbacks with stale signatures.
"""
import os

def _build_id():
    newest = 0.0
    root_dir = os.path.dirname(os.path.abspath(__file__))
    for root, _dirs, files in os.walk(root_dir):
        for f in files:
            if f.endswith((".py", ".css", ".js")):
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(root, f)))
                except OSError:
                    pass
    return str(int(newest))

BUILD_ID = _build_id()
