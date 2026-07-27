#!/bin/sh
# Nightly pg_dump of the AIS database into /data/backups on the existing
# picasso_data volume, so the current off-VPS sync (WireGuard -> Proxmox)
# picks it up with everything else. Runs at ~03:00 UTC, keeps
# BACKUP_RETENTION_DAYS days (default 14).

set -u
RETENTION="${BACKUP_RETENTION_DAYS:-14}"
DEST=/data/backups
mkdir -p "$DEST"

echo "ais-backup: started, retention ${RETENTION} days"

while true; do
    # seconds until next 03:00 UTC
    now=$(date -u +%s)
    target=$(date -u -d "03:00" +%s 2>/dev/null || date -u -D "%H:%M" -d "03:00" +%s)
    [ "$target" -le "$now" ] && target=$((target + 86400))
    sleep $((target - now))

    stamp=$(date -u +%Y%m%d)
    out="$DEST/ais_${stamp}.dump"
    echo "ais-backup: dumping to $out"
    if pg_dump -h ais-db -U ais -d ais -Fc -f "$out.tmp"; then
        mv "$out.tmp" "$out"
        echo "ais-backup: ok ($(du -h "$out" | cut -f1))"
    else
        echo "ais-backup: pg_dump FAILED"
        rm -f "$out.tmp"
    fi

    # rotate
    find "$DEST" -name 'ais_*.dump' -mtime +"$RETENTION" -delete
done
