#!/usr/bin/env bash
# CI check (run on a test server after install + deploy): a guest's file is served by
# Nginx via X-Accel-Redirect, supports seeking, and is invisible to other visitors.
set -euo pipefail
HOST="${1:-videos.example.test}"
APP=/opt/video-downloader

new_guest() {
  curl -fsS -D - -o /dev/null -H "Host: $HOST" http://127.0.0.1/api/auth/me \
    | tr -d '\r' | sed -nE 's/^[Ss]et-[Cc]ookie: vd_session=([^;]+).*/\1/p'
}
A="$(new_guest)"; B="$(new_guest)"
[ -n "$A" ] && [ -n "$B" ] || { echo "no guest cookie"; exit 1; }
UID_A="$(curl -fsS -H "Host: $HOST" -H "Cookie: vd_session=$A" http://127.0.0.1/api/auth/me | python3 -c 'import json,sys; print(json.load(sys.stdin)["user"]["id"])')"

# Create a 2 MB "video" for guest A exactly as the worker would (as videodl, same umask).
FILE_ID="$(sudo systemd-run --quiet --wait --pipe --collect --uid=videodl --gid=videodl -p UMask=0027 \
  -p EnvironmentFile=/etc/video-downloader/video-downloader.env -p WorkingDirectory="$APP/current/backend" \
  "$APP/current/backend/.venv/bin/python" -c "
import os
from app.config import get_settings
from app.db import session_scope
from app.models import MediaFile
s = get_settings(); d = s.media_dir / 'ci-check'; d.mkdir(exist_ok=True)
(d / 'video.mp4').write_bytes(os.urandom(2 * 1024 * 1024))
with session_scope() as db:
    mf = MediaFile(user_id=$UID_A, kind='video', path='ci-check/video.mp4', filename='ci.mp4', mime_type='video/mp4', size_bytes=2097152)
    db.add(mf); db.flush(); print(mf.id)
")"
echo "file id: $FILE_ID"
ls -l /var/lib/video-downloader/media/ci-check/

URL="http://127.0.0.1/api/media/$FILE_ID/file"
code="$(curl -sS -o /tmp/full.bin -w '%{http_code}' -H "Host: $HOST" -H "Cookie: vd_session=$A" "$URL?download=1")"
[ "$code" = 200 ] && [ "$(stat -c %s /tmp/full.bin)" = 2097152 ] || { echo "full download failed ($code)"; exit 1; }
headers="$(curl -sS -D - -o /tmp/part.bin -H "Host: $HOST" -H "Cookie: vd_session=$A" -r 100-199 "$URL")"
echo "$headers" | grep -q "^HTTP/1.1 206" || { echo "range request not honoured"; echo "$headers"; exit 1; }
[ "$(stat -c %s /tmp/part.bin)" = 100 ] || { echo "wrong range size"; exit 1; }
echo "$headers" | grep -qi '^x-accel-redirect' && { echo "internal header leaked"; exit 1; }
echo "$headers" | grep -qi '^content-type: video/mp4' || { echo "wrong content type"; echo "$headers"; exit 1; }
code="$(curl -sS -o /dev/null -w '%{http_code}' -H "Host: $HOST" -H "Cookie: vd_session=$B" "$URL")"
[ "$code" = 404 ] || { echo "other visitor got $code"; exit 1; }
code="$(curl -sS -o /dev/null -w '%{http_code}' -H "Host: $HOST" "http://127.0.0.1/_protected_media/ci-check/video.mp4")"
[ "$code" = 404 ] || { echo "internal location reachable directly ($code)"; exit 1; }
echo "file serving OK (Nginx X-Accel, range requests, per-visitor privacy)"
