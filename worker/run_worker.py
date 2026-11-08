"""Background worker: pulls job IDs from the Redis queue and runs them.

    cd backend && ../backend/.venv/bin/python ../worker/run_worker.py

Run several copies (systemd `video-downloader-worker@1`, `@2`, ...) to process jobs in
parallel; the number of copies is the server-wide concurrent job limit.
"""
from __future__ import annotations

import logging
import os
import socket
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
if os.environ.get("VD_WORKDIR"):
    os.chdir(os.environ["VD_WORKDIR"])


def main() -> None:
    from redis import Redis
    from rq import Queue, SimpleWorker, Worker

    from app.config import get_settings
    from app.db import init_engine

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = get_settings()
    s.ensure_dirs()
    init_engine(s.database_url)
    redis = Redis.from_url(s.redis_url)
    queue = Queue(s.queue_name, connection=redis)
    # macOS can't safely fork after loading some system libraries; use the non-forking
    # worker there (heavy work already runs in separate yt-dlp/FFmpeg processes).
    simple = os.environ.get("WORKER_CLASS", "simple" if sys.platform == "darwin" else "fork") == "simple"
    cls = SimpleWorker if simple else Worker
    instance = os.environ.get("WORKER_INSTANCE", str(os.getpid()))
    worker = cls([queue], connection=redis, name=f"vd-{socket.gethostname()}-{instance}-{os.getpid()}")
    worker.work(with_scheduler=False, logging_level="INFO")


if __name__ == "__main__":
    main()
