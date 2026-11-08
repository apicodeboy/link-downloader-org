# Worker

`run_worker.py` starts an [RQ](https://python-rq.org) worker that listens on the Redis
queue named by `QUEUE_NAME` and runs `app.jobs.tasks.run_job` for each job.

* The worker reuses the backend code in `../backend` (same virtualenv, same settings).
* It must run with the same working directory and environment as the API so both see the
  same database and `DATA_DIR`. Set `VD_WORKDIR` to force a working directory.
* Each job runs yt-dlp in a separate, time-limited, network-guarded process
  (`app/media/ytdlp_runner.py`) and FFmpeg as a separate process.
* One worker process = one job at a time. Concurrency = number of worker processes.
* Admin (site owner) jobs go to the `<QUEUE_NAME>-priority` queue. Every worker checks it
  first, and the `owner` instance (`WORKER_INSTANCE=owner`) serves only that queue.

Local run (from the `backend` folder):

```bash
.venv/bin/python ../worker/run_worker.py
```

On the server it runs as the systemd template unit `video-downloader-worker@N.service`.
