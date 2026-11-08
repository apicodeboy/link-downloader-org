#!/usr/bin/env bash
# =============================================================================
# One-time server setup for Video Downloader on Ubuntu (22.04 / 24.04).
#
# SAFE BY DESIGN
#   * Never edits or deletes other websites, Nginx sites, PM2 apps or certificates.
#   * Only creates things named "video-downloader" / "videodl".
#   * Installs apt packages only if they are missing (never upgrades or removes).
#   * Refuses to continue if the domain or ports are already used by something else.
#   * Re-running it is safe (idempotent). Every change is listed in
#     /etc/video-downloader/install-manifest.txt, and scripts/rollback.sh --disable undoes it.
#
# USAGE (as root, after reading it and after running server-inspect.sh):
#   sudo bash install-server.sh --domain videos.example.com [--api-port 8010] [--web-port 3010]
#                               [--redis-db 5] [--workers 2] [--with-deno] [--yes]
# =============================================================================
set -euo pipefail

DOMAIN=""; API_PORT=8010; WEB_PORT=3010; REDIS_DB=5; WORKERS=2; WITH_DENO=0; ASSUME_YES=0; SKIP_NGINX=0
PM2_VERSION="7.1.2"; NODE_MAJOR="24"; PY_VERSION="3.12"

APP=/opt/video-downloader
DATA=/var/lib/video-downloader
ETC=/etc/video-downloader
ENVF=$ETC/video-downloader.env
MANIFEST=$ETC/install-manifest.txt
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --api-port) API_PORT="$2"; shift 2 ;;
    --web-port) WEB_PORT="$2"; shift 2 ;;
    --redis-db) REDIS_DB="$2"; shift 2 ;;
    --workers) WORKERS="$2"; shift 2 ;;
    --with-deno) WITH_DENO=1; shift ;;
    --skip-nginx) SKIP_NGINX=1; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1"; exit 2 ;;
  esac
done

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARNING:\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
record() { mkdir -p "$ETC"; grep -qxF "$1" "$MANIFEST" 2>/dev/null || echo "$1" >> "$MANIFEST"; }
have() { command -v "$1" >/dev/null 2>&1; }

[ "$(id -u)" -eq 0 ] || die "Run as root (sudo)."
[ -n "$DOMAIN" ] || die "--domain is required (e.g. --domain videos.example.com)."
[[ "$DOMAIN" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] || die "Invalid domain: $DOMAIN"
[[ "$API_PORT" =~ ^[0-9]+$ && "$WEB_PORT" =~ ^[0-9]+$ && "$REDIS_DB" =~ ^[0-9]+$ && "$WORKERS" =~ ^[1-8]$ ]] || die "Bad numeric option."
[ -f "$SRC_DIR/deploy/systemd/video-downloader-api.service" ] || die "Run this from inside the repository checkout."
. /etc/os-release
[ "${ID:-}" = "ubuntu" ] || [ "${ID_LIKE:-}" = "debian" ] || warn "Tested on Ubuntu; this is $PRETTY_NAME."
case "$(uname -m)" in
  x86_64) ARCH=x86_64; NODE_ARCH=x64 ;;
  aarch64) ARCH=aarch64; NODE_ARCH=arm64 ;;
  *) die "Unsupported CPU architecture $(uname -m)" ;;
esac

# ------------------------------------------------------------------ preflight
say "Preflight checks"
port_owner() { ss -tlnpH "sport = :$1" 2>/dev/null | grep -oE 'users:\(\("[^"]+' | cut -d'"' -f2 | head -1; }
for p in "$API_PORT" "$WEB_PORT"; do
  owner="$(port_owner "$p")"
  if [ -n "$owner" ] && ! systemctl is-active --quiet video-downloader-api video-downloader-web 2>/dev/null; then
    die "Port $p is already used by '$owner'. Choose another with --api-port/--web-port."
  fi
done
if [ "$SKIP_NGINX" -eq 0 ]; then
  have nginx || die "Nginx is not installed. Install it or use --skip-nginx."
  if nginx -T 2>/dev/null | grep -E "^\s*server_name\b" | grep -qw -- "$DOMAIN"; then
    nginx -T 2>/dev/null | grep -B2 -E "server_name.*\b$DOMAIN\b" | grep -q "video-downloader" \
      || die "Another Nginx site already uses server_name $DOMAIN. Pick a different (sub)domain."
  fi
  nginx -t >/dev/null 2>&1 || die "Your current Nginx config already fails 'nginx -t'. Fix that first; nothing was changed."
fi
FREE_KB=$(df --output=avail /var/lib | tail -1)
[ "$FREE_KB" -gt $((3*1024*1024)) ] || warn "Less than 3 GB free on /var/lib. Lower MAX_STORAGE_MB in the env file."

cat <<PLAN

Plan (nothing outside this list will be touched):
  * apt packages, only if missing: ffmpeg, redis-server, sqlite3, curl, xz-utils, unzip
  * system user 'videodl' (runs the app, no login) and 'videodl-deploy' (SSH deploys only)
  * $APP           code releases + private Python $PY_VERSION, Node $NODE_MAJOR, PM2 $PM2_VERSION, uv
  * $DATA          database, temporary media (auto-deleted), backups
  * $ENVF  settings (created once, never overwritten)
  * systemd units video-downloader-{api,web,cleanup}, video-downloader-worker@1..$WORKERS
  * /usr/local/sbin/video-downloader-{deploy,rollback,cli}
  * /etc/sudoers.d/video-downloader (deploy user may run only deploy/rollback)
  * Nginx site for $DOMAIN -> API 127.0.0.1:$API_PORT, UI 127.0.0.1:$WEB_PORT
  * Redis database number $REDIS_DB on the local Redis
PLAN
if [ "$ASSUME_YES" -ne 1 ]; then
  read -r -p "Proceed? [y/N] " ans; [[ "$ans" =~ ^[Yy]$ ]] || { echo "Aborted. Nothing changed."; exit 0; }
fi

# ------------------------------------------------------------------ packages
say "Installing missing packages"
need=()
have ffmpeg || need+=(ffmpeg)
have ffprobe || need+=(ffmpeg)
have redis-server || have redis-cli || need+=(redis-server)
have sqlite3 || need+=(sqlite3)
have curl || need+=(curl)
have xz || need+=(xz-utils)
[ "$WITH_DENO" -eq 1 ] && ! have unzip && need+=(unzip)
if [ ${#need[@]} -gt 0 ]; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends ca-certificates "${need[@]}"
  for p in "${need[@]}"; do record "apt:$p"; done
else
  echo "All required packages already present."
fi
if ! ffmpeg -hide_banner -encoders 2>/dev/null | grep -q ' libx264 '; then
  warn "This FFmpeg has no libx264; processing will fall back to the mpeg4 encoder."
fi
systemctl is-active --quiet redis-server 2>/dev/null || systemctl is-active --quiet redis 2>/dev/null \
  || { systemctl enable --now redis-server 2>/dev/null || warn "Start Redis manually."; }

# ------------------------------------------------------------------ users and folders
say "Creating users and folders"
if ! id videodl >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA" --no-create-home --shell /usr/sbin/nologin videodl
  record "user:videodl"
fi
if ! id videodl-deploy >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash videodl-deploy
  passwd -l videodl-deploy >/dev/null
  record "user:videodl-deploy"
fi
install -d -m 0700 -o videodl-deploy -g videodl-deploy /home/videodl-deploy/.ssh /home/videodl-deploy/incoming
touch /home/videodl-deploy/.ssh/authorized_keys
chown videodl-deploy:videodl-deploy /home/videodl-deploy/.ssh/authorized_keys
chmod 0600 /home/videodl-deploy/.ssh/authorized_keys
install -d -m 0755 "$APP" "$APP/releases" "$APP/shared" "$APP/shared/bin"
install -d -m 0750 -o videodl -g videodl "$DATA" "$DATA/media" "$DATA/work" "$DATA/watermarks" "$DATA/backups"
install -d -m 0750 -o root -g videodl "$ETC"
install -d -m 0755 /var/cache/video-downloader
record "dir:$APP"; record "dir:$DATA"; record "dir:$ETC"

# ------------------------------------------------------------------ verified downloads
fetch_verified() {  # url sha_url_or_value dest
  local url="$1" sha="$2" dest="$3" tmp
  tmp="$(mktemp)"
  curl -fsSL --retry 3 -o "$tmp" "$url"
  echo "$sha  $tmp" | sha256sum -c --quiet - || { rm -f "$tmp"; die "Checksum mismatch for $url"; }
  mv "$tmp" "$dest"
}

say "Installing uv (Python manager, from github.com/astral-sh/uv)"
if [ ! -x "$APP/shared/bin/uv" ]; then
  base="https://github.com/astral-sh/uv/releases/latest/download/uv-${ARCH}-unknown-linux-gnu.tar.gz"
  sha="$(curl -fsSL "$base.sha256" | awk '{print $1}')"
  fetch_verified "$base" "$sha" /tmp/uv.tar.gz
  tar -xzf /tmp/uv.tar.gz -C /tmp
  install -m 0755 "/tmp/uv-${ARCH}-unknown-linux-gnu/uv" "$APP/shared/bin/uv"
  rm -rf /tmp/uv.tar.gz "/tmp/uv-${ARCH}-unknown-linux-gnu"
fi
export UV_PYTHON_INSTALL_DIR="$APP/shared/python" UV_CACHE_DIR=/var/cache/video-downloader/uv
"$APP/shared/bin/uv" python install "$PY_VERSION" >/dev/null
chmod -R a+rX "$APP/shared/python"
echo "Python: $("$APP/shared/bin/uv" python find "$PY_VERSION")"

say "Installing private Node.js $NODE_MAJOR (from nodejs.org, checksum verified)"
if [ ! -x "$APP/shared/node/bin/node" ]; then
  sums="$(curl -fsSL "https://nodejs.org/dist/latest-v${NODE_MAJOR}.x/SHASUMS256.txt")"
  file="$(echo "$sums" | awk '{print $2}' | grep -E "^node-v[0-9.]+-linux-${NODE_ARCH}\.tar\.xz$" | head -1)"
  sha="$(echo "$sums" | awk -v f="$file" '$2==f {print $1}')"
  fetch_verified "https://nodejs.org/dist/latest-v${NODE_MAJOR}.x/$file" "$sha" /tmp/node.tar.xz
  install -d -m 0755 "$APP/shared/node"
  tar -xJf /tmp/node.tar.xz -C "$APP/shared/node" --strip-components=1 --no-same-owner
  rm -f /tmp/node.tar.xz
fi
echo "Node: $("$APP/shared/node/bin/node" -v)"

say "Installing private PM2 $PM2_VERSION (separate from any existing PM2)"
if [ ! -x "$APP/shared/pm2/node_modules/.bin/pm2-runtime" ]; then
  install -d -m 0755 "$APP/shared/pm2"
  PATH="$APP/shared/node/bin:$PATH" "$APP/shared/node/bin/npm" install --silent --no-fund --no-audit \
    --prefix "$APP/shared/pm2" "pm2@$PM2_VERSION"
fi

if [ "$WITH_DENO" -eq 1 ] && [ ! -x "$APP/shared/bin/deno" ]; then
  say "Installing Deno (sandboxed JavaScript runtime for YouTube, from github.com/denoland/deno)"
  base="https://github.com/denoland/deno/releases/latest/download/deno-${ARCH}-unknown-linux-gnu.zip"
  sha="$(curl -fsSL "$base.sha256sum" | awk '{print $1}')"
  fetch_verified "$base" "$sha" /tmp/deno.zip
  unzip -o -q /tmp/deno.zip -d "$APP/shared/bin" && chmod 0755 "$APP/shared/bin/deno" && rm -f /tmp/deno.zip
fi

# ------------------------------------------------------------------ settings
say "Writing settings file (only if it doesn't exist)"
if [ ! -f "$ENVF" ]; then
  umask 027
  sed -e "s|^APP_ENV=.*|APP_ENV=production|" \
      -e "s|^DATABASE_URL=.*|DATABASE_URL=sqlite:///$DATA/app.db|" \
      -e "s|^REDIS_URL=.*|REDIS_URL=redis://127.0.0.1:6379/$REDIS_DB|" \
      -e "s|^DATA_DIR=.*|DATA_DIR=$DATA|" \
      -e "s|^SESSION_COOKIE_SECURE=.*|SESSION_COOKIE_SECURE=true|" \
      -e "s|^ALLOWED_ORIGINS=.*|ALLOWED_ORIGINS=https://$DOMAIN|" \
      "$SRC_DIR/.env.example" > "$ENVF"
  {
    echo ""
    echo "# --- Server-only settings written by install-server.sh ---"
    echo "VD_API_PORT=$API_PORT"
    echo "VD_WEB_PORT=$WEB_PORT"
    echo "VD_WORKERS=$WORKERS"
    echo "VD_DOMAIN=$DOMAIN"
    echo "UV_PYTHON_INSTALL_DIR=$APP/shared/python"
  } >> "$ENVF"
  chown root:videodl "$ENVF"; chmod 0640 "$ENVF"
  record "file:$ENVF"
else
  echo "Keeping existing $ENVF"
fi

# ------------------------------------------------------------------ helper commands
say "Installing helper commands"
for name in deploy rollback cli; do
  src="$SRC_DIR/scripts/server/video-downloader-$name"
  install -m 0755 -o root -g root "$src" "/usr/local/sbin/video-downloader-$name"
  record "file:/usr/local/sbin/video-downloader-$name"
done
tmp_sudo="$(mktemp)"
cp "$SRC_DIR/deploy/sudoers/video-downloader" "$tmp_sudo"
visudo -cf "$tmp_sudo" >/dev/null || die "sudoers file failed validation; not installed."
install -m 0440 -o root -g root "$tmp_sudo" /etc/sudoers.d/video-downloader
rm -f "$tmp_sudo"
record "file:/etc/sudoers.d/video-downloader"

# ------------------------------------------------------------------ systemd
say "Installing systemd units"
for unit in video-downloader-api.service video-downloader-web.service video-downloader-worker@.service \
            video-downloader-cleanup.service video-downloader-cleanup.timer; do
  dest="/etc/systemd/system/$unit"
  if [ -f "$dest" ] && ! cmp -s "$SRC_DIR/deploy/systemd/$unit" "$dest"; then
    cp "$dest" "$dest.bak.$(date +%s)"
  fi
  install -m 0644 "$SRC_DIR/deploy/systemd/$unit" "$dest"
  record "file:$dest"
done
systemctl daemon-reload
systemctl enable video-downloader-api.service video-downloader-web.service video-downloader-cleanup.timer >/dev/null
for i in $(seq 1 "$WORKERS"); do systemctl enable "video-downloader-worker@$i.service" >/dev/null; done
echo "Services enabled; they start on the first deploy."

# ------------------------------------------------------------------ nginx
if [ "$SKIP_NGINX" -eq 0 ]; then
  say "Adding Nginx site for $DOMAIN"
  if [ -d /etc/nginx/sites-available ]; then
    site=/etc/nginx/sites-available/video-downloader.conf; link=/etc/nginx/sites-enabled/video-downloader.conf
  else
    site=/etc/nginx/conf.d/video-downloader.conf; link=""
  fi
  rendered="$(mktemp)"
  sed -e "s|__DOMAIN__|$DOMAIN|g" -e "s|__API_PORT__|$API_PORT|g" -e "s|__WEB_PORT__|$WEB_PORT|g" -e "s|__DATA_DIR__|$DATA|g" \
      "$SRC_DIR/deploy/nginx/video-downloader.conf.template" > "$rendered"
  if [ -f "$site" ]; then
    if cmp -s "$rendered" "$site"; then echo "Nginx site unchanged."; else
      cp "$rendered" "$site.new"
      warn "$site already exists (Certbot may have edited it). New version saved as $site.new; review and merge manually."
    fi
    rm -f "$rendered"
  else
    install -m 0644 "$rendered" "$site"; rm -f "$rendered"; record "file:$site"
  fi
  if [ -n "$link" ] && [ ! -e "$link" ]; then ln -s "$site" "$link"; record "file:$link"; fi
  if nginx -t 2>/tmp/vd-nginx-test.log; then
    systemctl reload nginx
    echo "Nginx reloaded."
  else
    cat /tmp/vd-nginx-test.log
    [ -n "$link" ] && rm -f "$link"
    die "nginx -t failed with the new site, so it was disabled again. Other sites were not affected."
  fi
fi

cat <<NEXT

Installation complete. Next steps (details in docs/DEPLOYMENT.md):

  1. DNS: point an A record for $DOMAIN to this server's IP.
  2. HTTPS:   sudo certbot --nginx -d $DOMAIN
  3. Deploy key: add the GitHub Actions public key to /home/videodl-deploy/.ssh/authorized_keys
  4. First release: push to main (GitHub Actions), or build locally with scripts/build-release.sh,
     copy the tarball to /home/videodl-deploy/incoming/ and run:
       sudo video-downloader-deploy /home/videodl-deploy/incoming/video-downloader-<version>.tar.gz
  5. Create your login:   sudo video-downloader-cli create-admin <username>
  6. Review settings in $ENVF (then: sudo systemctl restart video-downloader-api 'video-downloader-worker@*')

To undo everything later:  sudo video-downloader-rollback --disable
NEXT
