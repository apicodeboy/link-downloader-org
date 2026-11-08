#!/bin/bash
# Run on the VPS after its loopback frontend and API pass their checks.
set -euo pipefail
domain=linkdownloader.org
vhost=/etc/nginx/sites-available/linkdownloader.org.conf
enabled=/etc/nginx/sites-enabled/linkdownloader.org.conf
marker='# Managed by the linkdownloader.org VPS deployment'
[ "$(id -u)" = 0 ] || { echo 'Run with sudo.'; exit 1; }
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
exec 9>/run/lock/linkdownloader-domain.lock
flock -n 9 || { echo 'Another activation is running.'; exit 1; }
health() { curl -fsS --max-time 10 "$@" | python3 -c 'import json,sys; h=json.load(sys.stdin); assert h["status"]=="ok" and all(h["checks"].get(k) is True for k in ("database","queue","ffmpeg")), h'; }
health http://127.0.0.1:18110/api/health
curl -fsS --max-time 10 -o /dev/null http://127.0.0.1:13110/login
nginx -t
nginx -T >"$scratch/nginx" 2>/dev/null
python3 - "$scratch/nginx" "$vhost" "$enabled" <<'PY'
import re,sys
owner=''
for line in open(sys.argv[1]):
    if line.startswith('# configuration file '):
        owner=line.strip().removeprefix('# configuration file ').rstrip(':')
    elif owner not in sys.argv[2:]:
        for hosts in re.findall(r'\bserver_name\s+([^;]+);',line.partition('#')[0]):
            names={v.strip('"').lower().rstrip('.') for v in hosts.split()}
            if names & {'linkdownloader.org','www.linkdownloader.org'}:
                sys.exit('Existing site handles the domain: '+owner+'. Review before switching.')
PY
if [ -e "$vhost" ] || [ -L "$vhost" ]; then
  [ ! -L "$vhost" ] && grep -Fxq "$marker" "$vhost" || { echo "Review existing $vhost first."; exit 1; }
else
  cat > "$scratch/site" <<'NGINX'
# Managed by the linkdownloader.org VPS deployment
limit_req_zone $binary_remote_addr zone=ld_login:1m rate=10r/m;
limit_req_zone $binary_remote_addr zone=ld_api:5m rate=20r/s;
server {
    listen 80;
    listen [::]:80;
    server_name linkdownloader.org www.linkdownloader.org;
    client_max_body_size 8m;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Real-IP $remote_addr;
    location = /api/auth/login {
        limit_req zone=ld_login burst=5 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:18110;
    }
    location /api/ {
        limit_req zone=ld_api burst=40 nodelay;
        limit_req_status 429;
        proxy_buffering off;
        proxy_read_timeout 300s;
        proxy_pass http://127.0.0.1:18110;
    }
    location / { proxy_pass http://127.0.0.1:13110; }
}
NGINX
  install -m 644 "$scratch/site" "$vhost"
fi
newlink=0
if [ -e "$enabled" ] || [ -L "$enabled" ]; then
  [ "$(readlink -f "$enabled")" = "$vhost" ] || { echo "Review existing $enabled first."; exit 1; }
else
  ln -s "$vhost" "$enabled"
  newlink=1
fi
if ! nginx -t; then
  if [ "$newlink" = 1 ]; then rm -- "$enabled"; fi
  exit 1
fi
systemctl reload nginx
if ! command -v certbot >/dev/null || ! certbot plugins 2>/dev/null | grep -F nginx >/dev/null; then
  apt-get update -qq && apt-get install -y --no-install-recommends certbot python3-certbot-nginx
fi
if ! curl -fsS -o /dev/null --max-time 10 --resolve "$domain:443:127.0.0.1" "https://$domain/login" || ! curl -fsS -o /dev/null --max-time 10 --resolve "www.$domain:443:127.0.0.1" "https://www.$domain/login"; then
  certbot --nginx --redirect --cert-name "$domain" -d "$domain" -d "www.$domain"
fi
for host in "$domain" "www.$domain"; do
  health --resolve "$host:443:127.0.0.1" "https://$host/api/health"
  health "https://$host/api/health"
  curl -fsS -o /dev/null --max-time 10 "https://$host/login"
done
echo 'LIVE: both hostnames passed HTTPS, website and downloader checks.'
