#!/usr/bin/env bash
set -euo pipefail
umask 022
domain=linkdownloader.org
ip=2.25.142.128
release=78e4ea79
src=$(cd "$(dirname "$0")/../.." && pwd)
[ -f "$src/frontend/package-lock.json" ] && [ -f "$src/deploy/systemd/video-downloader-api.service" ] || { echo "Incomplete release source."; exit 1; }
cfg=/etc/video-downloader/video-downloader.env
stage_root=$(mktemp -d /root/linkdownloader-stage.XXXXXXXXXX)
trap 'rm -rf -- "$stage_root"' EXIT
die() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die 'A sudo-capable login is required.'
. /etc/os-release
[ "$ID" = ubuntu ] && [ "$(uname -m)" = x86_64 ] || die 'This package targets an x86_64 Ubuntu server.'
# Do not let two copies of the launcher run at the same time.
exec 9>/run/lock/linkdownloader-stage.lock
flock -n 9 || die 'Another copy of this installer is running.'

nginx -t
systemctl is-active --quiet nginx || die 'Nginx must already be running.'
nginx -T > "$stage_root/nginx-active" 2>/dev/null
# The installer owns only its dedicated vhost. Check both requested names.
python3 - "$stage_root/nginx-active" <<'PY'
import re, sys
allowed = {'/etc/nginx/sites-enabled/video-downloader.conf','/etc/nginx/conf.d/video-downloader.conf','/etc/nginx/sites-available/video-downloader.conf'}
path = ''
for line in open(sys.argv[1]):
    if line.startswith('# configuration file '):
        path = line.strip().removeprefix('# configuration file ').rstrip(':')
    if path not in allowed:
        for v in re.findall(r'\bserver_name\s+([^;]+);',line.partition('#')[0]):
            names = {t.strip('"').lower().rstrip('.') for t in v.split()}
            if names & {'linkdownloader.org','www.linkdownloader.org'}:
                sys.exit('STOP: An existing Nginx site already owns this name: '+path)
PY
setting() { sed -n "s/^$1=//p" "$cfg" | tail -n 1; }
# Add both public origins while preserving any other configured origins and file ownership.
ensure_origins() {
  python3 - "$cfg" <<'PYORIGINS'
import os, pathlib, stat, sys, tempfile
p=pathlib.Path(sys.argv[1])
old=p.read_text(); lines=old.splitlines(keepends=True)
idx=next((i for i,l in enumerate(lines) if l.startswith("ALLOWED_ORIGINS=")),None)
value=lines[idx].partition("=")[2].strip().strip("'\"") if idx is not None else ""
origins=[o.strip() for o in value.split(",") if o.strip()]
for origin in ("https://linkdownloader.org","https://www.linkdownloader.org"):
    if origin not in origins: origins.append(origin)
record="ALLOWED_ORIGINS="+",".join(origins)+"\n"
if idx is None: lines.append(("\n" if old and not old.endswith("\n") else "")+record)
else: lines[idx]=record
new="".join(lines)
if old==new: sys.exit(0)
st=p.stat()
with tempfile.NamedTemporaryFile(mode="w",dir=p.parent,delete=False) as tmp:
    tmp.write(new); tmp.flush(); os.fchown(tmp.fileno(),st.st_uid,st.st_gid); os.fchmod(tmp.fileno(),stat.S_IMODE(st.st_mode))
os.replace(tmp.name,p)
print("changed")
PYORIGINS
}

if [ -f "$cfg" ]; then
  [ "$(setting VD_DOMAIN)" = "$domain" ] || die 'Existing downloader settings belong to a different domain.'
fi
health() {
  curl -fsS --max-time 12 "$1" "${@:2}" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("status")=="ok" and all(d.get("checks",{}).get(k) is True for k in ("database","queue","ffmpeg")) else "Downloader is degraded: "+str(d))'
}
cert_ok() {
  curl -fsS --max-time 8 --resolve "$1:443:127.0.0.1" -o /dev/null "https://$1/"
}
if [ "${1:-stage}" = stage ]; then
  for f in /etc/nginx/sites-available/video-downloader.conf /etc/nginx/conf.d/video-downloader.conf; do
    if [ -e "$f" ]; then
      grep -Eq 'server_name[[:space:]]+linkdownloader\.org([[:space:];]|$)' "$f" || die "Existing $f serves a different domain."
      grep -Fq 'upstream vdl_api' "$f" && grep -Fq 'location /api/' "$f" || die "Review the existing $f before assigning this domain."
    fi
  done
  df_free=$(df --output=avail /var/lib | tail -1)
  [ "$df_free" -gt 3145728 ] || die 'At least 3 GiB of free space is required for installation.'
  cp -R -- "$src/deploy" "$src/scripts" "$src/.env.example" "$stage_root/"
  # Include both hostnames in the one site file that the upstream installer creates.
  sed -i 's/server_name __DOMAIN__;/server_name __DOMAIN__ www.__DOMAIN__;/' "$stage_root/deploy/nginx/video-downloader.conf.template"
  # Read all of nginx -T so a long multi-site configuration cannot cause SIGPIPE.
  python3 - "$stage_root/scripts/install-server.sh" <<'PY'
import pathlib,sys
p=pathlib.Path(sys.argv[1]); s=p.read_text()
s=s.replace("""'$1=="user"{gsub(";","",$2); print $2; exit}'""","""'$1=="user" && !seen{gsub(";","",$2); print $2; seen=1}'""")
p.write_text(s)
PY
  if [ -f "$cfg" ]; then
    api=$(setting VD_API_PORT); web=$(setting VD_WEB_PORT); redis_db=$(setting REDIS_URL); redis_db=${redis_db##*/}
    worker_count=$(setting VD_WORKERS)
  else
    free_port() {
      local p
      for p in "$@"; do
        if [ -z "$(ss -H -ltn "sport = :$p")" ]; then echo "$p"; return; fi
      done
      die 'No free application port was found.'
    }
    api=$(free_port 8010 8011 8012 8013); web=$(free_port 3010 3011 3012 3013)
    redis_db=5; worker_count=2
    if command -v redis-cli >/dev/null && [ -n "$(ss -H -ltn 'sport = :6379')" ]; then
      [ "$(redis-cli --raw ping)" = PONG ] || die 'Existing Redis requires a different connection configuration.'
      redis_db=''
      for n in 5 6 7 8 9 10 11 12 13 14 15; do
        if [ "$(redis-cli --raw -n "$n" dbsize)" = 0 ]; then redis_db=$n; break; fi
      done
      [ -n "$redis_db" ] || die 'No free Redis database was found.'
    elif [ -n "$(ss -H -ltn 'sport = :6379')" ]; then
      die 'Port 6379 is occupied and could not be verified as Redis.'
    fi
  fi
  active_version=$(cat /opt/video-downloader/current/VERSION 2>/dev/null || true)
  if [ -n "$active_version" ] && [ "$active_version" != "$release" ]; then
    die "A different release ($active_version) is already active. Verify it before replacing it."
  fi
  if [ "$active_version" != "$release" ]; then
    for p in "$api" "$web"; do
      [ -z "$(ss -H -ltn "sport = :$p")" ] || die "Port $p is already occupied."
    done
    bash "$stage_root/scripts/install-server.sh" --domain "$domain" --api-port "$api" --web-port "$web" --redis-db "$redis_db" --workers "$worker_count" --yes
    command -v rsync >/dev/null || { apt-get update -qq && apt-get install -y --no-install-recommends rsync; }
    build_dir=$(mktemp -d /var/tmp/linkdownloader-build.XXXXXXXXXX)
    trap 'rm -rf -- "$stage_root" "$build_dir"' EXIT
    # npm lifecycle scripts and Next.js run as the application user.
    cp -R -- "$src/backend" "$src/worker" "$src/frontend" "$src/scripts" "$src/deploy" "$src/.env.example" "$build_dir/"
    rm -rf -- "$build_dir/deploy/hostinger"
    install -d -m 0700 "$build_dir/.home"
    chown -R videodl:videodl "$build_dir"
    systemd-run --quiet --wait --pipe --collect --uid=videodl --gid=videodl \
      -p "WorkingDirectory=$build_dir" -p NoNewPrivileges=true -p ProtectSystem=strict \
      -p "ReadWritePaths=$build_dir" -p CPUQuota=120% -p MemoryMax=2600M \
      -E "HOME=$build_dir/.home" -E "PATH=/opt/video-downloader/shared/node/bin:/usr/bin:/bin" \
      -E NEXT_TELEMETRY_DISABLED=1 bash "$build_dir/scripts/build-release.sh" "$release"
    install -m 0600 "$build_dir/dist/video-downloader-$release.tar.gz" "$stage_root/video-downloader-$release.tar.gz"
    /usr/local/sbin/video-downloader-deploy "$stage_root/video-downloader-$release.tar.gz"
  fi
  # Reconcile just the downloader vhost when the app was installed previously.
  site=/etc/nginx/sites-available/video-downloader.conf
  link=/etc/nginx/sites-enabled/video-downloader.conf
  if [ ! -d /etc/nginx/sites-available ]; then site=/etc/nginx/conf.d/video-downloader.conf; link=''; fi
  site_existed=0; new_link=0
  if [ -f "$site" ]; then
    site_existed=1; cp -p -- "$site" "$stage_root/site.before"
    if ! grep -Eq 'server_name[^;]*[[:space:]]www\.linkdownloader\.org([[:space:];]|$)' "$site"; then
      sed -E 's/(server_name[[:space:]]+linkdownloader\.org)[[:space:]]*;/\1 www.linkdownloader.org;/' "$site" > "$stage_root/site.new"
      grep -Eq 'server_name[^;]*[[:space:]]www\.linkdownloader\.org([[:space:];]|$)' "$stage_root/site.new" || die 'Existing Nginx config needs manual hostname review.'
      install -m 0644 "$stage_root/site.new" "$site"
    fi
  else
    sed -e "s|__DOMAIN__|$domain|g" -e "s|__API_PORT__|$api|g" -e "s|__WEB_PORT__|$web|g" -e 's|__DATA_DIR__|/var/lib/video-downloader|g' "$stage_root/deploy/nginx/video-downloader.conf.template" > "$stage_root/site.new"
    install -m 0644 "$stage_root/site.new" "$site"
  fi
  if [ -n "$link" ] && [ ! -e "$link" ] && [ ! -L "$link" ]; then
    ln -s "$site" "$link"; new_link=1
  fi
  if ! nginx -t; then
    if [ "$new_link" = 1 ]; then rm -- "$link"; fi
    if [ "$site_existed" = 1 ]; then cp -p -- "$stage_root/site.before" "$site"; else rm -- "$site"; fi
    die 'Nginx rejected the downloader configuration. Previous configuration restored.'
  fi
  systemctl reload nginx
  systemctl start video-downloader-api video-downloader-web video-downloader-cleanup.timer video-downloader-worker@owner
  for ((i=1;i<=worker_count;i++)); do systemctl start "video-downloader-worker@$i"; done
  for ((i=0;i<25;i++)); do
    if health "http://127.0.0.1:$api/api/health" 2>/dev/null; then break; fi
    sleep 2
  done
  if [ "$(ensure_origins)" = changed ]; then
    systemctl restart video-downloader-api
    for ((i=0;i<25;i++)); do
      if health "http://127.0.0.1:$api/api/health" 2>/dev/null; then break; fi
      sleep 2
    done
  fi
  health "http://127.0.0.1:$api/api/health"
  systemctl is-active --quiet video-downloader-worker@owner
  for ((i=1;i<=worker_count;i++)); do systemctl is-active --quiet "video-downloader-worker@$i"; done
  systemctl is-active --quiet video-downloader-web
  systemctl is-active --quiet video-downloader-cleanup.timer
  for host in "$domain" "www.$domain"; do
    status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 --resolve "$host:80:127.0.0.1" "http://$host/api/health")
    case "$status" in
      200) health "http://$host/api/health" --resolve "$host:80:127.0.0.1";;
      301|302|307|308)
        redirect=$(curl -sS -o /dev/null -w '%{redirect_url}' --max-time 10 --resolve "$host:80:127.0.0.1" "http://$host/api/health")
        case "$redirect" in "https://$domain/api/health"|"https://www.$domain/api/health") :;; *) die "Unexpected redirect for $host.";; esac;;
      *) die "Nginx returned $status for $host.";;
    esac
  done
  if ! command -v certbot >/dev/null || ! certbot plugins 2>/dev/null | grep -F 'nginx' >/dev/null; then
    apt-get update -qq && apt-get install -y --no-install-recommends certbot python3-certbot-nginx
  fi
  printf '\nVPS READY FOR DNS — API, Redis, FFmpeg, frontend and workers passed.\n'
  echo 'Checking public addresses and enabling HTTPS for linkdownloader.org and www.'

elif [ "${1:-}" != https ]; then
  die 'Unknown mode.'
fi
[ -f "$cfg" ] || die 'Stage the application first.'
health "http://127.0.0.1:$(setting VD_API_PORT)/api/health"
dns_ready() {
  python3 - "$ip" "$domain" "www.$domain" <<'PY'
import ipaddress, socket, sys
expected = {ipaddress.ip_address(sys.argv[1]), ipaddress.ip_address("2a02:4780:75:aedd::1")}
for name in sys.argv[2:]:
    try:
        ips={ipaddress.ip_address(x[4][0]) for x in socket.getaddrinfo(name,80,type=socket.SOCK_STREAM)}
    except socket.gaierror:
        sys.exit(1)
    if not ips or not ips.issubset(expected):
        sys.exit(1)
PY
}
for ((i=0;i<90;i++)); do
  if dns_ready; then break; fi
  sleep 20
done
dns_ready || die 'DNS returned an unexpected address. Check the A and AAAA records for both hostnames.'
if ! cert_ok "$domain" || ! cert_ok "www.$domain"; then
  certbot --nginx --redirect --cert-name "$domain" -d "$domain" -d "www.$domain"
fi
for host in "$domain" "www.$domain"; do
  cert_ok "$host"
  health "https://$host/api/health" --resolve "$host:443:127.0.0.1"
  curl -fsS -o /dev/null --max-time 15 "https://$host/"
done
echo 'LIVE — both names passed HTTPS and downloader health checks.'
