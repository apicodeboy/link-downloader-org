#!/usr/bin/env bash
# =============================================================================
# READ-ONLY server inspection. Changes nothing. Run this FIRST on your VPS and
# paste the output back so the deployment can be planned around what's there.
#
#   curl -fsSLO https://raw.githubusercontent.com/<you>/video-downloader/main/scripts/server-inspect.sh
#   less server-inspect.sh        # read it first
#   sudo bash server-inspect.sh 2>&1 | tee inspect-report.txt
#
# sudo is only needed so it can read the Nginx config and list every listening port.
# It does not install, start, stop, edit or delete anything.
# =============================================================================
set -u
API_PORT="${API_PORT:-8010}"
WEB_PORT="${WEB_PORT:-3010}"
section() { printf '\n==================== %s ====================\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

section "Operating system"
cat /etc/os-release 2>/dev/null | grep -E '^(PRETTY_NAME|VERSION_ID)='
uname -srm
echo "uptime: $(uptime -p 2>/dev/null || uptime)"
echo "CPU cores: $(nproc 2>/dev/null)"
free -h 2>/dev/null | sed -n '1,2p'
have systemctl && echo "init: systemd $(systemctl --version | head -1 | awk '{print $2}')"

section "Disk space"
df -h -x tmpfs -x devtmpfs 2>/dev/null
for d in /opt /var/lib /srv /home; do [ -d "$d" ] && printf '%-10s %s free\n' "$d" "$(df -h --output=avail "$d" | tail -1 | tr -d ' ')"; done

section "Listening ports (who is using what)"
if have ss; then ss -tlnpH 2>/dev/null | awk '{print $4, $6}' | sort -u; else netstat -tlnp 2>/dev/null; fi
for p in "$API_PORT" "$WEB_PORT"; do
  if ss -tlnH "sport = :$p" 2>/dev/null | grep -q .; then echo "PORT $p: IN USE  -> pick another with --api-port/--web-port"
  else echo "PORT $p: free"; fi
done

section "Running services (web/app related)"
systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null \
  | grep -Ei 'nginx|apache|httpd|caddy|redis|valkey|postgres|mysql|maria|php|pm2|node|docker|gunicorn|uvicorn|supervisor|cloudpanel|plesk|cpanel' \
  || echo "(none of the usual web services found)"

section "Nginx"
if have nginx; then
  nginx -v 2>&1
  echo "--- config test ---"; nginx -t 2>&1 | tail -2
  echo "--- server_name / listen lines per enabled site ---"
  for f in /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf; do
    [ -e "$f" ] || continue
    echo "# $f"
    grep -hE '^\s*(server_name|listen|root|proxy_pass)\b' "$f" 2>/dev/null | sed 's/^\s*/    /' | sort -u
  done
  echo "--- existing video-downloader files (should be none on first install) ---"
  ls -la /etc/nginx/sites-available/video-downloader* /etc/nginx/sites-enabled/video-downloader* 2>/dev/null || echo "none"
  echo "--- limit_req_zone names in use ---"
  nginx -T 2>/dev/null | grep -oE 'limit_req_zone[^;]*zone=[a-zA-Z0-9_]+' | sort -u || true
else
  echo "nginx NOT installed"
fi

section "TLS certificates (Certbot)"
if have certbot; then certbot --version 2>&1; certbot certificates 2>/dev/null | grep -E 'Certificate Name|Domains|Expiry' || true
else echo "certbot NOT installed"; fi

section "PM2 (other apps; we will NOT touch these)"
if have pm2; then echo "pm2 at $(command -v pm2) version $(pm2 -v 2>/dev/null)"; pm2 jlist 2>/dev/null | grep -oE '"name":"[^"]+"' | sort -u || true; fi
for home in /root /home/*; do
  [ -d "$home/.pm2" ] && echo "PM2 home found: $home/.pm2 (owner $(stat -c %U "$home/.pm2"))"
done
ps -eo user,cmd 2>/dev/null | grep -E '[P]M2|[p]m2' | head -5

section "Node.js"
if have node; then echo "node $(node -v) at $(readlink -f "$(command -v node)")"; else echo "node NOT on PATH"; fi
ls -d /root/.nvm /home/*/.nvm 2>/dev/null && echo "(nvm installs are private to one user; the app will use its own Node build)"

section "Python"
for py in python3 python3.13 python3.12 python3.11 python3.10; do have "$py" && echo "$py -> $($py -V 2>&1)"; done
echo "yt-dlp needs Python >= 3.11. The installer uses uv to provide Python 3.12 privately if the system one is older."
have uv && echo "uv $(uv --version)"

section "FFmpeg"
if have ffmpeg; then ffmpeg -hide_banner -version | head -1; ffmpeg -hide_banner -encoders 2>/dev/null | grep -E ' libx264 ' || echo "WARNING: libx264 encoder missing"
else echo "ffmpeg NOT installed (apt install ffmpeg)"; fi
have ffprobe && echo "ffprobe present" || echo "ffprobe NOT installed"

section "Redis"
if have redis-cli; then
  redis-server --version 2>/dev/null | head -1
  if redis-cli ping >/dev/null 2>&1; then
    echo "redis responding on default port"
    redis-cli info keyspace 2>/dev/null | grep '^db' || echo "no keys in any database"
    echo "(the app will use a database number that is empty above, default 5)"
  else
    echo "redis-cli present but no server answering on 127.0.0.1:6379 (it may require a password)"
  fi
else echo "redis NOT installed"; fi

section "Firewall"
have ufw && ufw status 2>/dev/null | head -15
have iptables && echo "iptables rules: $(iptables -S 2>/dev/null | wc -l)"

section "Existing video-downloader install (should be empty on first install)"
ls -la /opt/video-downloader /var/lib/video-downloader /etc/video-downloader 2>/dev/null || echo "none"
id videodl 2>/dev/null || echo "user videodl: does not exist"
id videodl-deploy 2>/dev/null || echo "user videodl-deploy: does not exist"
systemctl list-unit-files 'video-downloader*' --no-pager --no-legend 2>/dev/null || true

section "Summary"
echo "Report complete. Nothing was changed."
