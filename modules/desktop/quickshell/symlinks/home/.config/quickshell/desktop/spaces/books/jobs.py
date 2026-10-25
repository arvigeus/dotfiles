"""Owned, bounded background jobs with cooperative cancellation and truthful progress."""

import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

_context = threading.local()


class Cancelled(ValueError):
    pass


class Job:
    def __init__(self, title):
        self.id = uuid.uuid4().hex
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.data: dict[str, Any] = {
            "job_id": self.id,
            "title": title,
            "state": "queued",
            "done": 0,
            "total": 0,
            "unit": "bytes",
            "detail": "Waiting…",
            "speed": 0,
            "eta": None,
        }

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled(
                self.data.get("cancel_message", "Cancelled. Completed files were kept.")
            )

    def update(self, **values):
        self.check()
        with self.lock:
            self.data.update(values)
            elapsed = time.monotonic() - self.started
            done, total = self.data["done"], self.data["total"]
            speed = done / elapsed if elapsed > 0.5 else 0
            self.data["speed"] = speed
            self.data["eta"] = (total - done) / speed if speed and total >= done else None

    def snapshot(self):
        with self.lock:
            return dict(self.data)


def current_job():
    return getattr(_context, "job", None)


def check_cancelled():
    if job := current_job():
        job.check()


def progress(**values):
    if job := current_job():
        job.update(**values)


class Jobs:
    def __init__(self, errors=(ValueError,)):
        self.errors = errors
        self.lock = threading.Lock()
        self.jobs = OrderedDict()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="transfer")

    def start(self, title, action):
        with self.lock:
            active = [j for j in self.jobs.values() if j.data["state"] in ("queued", "running")]
            if len(active) >= 16:
                raise ValueError("The transfer queue is full. Wait for a transfer to finish.")
            for key in list(self.jobs):
                if len(self.jobs) < 32:
                    break
                if self.jobs[key].data["state"] not in ("queued", "running"):
                    del self.jobs[key]
            job = Job(title)
            self.jobs[job.id] = job
        self.executor.submit(self.execute, job, action)
        return {"job_id": job.id}

    def execute(self, job, action):
        _context.job = job
        try:
            job.started = time.monotonic()
            job.update(state="running", detail="Preparing…")
            result = action()
            # A completed commit wins over cancellation arriving just afterwards.
            with job.lock:
                job.data.update(state="finished", result=result, detail="Completed", eta=0)
        except Cancelled as error:
            with job.lock:
                job.data.update(state="cancelled", error=str(error), eta=None)
        except Exception as error:
            # Network providers sanitize their errors before they reach this boundary.
            message = (
                str(error)
                if isinstance(error, self.errors)
                else "The operation failed. Check your connection and permissions."
            )
            with job.lock:
                job.data.update(state="failed", error=message, eta=None)
        finally:
            _context.job = None

    def snapshots(self):
        with self.lock:
            return {"jobs": [job.snapshot() for job in self.jobs.values()]}

    def cancel(self, identifier):
        with self.lock:
            job = self.jobs.get(identifier)
            if job is None:
                raise ValueError("That transfer is no longer available.")
            if job.data["state"] in ("queued", "running"):
                job.cancelled.set()
                with job.lock:
                    job.data.update(detail="Cancelling…", cancel_requested=True)
        return {}

    def stop(self):
        with self.lock:
            for job in self.jobs.values():
                job.cancelled.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
