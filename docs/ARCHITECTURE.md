# Architecture

```
 Browser ──HTTPS──> Nginx ──/api/*──> FastAPI (uvicorn, 127.0.0.1:8010) ──┐
   (phone/PC)        │                    │  sessions, CSRF, rate limits    │
                     │                    │  writes jobs to SQLite          │ RQ job IDs
                     └──/*──> Next.js UI  │                                 ▼
                         (PM2, :3010)     │                               Redis
                                          ▼                                 │
                                   SQLite database  <──── Worker(s) <───────┘
                                   (jobs, files,          │  1 job at a time each
                                    history, audit)       ├─> yt-dlp runner process (network-guarded)
                                                          └─> FFmpeg / ffprobe processes
                                   /var/lib/video-downloader/media  (auto-deleted after 60 min)
```

## Components

| Folder | What it is | Runs as |
| --- | --- | --- |
| `frontend/` | Next.js 16 dashboard (App Router, TypeScript, Tailwind v4). Pure client UI that calls the API. | PM2 (`pm2-runtime`) inside `video-downloader-web.service` |
| `backend/app/` | FastAPI API: auth, URL checks, job creation, file serving, presets, publishing | `video-downloader-api.service` |
| `worker/` | RQ worker that runs jobs from Redis | `video-downloader-worker@N.service` |
| `backend/app/media/ytdlp_runner.py` | Separate process that runs yt-dlp with the socket guard installed | started by the worker per job |
| `backend/app/jobs/cleanup.py` | Deletes expired media, stale work folders and stuck jobs | `video-downloader-cleanup.timer` (every 5 min) |
| `deploy/` | systemd units, Nginx template, PM2 file, sudoers rule | |
| `scripts/` | inspection, install, build, deploy, rollback, smoke test, dev launcher | |

## A download, step by step

1. **Analyze**. `POST /api/media/analyze` validates the URL (scheme, port, host
   allowlist, no IPs or credentials) and stores a `queued` job. Redis tells a worker.
2. The worker marks it `analyzing` and expands short links (t.co, vm.tiktok.com…) one hop
   at a time. Every hop is re-validated and pinned to a checked public IP.
3. The worker starts `ytdlp_runner` as a child process. The runner first patches
   `socket.connect` so every connection is checked against the public-IP policy. Then
   yt-dlp reads metadata and the thumbnail, with the generic page extractor disabled.
4. Captions, hashtags and creator info are parsed (`media/captions.py`), and formats are
   grouped by resolution (`media/formats.py`). The job becomes `completed`.
5. **Download**. `POST /api/media/download` accepts only a `format_id` that the analysis
   offered. The worker sets `downloading`, and yt-dlp downloads and merges audio and video
   with FFmpeg, while a hook enforces the size cap on the bytes received.
6. `processing`. FFmpeg remuxes to MP4 (`+faststart`) or re-encodes if the codecs don't
   fit MP4. A `MediaFile` row records the path and `expires_at = now + RETENTION_MINUTES`.
7. The UI polls `GET /api/jobs/{id}`, shows the preview, and links to
   `GET /api/media/{id}/file`, which only serves the file to the identity that created it, and supports seeking.
8. The cleanup timer deletes the file after the retention period. The history row stays.

## Public-site features

* **Two queues.** Admin jobs go to `<QUEUE_NAME>-priority`, which every worker checks first.
  `video-downloader-worker@owner` serves only that queue, so the owner always has a free worker.
* **Shared results** (`jobs/cache.py`). Links are normalized (tracking parameters such as
  `?si=`, `?igsh=` and `utm_*` removed, `twitter.com` treated as `x.com`). A matching analysis
  from the last `RESULT_CACHE_MINUTES` is copied into a new job for the visitor. A matching
  download, with the same format and at least 5 minutes left, is hard-linked into the
  visitor's own folder. Each copy expires on its own schedule, and storage counts shared
  copies once.
* **Per-role limits** (`limits.py`). These are applied when a job is created and stored in its options.
* **Cancellation.** Queued jobs are marked cancelled immediately. Running downloads set
  `cancel_requested`. The worker checks it every second and kills the yt-dlp process.
* **File delivery.** The API authorizes, then Nginx sends the file via `X-Accel-Redirect`.

## Database

SQLAlchemy 2 models in `backend/app/models.py` and Alembic migrations in `backend/alembic/`.

| Table | Purpose |
| --- | --- |
| `users` | admin accounts (scrypt password hashes, lockout counters) and automatic per-browser guest identities |
| `user_sessions` | server-side sessions (SHA-256 of the cookie token, CSRF token, expiry) |
| `media_jobs` | every analyze, download and process job: status, progress, stage, options, result, error, timestamps |
| `media_files` | files on disk: kind, relative path, size, codecs, `expires_at`, `deleted_at` |
| `download_history` | permanent record of downloads and exports, kept after files expire |
| `processing_presets` | saved watermark and 9:16 settings |
| `publishing_jobs` | caption, hashtags, destinations, approval state |
| `audit_logs` | logins, downloads, deletions, processing, publishing actions, with IP and user agent |

### Moving to PostgreSQL later

1. `pip install "psycopg[binary]"` (add it to `requirements.in`).
2. Create the database and set `DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1/videodl`.
3. `python -m app.cli init-db` creates the tables through Alembic.
4. Copy data across, for example with `pgloader` from the SQLite file.

No code changes are needed. All queries go through SQLAlchemy, and the timezone-aware
datetime type works on both databases.

## Job statuses

`queued → analyzing → completed` for analysis, `queued → downloading → processing → completed`
for downloads, and `queued → processing → completed` for processing. Any step can end in
`failed`, with an `error.code` and a human-readable `error.message`. The technical
`error_detail` is only shown to administrators.
