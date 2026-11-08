"""Redis-backed job queue (RQ). The database is the source of truth for job state;
Redis only carries "please run job X" messages to the worker processes."""
from __future__ import annotations

from typing import Protocol

from ..config import Settings, get_settings


def priority_queue_name(name: str) -> str:
    return f"{name}-priority"


class JobQueue(Protocol):
    def enqueue(self, job_id: str, timeout: int, priority: bool = False) -> str | None: ...
    def ping(self) -> bool: ...
    def depth(self) -> int | None: ...


class RQJobQueue:
    def __init__(self, settings: Settings | None = None):
        from redis import Redis
        from rq import Queue

        s = settings or get_settings()
        self.redis = Redis.from_url(s.redis_url, socket_connect_timeout=3, socket_timeout=10)
        self.queue = Queue(s.queue_name, connection=self.redis)
        # Admin jobs go to a separate lane that every worker checks first, and that the
        # dedicated "owner" worker serves exclusively.
        self.priority_queue = Queue(priority_queue_name(s.queue_name), connection=self.redis)

    def enqueue(self, job_id: str, timeout: int, priority: bool = False) -> str | None:
        from rq import Callback

        job = (self.priority_queue if priority else self.queue).enqueue_call(
            "app.jobs.tasks.run_job",
            args=(job_id,),
            timeout=timeout + 120,  # hard ceiling above our own subprocess timeouts
            result_ttl=3600,
            failure_ttl=7 * 86400,
            job_id=f"vd-{job_id}",
            on_failure=Callback("app.jobs.tasks.on_rq_failure"),
        )
        return job.id

    def ping(self) -> bool:
        try:
            return bool(self.redis.ping())
        except Exception:
            return False

    def depth(self) -> int | None:
        try:
            return self.queue.count + self.priority_queue.count
        except Exception:
            return None


class InlineQueue:
    """Test/dev queue: records jobs and optionally runs them in-process immediately."""

    def __init__(self, run: bool = False):
        self.run = run
        self.enqueued: list[str] = []
        self.priority: list[str] = []

    def enqueue(self, job_id: str, timeout: int, priority: bool = False) -> str | None:
        self.enqueued.append(job_id)
        if priority:
            self.priority.append(job_id)
        if self.run:
            from .tasks import run_job

            run_job(job_id)
        return f"inline-{job_id}"

    def ping(self) -> bool:
        return True

    def depth(self) -> int | None:
        return 0
