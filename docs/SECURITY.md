# Security

By default the app is **open**: anyone with the address can use it without signing in
(`REQUIRE_LOGIN=false`). The main risks are therefore strangers overusing the server, one
visitor reaching another's files, someone tricking the server into fetching internal
addresses (SSRF), and content that shouldn't be downloaded at all.

## Controls

| Requirement | How it's done | Where |
| --- | --- | --- |
| Access mode | Open by default: each browser silently gets its own guest identity (a 30-day cookie). Guests only see and delete their own jobs and files. Guest creation is limited to 20 per IP per hour, and abandoned guests are purged. `REQUIRE_LOGIN=true` makes the site accounts-only. | `routers/auth.py`, `jobs/cleanup.py` |
| Admin authentication | Admin accounts are created only from the server command line, with scrypt password hashes and no sign-up page. Admin-only views: server status, audit trail, technical error details, publishing connection test and submit. | `security/passwords.py`, `cli.py`, `deps.py` |
| Server-wide capacity | `MAX_ACTIVE_JOBS_TOTAL` caps queued and running guest jobs across all visitors. Guests have smaller size, duration and editing limits than the owner. The owner has a priority queue and a reserved worker. | `routers/media.py`, `limits.py`, `worker/` |
| Publishing | Admin only. Destination accounts are the owner's social accounts, so guests never see or target them. | `routers/publishing.py` |
| Shared results | A visitor asking for a video another visitor fetched recently gets a private hard-linked copy. Only the public video and its metadata are shared, never who asked for it. | `jobs/cache.py` |
| Data minimization | Guest identities whose cookie has expired are deleted along with their jobs, files and history. Security logs are deleted after `AUDIT_RETENTION_DAYS`. | `jobs/cleanup.py` |
| File delivery | Nginx sends files only after the API authorizes the request (`X-Accel-Redirect` to an `internal` location). Nginx can read the media folder through the `videodl-media` group, but not the database or settings. | Nginx template, `install-server.sh` |
| Secure sessions | Random 256-bit token in an `HttpOnly; Secure; SameSite=Strict` cookie. The database stores only its SHA-256. 12 h absolute and 2 h idle expiry. Logout and password reset revoke sessions. | `security/sessions.py` |
| Brute-force protection | 5 failures lock the account for 15 minutes. Login is rate-limited in the app and in Nginx. Unknown usernames take the same time as known ones. | `routers/auth.py`, Nginx template |
| CSRF | Every state-changing request needs the `X-CSRF-Token` header matching the session, and the `Origin` must be in `ALLOWED_ORIGINS`. | `deps.py` |
| Rate limiting | Per-IP fixed windows in Redis: general API, analyze, login. Nginx adds its own limits. | `security/ratelimit.py` |
| File size, duration, timeouts | `MAX_FILESIZE_MB` is enforced on received bytes. `MAX_DURATION_SECONDS` is checked before download. Hard subprocess timeouts kill the whole process group. | `ytdlp_runner.py`, `ytdlp.py`, `ffmpeg.py` |
| Disk limits | New jobs are refused when the app quota (`MAX_STORAGE_MB`) is used up or the disk has less than `MIN_FREE_DISK_MB` free. | `media/storage.py` |
| Concurrent jobs | Per-user cap on queued and running jobs. Server-wide concurrency equals the number of worker processes. | `routers/media.py`, systemd |
| Safe temp directories | One work folder per job under `DATA_DIR/work`, removed after each job. Stale folders are swept by cleanup. Stored paths are resolved and must stay inside the storage root. | `jobs/tasks.py`, `media/storage.py` |
| Strict URL validation | http/https only, ports 80/443, no credentials or backslashes, no IP literals (including decimal/hex forms), no `localhost`/`.internal`/`metadata.*`, and a domain allowlist. Optionally, other sites only with a dedicated yt-dlp extractor (never the generic one). | `security/url_guard.py` |
| SSRF and cloud metadata blocking | Every resolved address must be globally routable. 10/8, 172.16/12, 192.168/16, 127/8, 169.254/16 (AWS/GCP/Azure/DO metadata), 100.64/10 (Alibaba metadata), `fd00:ec2::254`, IPv4-mapped/6to4/Teredo/NAT64 wrappers and more are blocked. | `security/ip_policy.py` |
| DNS rebinding | Short-link expansion connects to the exact IP that passed the check. Inside the yt-dlp process, `socket.connect` itself is guarded, so the address actually connected to is checked every time. Unix sockets are blocked. | `url_guard.py`, `net_guard.py` |
| No arbitrary command execution | Every subprocess uses an argument list, never a shell. User input never becomes a yt-dlp format string: only `format_id`s from the analysis are accepted. | `ytdlp.py`, `ffmpeg.py`, `routers/media.py` |
| No arbitrary server-side fetching | yt-dlp's generic extractor is disabled, environment proxies are ignored, config files and cookies are not loaded, and solver code is never downloaded at runtime. | `ytdlp_runner.py` |
| Uploads | Watermarks must have a PNG signature and valid header, be at most 4096×4096 and at most 5 MB. They are stored under random names. | `routers/assets.py` |
| HTTPS | Certbot plus Nginx. `SESSION_COOKIE_SECURE=true` is enforced in production. HSTS can be enabled after HTTPS works. | `docs/DEPLOYMENT.md` |
| Secrets | Only in `/etc/video-downloader/video-downloader.env` (root:videodl 0640). `.gitignore` and the release builder refuse `.env`, keys and cookie files. | `.gitignore`, `build-release.sh` |
| Audit logging | Logins (including failures), analyze, download, file download, delete, process, presets, watermarks and publishing actions, with IP and user agent. | `audit.py` |
| Least privilege on the server | The app runs as `videodl` with no shell and can only write `/var/lib/video-downloader`. Code is root-owned and read-only. The deploy user can only run the deploy and rollback commands. | `deploy/systemd`, `deploy/sudoers` |

## Content policy built into the code

* Private, login-only, age-gated, members-only, paywalled and DRM-protected content is
  refused with an explanation. No cookies or credentials are ever passed to yt-dlp.
* Captions are copied exactly. If none exist the UI says "Caption unavailable" and never
  generates one.
* Processing never crops the original frame, so existing creator watermarks stay visible.
* Publishing requires explicit approval and is disabled unless an administrator enables it.

## Known limits

* yt-dlp may start helper processes for YouTube: a JavaScript runtime (Deno, which has no
  network permission by default, or Node with `--permission`) and FFmpeg for merging
  local files. Those processes don't inherit the Python socket guard. HLS is downloaded
  natively in Python so that FFmpeg never fetches URLs.
* If Cloudflare or another proxy sits in front of Nginx, configure `real_ip_header`. Otherwise
  every visitor appears to come from the proxy's address, and rate limits apply to everyone together.
* Keep yt-dlp updated (see README). Platform changes break extractors regularly.

## Reporting

Check `audit_logs` and `journalctl -u 'video-downloader-*'`. Rotate a password with
`sudo video-downloader-cli reset-password <name>`, which also signs out every session.
