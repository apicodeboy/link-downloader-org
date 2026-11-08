# API reference

Base path `/api`. All bodies are JSON unless noted. Errors look like this:

```json
{ "detail": { "code": "unsupported_site", "message": "example.com is not a supported site. ..." } }
```

**Identity.** Call `GET /api/auth/me` first. In open mode (`REQUIRE_LOGIN=false`, the
default) it creates a guest identity for a new browser, sets an `HttpOnly` cookie and
returns a `csrf_token`. In login mode it returns `401` until `POST /api/auth/login`
succeeds. Every `POST`, `PUT`, `PATCH` and `DELETE` must send `X-CSRF-Token: <token>`.
Without a session cookie, every endpoint except `/api/health`, `/api/auth/me` and
`/api/auth/login` returns `401`. Each identity sees only its own jobs and files.

In development, interactive docs are at `http://127.0.0.1:8010/api/docs`. They are
disabled in production.

## Auth

| Method | Path | Body | Notes |
| --- | --- | --- | --- |
| POST | `/api/auth/login` | `{"username","password","remember"?}` | 200 `{user, csrf_token, expires_at}`. 401 wrong credentials. 429 locked or rate-limited. |
| POST | `/api/auth/logout` | | Revokes the session. |
| GET | `/api/auth/me` | | Current identity, CSRF token, `mode` (`open` or `login`) and this identity's `limits`. In open mode it creates a guest identity on first visit (429 after 20 per IP per hour). |

## Media

| Method | Path | Body | Result |
| --- | --- | --- | --- |
| POST | `/api/media/analyze` | `{"url": "https://x.com/…"}` | 202 job (`kind: "analyze"`). It may already be `completed`, with `result.cached: true`, if someone fetched the same video recently. 400 with a reason if the URL is rejected. 429 `too_many_jobs` (per visitor) or `server_busy` (server-wide). 503 queue down. |
| POST | `/api/media/download` | `{"analysis_job_id", "format_id"}` | 202 job (`kind: "download"`). `format_id` must be one the analysis returned, or `"best"`. 507 if storage is full. |
| GET | `/api/jobs/{id}` | | Job status (see below), including `queue_position` while queued. |
| POST | `/api/jobs/{id}/cancel` | | Cancels a queued job, or stops a download in progress. 409 for other steps. |
| GET | `/api/jobs?status=active\|completed\|failed&limit=50` | | Recent jobs. |
| GET | `/api/media/{id}` | | File details, generated `children` (thumbnails), and `source` (original caption, hashtags, creator). |
| GET | `/api/media/{id}/file` | | The file itself. Supports `Range` for seeking. `?download=1` returns it as an attachment. 410 once expired. |
| GET | `/api/media/history?limit=50&offset=0` | | Download and processing history, including expired items. |
| DELETE | `/api/media/{id}` | | Deletes the file and its thumbnails now. The history row is kept. |
| POST | `/api/media/{id}/process` | see below | 202 job (`kind: "process"`). |

Process body. Either `preset_id`, or any of these options:

```json
{
  "aspect": "9:16",            // or "original"
  "fill_mode": "blur",         // or "black"; the original frame is never cropped
  "watermark_file_id": "…",    // from POST /api/watermarks
  "watermark_size_pct": 15,    // 2–50, % of video width
  "watermark_opacity": 0.8,    // 0.05–1
  "watermark_margin_pct": 3,   // 0–20
  "thumbnails": true
}
```

### Job object

```json
{
  "id": "4f1c…", "kind": "download", "status": "downloading",
  "progress": 0.42, "stage": "Downloading (12.3 MB)",
  "source_url": "https://…", "platform": "tiktok",
  "result": null,
  "error": null,
  "created_at": "2026-11-08T18:20:11+00:00", "started_at": "…", "finished_at": null
}
```

`status` is one of `queued`, `analyzing`, `downloading`, `processing`, `completed` or `failed`.

A completed **analyze** job's `result` has `title`, `title_is_generated`, `caption` (or
`null`), `caption_source`, `description`, `hashtags`, `creator`, `duration`, `formats[]`,
`thumbnail_file_id`, `too_long` and `platform`.

A completed **download** job's `result` has `media_file_id`, `filename`, `size_bytes`,
`width`, `height`, `vcodec`, `acodec`, `has_audio` and `expires_at`.

## Watermarks and presets

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/api/watermarks` | multipart field `file`. PNG only, at most 5 MB and 4096×4096. Kept until deleted. |
| GET | `/api/watermarks` | |
| DELETE | `/api/watermarks/{id}` | |
| GET / POST | `/api/presets` | Body is the process options plus `name`. |
| PUT / DELETE | `/api/presets/{id}` | |

## Publishing (admin only)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/publishing/config` | Provider, whether submitting is enabled, and destination accounts. |
| POST | `/api/publishing/check` | Admin only. Read-only connection test. |
| GET / POST | `/api/publishing/jobs` | Create: `{media_file_id, caption, hashtags[], destinations[], scheduled_at?}`. |
| PATCH | `/api/publishing/jobs/{id}` | Edit. Removes any approval. |
| POST | `/api/publishing/jobs/{id}/approve` | Needs at least one destination. |
| POST | `/api/publishing/jobs/{id}/cancel` | |
| POST | `/api/publishing/jobs/{id}/submit` | Admin only. Needs approval and `PUBLISHING_SUBMIT_ENABLED=true`. Returns 501 until a verified provider exists. |
| GET | `/api/publishing/jobs/{id}/package` | ZIP containing the MP4 and `caption.txt`. |

## Health and status

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/health` | Public. `{"status":"ok"\|"degraded","checks":{"database","queue","ffmpeg"}}` |
| GET | `/api/site` | Public, no identity needed. Site name, contact email, platforms and guest limits (used by FAQ, Terms and Privacy). |
| GET | `/api/status` | Any visitor. Queue depth, running jobs, storage percentage, limits. |
| GET | `/api/admin/status` | Admin only. Versions, queue depth, job counts, storage use, `last_24h` (visitors, downloads, cache hits, failures by reason), recent failures and audit events. |
