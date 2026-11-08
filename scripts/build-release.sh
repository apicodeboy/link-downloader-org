#!/usr/bin/env bash
# Build a deployable release tarball: dist/video-downloader-<version>.tar.gz
#   scripts/build-release.sh [version]      (default version: short git commit)
# Contains the backend source, worker, built Next.js standalone server, deploy files and
# scripts. No virtualenv, database, media, .env or secrets are included.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
[[ "$VERSION" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "bad version"; exit 2; }
STAGE="$ROOT/dist/stage"
OUT="$ROOT/dist/video-downloader-$VERSION.tar.gz"

case "$STAGE" in "$ROOT"/dist/stage) rm -rf -- "$STAGE" ;; esac
mkdir -p "$STAGE"

echo "==> Building frontend"
(cd "$ROOT/frontend" && npm ci --no-fund --no-audit && npm run build)
mkdir -p "$STAGE/frontend"
cp -R "$ROOT/frontend/.next/standalone/." "$STAGE/frontend/"
mkdir -p "$STAGE/frontend/.next"
cp -R "$ROOT/frontend/.next/static" "$STAGE/frontend/.next/static"
[ -d "$ROOT/frontend/public" ] && cp -R "$ROOT/frontend/public" "$STAGE/frontend/public"
[ -f "$STAGE/frontend/server.js" ] || { echo "standalone server.js missing"; exit 1; }

echo "==> Copying backend, worker, deploy files"
rsync -a --exclude '.venv' --exclude 'data' --exclude '.env' --exclude '__pycache__' \
      --exclude '.pytest_cache' --exclude '*.db' "$ROOT/backend/" "$STAGE/backend/"
rsync -a --exclude '__pycache__' "$ROOT/worker/" "$STAGE/worker/"
rsync -a "$ROOT/deploy/" "$STAGE/deploy/"
rsync -a "$ROOT/scripts/" "$STAGE/scripts/"
cp "$ROOT/.env.example" "$STAGE/.env.example"
echo "$VERSION" > "$STAGE/VERSION"

# Guard: never ship secrets.
if find "$STAGE" \( -name '.env' -o -name '*.pem' -o -name 'id_rsa*' -o -name 'id_ed25519*' -o -name 'cookies*.txt' \) | grep -q .; then
  echo "Refusing to package: secret-looking file found"; exit 1
fi

tar -czf "$OUT" -C "$STAGE" .
echo "==> $OUT ($(du -h "$OUT" | cut -f1))"
