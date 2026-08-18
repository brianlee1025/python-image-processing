"""A thread pool with a hard admission limit.

Rendering a card is CPU and memory heavy, so the service must never accept more
work than it can hold. `ThreadPoolExecutor` on its own has an unbounded queue:
a burst of users would be accepted, queue for a minute and time out anyway,
having already paid for the memory. A semaphore in front of it caps the total
number of accepted jobs at `workers + queue_size`. Past that point callers are
rejected immediately, which is what lets the Kafka bridge stop consuming and
the HTTP API answer 503 instead of quietly falling behind.
"""

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from logging import getLogger
from typing import Any, TypeVar

logger = getLogger(__name__)

T = TypeVar("T")


class PoolFull(Exception):
    """The pool is saturated and refused the job."""


class RenderPool:
    def __init__(self, workers: int, queue_size: int, name: str = "render") -> None:
        if workers < 1:
            raise ValueError("workers must be at least 1")

        self.workers = workers
        self.capacity = workers + max(queue_size, 0)

        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=name)
        self._slots = threading.BoundedSemaphore(self.capacity)
        self._lock = threading.Lock()

        self._accepted = 0
        self._completed = 0
        self._failed = 0
        self._rejected = 0
        self._in_flight = 0

    def submit(self, func: Callable[..., T], *args: Any, wait: float = 0.0) -> "Future[T]":
        """Accept a job, or raise `PoolFull`.

        `wait` is how long the caller is willing to block for a free slot; the
        HTTP API gives it a few seconds so a short burst queues instead of
        failing, while the Kafka bridge passes 0 and pauses its partitions.
        """
        acquired = self._slots.acquire(timeout=wait) if wait > 0 else self._slots.acquire(blocking=False)
        if not acquired:
            with self._lock:
                self._rejected += 1
            raise PoolFull(f"All {self.capacity} render slots are busy")

        with self._lock:
            self._accepted += 1
            self._in_flight += 1

        try:
            future = self._executor.submit(func, *args)
        except RuntimeError:  # Pool already shut down.
            self._finish(failed=True)
            raise

        future.add_done_callback(self._on_done)
        return future

    def _on_done(self, future: "Future[Any]") -> None:
        self._finish(failed=future.cancelled() or future.exception() is not None)

    def _finish(self, failed: bool) -> None:
        with self._lock:
            self._in_flight -= 1
            if failed:
                self._failed += 1
            else:
                self._completed += 1
        self._slots.release()

    def has_capacity(self) -> bool:
        with self._lock:
            return self._in_flight < self.capacity

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "workers": self.workers,
                "capacity": self.capacity,
                "in_flight": self._in_flight,
                "available": self.capacity - self._in_flight,
                "accepted": self._accepted,
                "completed": self._completed,
                "failed": self._failed,
                "rejected": self._rejected,
            }

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)
