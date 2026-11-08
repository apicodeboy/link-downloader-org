# Video Downloader

A self-hosted web app for downloading **public videos you're authorized to use**
from X/Twitter, Instagram, Facebook, TikTok, YouTube (incl. Shorts) and Reddit. It shows
the original caption, saves the video as MP4, can add your watermark and convert to 9:16,
and prepares posts for publishing.

> **Support varies by platform.** Sites change often, and some videos can't be fetched
> without logging in. This app **does not** bypass logins, private accounts, paywalls,
> age gates or DRM. It only works with content anyone can view publicly. Only download
> content you own or have permission to use.

## Who can use it

It's built to run as a **public site**. Visitors don't need an account: each browser
automatically gets its own private file list for 30 days, and nobody can see or delete
anyone else's files.

| | Guests (everyone) | You (the site owner) |
| --- | --- | --- |
| Sign-in | none | `/login` (not linked), "keep me signed in" for 30 days |
| Longest video | 20 min | 30 min |
| Largest file | 300 MB | 500 MB |
| Editing (watermark, 9:16) | videos up to 5 min | any length |
| Jobs at once | 3 | 5 |
| Files kept | 60 min | 24 h |
| Queue | normal | priority lane, plus a reserved worker; never refused when the site is busy |
| Publish page and your social accounts | hidden | yes |
| Activity page | own jobs, queue length | daily visitors, downloads, failure reasons, versions |

All numbers are settings (see the table below). Set `REQUIRE_LOGIN=true` to make the site
private instead.

## What you get

* **Dashboard.** Paste a link, click **Analyze Video**, and see the thumbnail, title,
  duration, creator and original caption, plus a **Copy Caption** button. Pick a
  resolution and click **Download MP4**. Status updates live: Queued → Analyzing →
  Downloading → Processing → Completed (or Failed, with a plain-English reason).
* **History.** Every download and export is listed, with preview, download, process,
  publish and delete buttons. Files are deleted from the server after 60 minutes by
  default. The history entry stays.
* **Process.** Add a PNG watermark in the bottom-right corner (size, opacity, margin),
  convert to 9:16 with a blurred or black background, and generate 3 thumbnails. Audio is
  preserved and the original frame is never cropped. Settings can be saved as presets.
* **Publish** (owner only). Pick a video, edit the prefilled caption, add hashtags, choose
  your accounts and approve. Then download a ready-to-upload package. Metricool support is prepared but off;
  see [docs/METRICOOL.md](docs/METRICOOL.md).
* **Jobs.** A live monitor with queue length, storage use and tool versions.
* **Fast repeat requests.** When several visitors ask for the same video, the result is
  shared, so it's instant for them and the server sends fewer requests to the platforms.
* **Phone friendly.** Visitors can install the site to their home screen. On Android it
  then appears in the share sheet: share a TikTok or Reel straight to the site. Links like
  `https://your-site/?url=<video link>` start automatically.
* **Queue position and Cancel** for waiting or downloading jobs, and **Try again** after
  temporary failures.
* **Terms**, **Privacy** and FAQ pages that pull the real limits and your contact address.
* Dark mode.

## How it fits together

| Part | What it does |
| --- | --- |
| **Frontend** (`frontend/`) | The website you click around in. Built with Next.js, TypeScript and Tailwind. |
| **API** (`backend/`) | The FastAPI server. It gives each browser its identity, validates links, creates jobs and serves files. |
| **Worker** (`worker/`) | Does the slow work in the background (analyze, download, process), so the website never freezes. |
| **Redis** | A small queue where the API leaves "job to do" notes for workers. |
| **SQLite** | The database file: users, jobs, files, history, presets, publishing drafts, audit log. |
| **yt-dlp** | The open-source tool ([github.com/yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp)) that understands each video site. |
| **FFmpeg** | The open-source video tool ([ffmpeg.org](https://ffmpeg.org)). It merges audio and video, makes MP4s, adds watermarks and creates thumbnails. |
| **Nginx** | The web server on your VPS. It sends visitors to the right part and handles HTTPS. |
| **systemd / PM2** | Keep everything running and restart it after crashes or reboots. |

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/API.md](docs/API.md) ·
[docs/SECURITY.md](docs/SECURITY.md) · [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

## Run it on your computer

You need Python 3.11 or newer, Node.js 20 or newer, FFmpeg and Redis. On a Mac with
Homebrew, `brew install python@3.12 node ffmpeg redis` installs all four. The
[uv](https://docs.astral.sh/uv/) tool is the easiest way to get Python.

```bash
# 1. Get the code
git clone https://github.com/<you>/video-downloader.git
cd video-downloader

# 2. Backend: create a private Python environment and install the packages
cd backend
uv venv --python 3.12 .venv                 # makes the .venv folder
uv pip install -r requirements-dev.txt       # installs FastAPI, yt-dlp, etc.

# 3. Settings for local use (plain http, so cookies can't be "Secure")
cp ../.env.example .env
#    then edit .env and set:
#      SESSION_COOKIE_SECURE=false
#      ALLOWED_ORIGINS=http://localhost:3010
#      REDIS_URL=redis://127.0.0.1:6379/0

# 4. Create the database (and, optionally, an admin account for /login)
.venv/bin/python -m app.cli init-db
.venv/bin/python -m app.cli create-admin admin     # optional; asks for a password

# 5. Frontend packages
cd ../frontend && npm install && cd ..

# 6. Start everything (Redis, API, worker, website). Ctrl+C stops it all.
scripts/dev.sh
```

Open **http://localhost:3010**. No sign-in is needed. The API docs are at
http://127.0.0.1:8010/api/docs.

### Run the tests

```bash
cd backend && .venv/bin/python -m pytest -q      # 192 tests; no internet needed
cd frontend && npm run typecheck && npm run build
```

The tests generate their own sample clips with FFmpeg and fake the network. They never
download from real platforms. To try the real thing end to end, use the Creative Commons
sample (Blender's *Big Buck Bunny*):

```bash
python3 scripts/smoke_test.py http://localhost:3010
```

## Settings (environment variables)

All settings are in [.env.example](.env.example), each with a comment. Locally, they go in
`backend/.env`. On the server they live in `/etc/video-downloader/video-downloader.env`.
Never commit either file. The ones you're most likely to change:

| Variable | Default | Meaning |
| --- | --- | --- |
| `CONTACT_EMAIL` | — | Shown on Terms and Privacy for questions and takedown requests. **Set this.** |
| `SITE_NAME` | `Video Downloader` | Name on the Terms and Privacy pages. For the header, also set the GitHub variable `SITE_NAME`. |
| `REQUIRE_LOGIN` | `false` | `false` = open to everyone, no sign-in. `true` = accounts only |
| `MAX_ACTIVE_JOBS_TOTAL` | `20` | Guest jobs queued or running across all visitors |
| `GUEST_MAX_DURATION_SECONDS` / `GUEST_MAX_FILESIZE_MB` | `1200` / `300` | Guest download limits |
| `GUEST_PROCESS_MAX_DURATION_SECONDS` | `300` | Longest video a guest can edit (editing uses a lot of CPU) |
| `RESULT_CACHE_MINUTES` | `30` | How long an analysis is shared with other visitors |
| `ALLOWED_ORIGINS` | — | The exact address you open the app at, e.g. `https://videos.example.com` |
| `RETENTION_MINUTES` | `60` | Minutes before downloaded and processed files are deleted |
| `MAX_FILESIZE_MB` | `500` | Largest video for you (admin) |
| `MAX_DURATION_SECONDS` | `1800` | Longest video for you (30 minutes) |
| `MAX_STORAGE_MB` | `5000` | Total disk space the app may use |
| `MIN_FREE_DISK_MB` | `2000` | Stop new jobs when the disk gets this full |
| `MAX_PENDING_JOBS_PER_USER` | `5` | Jobs a user can have queued or running at once |
| `DOWNLOAD_TIMEOUT_SECONDS` | `900` | A download is stopped after this long |
| `FFMPEG_THREADS` | `2` | CPU threads per FFmpeg job, so other sites stay fast |
| `ALLOW_OTHER_YTDLP_SITES` | `false` | Also allow other sites yt-dlp has a dedicated extractor for |
| `SESSION_COOKIE_SECURE` | `true` | Must be `true` in production (HTTPS) |

After changing the server file, restart:
`sudo systemctl restart video-downloader-api 'video-downloader-worker@*'`.

## Deploy on your Ubuntu VPS

Full guide: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**. In short:

1. `sudo bash scripts/server-inspect.sh`. A read-only report of what's on the server.
2. `sudo bash scripts/install-server.sh --domain videos.yourdomain.com`. One-time setup.
   It never touches your other sites.
3. Add a DNS A record, then `sudo certbot --nginx -d videos.yourdomain.com` for HTTPS.
4. Push to GitHub (automatic deploy), or build and deploy by hand.
5. Optional: `sudo video-downloader-cli create-admin yourname` for the hidden `/login` admin view.

Undo at any time with `sudo video-downloader-rollback` (previous version) or
`sudo video-downloader-rollback --disable` (switch the app off).

## Running it as a public site

1. **Set `CONTACT_EMAIL`** in the server settings file. The Terms page tells rights holders
   to use it for takedown requests, so use an address you check.
2. **Read the Terms and Privacy pages** at `/terms` and `/privacy`. They are a sensible
   starting point written for how this app actually behaves, not legal advice. Have them
   checked for your country, then edit `frontend/app/(public)/`.
3. **Merge yt-dlp updates promptly.** Dependabot checks daily and opens a pull request.
   CI tests it, and merging deploys it. An outdated yt-dlp is the most common reason
   downloads start failing.
4. **Check Activity now and then** (signed in as owner). Many `rate_limited` failures mean
   a platform is throttling your server's IP. Lower `MAX_ACTIVE_JOBS_TOTAL` or the worker
   count for a while.
5. **Using Cloudflare?** Enable the real-IP lines in the Nginx site (see
   [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#nginx-details)). Otherwise every visitor shares
   one rate limit.
6. **Name it.** Set `SITE_NAME` in the settings file and as a GitHub Actions variable
   (Settings → Secrets and variables → Actions → Variables), so the header matches.

## Connect to GitHub

See [docs/DEPLOYMENT.md#connecting-github](docs/DEPLOYMENT.md#connecting-github). In short:

1. Create an empty private repository.
2. Run `git remote add origin …` and `git push -u origin main`.
3. Add the four `VPS_*` secrets. Deploys start after that.

## Configure Nginx and HTTPS

The installer writes one new site file from
[deploy/nginx/video-downloader.conf.template](deploy/nginx/video-downloader.conf.template).
Certbot adds HTTPS to that file only. Both steps are in
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#step-3-dns-and-https).

## Monitor jobs

* **In the app:** the **Jobs** page shows running, finished and failed jobs, queue length,
  storage and versions. It refreshes every 3 seconds.
* **On the server:**
  * `journalctl -u 'video-downloader-*' -f` shows the live logs.
  * `systemctl status 'video-downloader-*'` shows whether everything is up.
  * `curl -s localhost:8010/api/health` checks the database, queue and FFmpeg.

## Troubleshooting failed downloads

The error message tells you what happened. Common ones:

| Message | Why | What to do |
| --- | --- | --- |
| *The platform requires a login…* / *This content is private* | Not public | Nothing. This app won't bypass logins. |
| *DRM-protected* / *paywall* / *age-restricted* | Protected content | Not supported, by design. |
| *rate-limiting the server* | The platform is throttling your server's IP | Wait, then try again. If it keeps happening, lower `MAX_ACTIVE_JOBS_TOTAL` or the number of workers. |
| *The server is busy* | `MAX_ACTIVE_JOBS_TOTAL` guest jobs are already running | Visitors try again shortly. Raise it only if the VPS has spare CPU. |
| *The platform changed something…* / *Unable to extract* | yt-dlp needs an update | [Update yt-dlp](#update-yt-dlp-safely). |
| *isn't a supported site* | Domain not on the allowlist | Use the post's direct link, or see `ALLOW_OTHER_YTDLP_SITES`. |
| *Blocked for security* | The link points to a private or internal address | Working as intended. |
| *larger than the size limit* / *longer than the limit* | Over `MAX_FILESIZE_MB` / `MAX_DURATION_SECONDS` | Pick a lower resolution, or raise the limit. |
| *storage quota is full* / *low on disk* | Disk limits reached | Delete files in History, or wait for cleanup. |
| *job queue is unavailable* | Redis or the worker is down | `systemctl status redis-server 'video-downloader-worker@*'` |
| Stuck on *Queued* | No worker running | `sudo systemctl restart 'video-downloader-worker@*'` |
| YouTube shows few formats | No JavaScript runtime | Reinstall with `--with-deno`, or make sure Node is in the worker's PATH |

Administrators see **Technical details** under a failed job. That's yt-dlp's own log,
which is useful for bug reports.

## Update yt-dlp safely

Platforms change often, so yt-dlp ships fixes frequently. **Dependabot opens a pull request
for each new yt-dlp release automatically.** Merge it once CI is green, and it deploys.
To update by hand instead, go through Git so the update is tested and can be rolled back:

```bash
cd backend
uv pip compile requirements.in -o requirements.txt --upgrade-package yt-dlp --upgrade-package yt-dlp-ejs
uv pip compile requirements-dev.in -o requirements-dev.txt
uv pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q                         # must pass
python3 ../scripts/smoke_test.py http://localhost:3010   # real check
git commit -am "Update yt-dlp" && git push            # CI tests, then deploys
```

If the new version misbehaves on the server, `sudo video-downloader-rollback` returns to
the previous release (with the previous yt-dlp) within seconds.

Avoid running `pip install -U yt-dlp` directly on the server. It bypasses the tests and
can't be rolled back.

## Project layout

```
video-downloader/
├── frontend/            Next.js dashboard
├── backend/             FastAPI app, models, yt-dlp/FFmpeg integration, tests, migrations
├── worker/              background worker entry point
├── scripts/             inspect, install, build, deploy, rollback, smoke test, dev launcher
├── deploy/              systemd, Nginx, PM2 and sudoers templates
├── docs/                architecture, API, security, deployment, Metricool notes
├── .github/workflows/   CI, server install test, deploy
├── .env.example         every setting, documented
└── README.md
```

## Credits

[yt-dlp](https://github.com/yt-dlp/yt-dlp) (Unlicense) and [FFmpeg](https://github.com/FFmpeg/FFmpeg)
(LGPL/GPL) do the heavy lifting. They are installed from their official releases and are
not bundled in this repository.
