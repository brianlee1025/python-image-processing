"""Tests for the bounded worker pool."""

import threading
import time

import pytest

from image_processing_service.services.pool import PoolFull, RenderPool


@pytest.fixture
def pool():
    instance = RenderPool(workers=2, queue_size=1)
    yield instance
    instance.shutdown(wait=False)


def test_runs_work_and_returns_results(pool):
    assert pool.submit(lambda value: value * 2, 21).result(timeout=5) == 42


def test_rejects_once_every_slot_is_taken(pool):
    """Two workers plus one queue slot means the fourth caller is turned away
    immediately rather than queued behind a growing backlog."""
    release = threading.Event()
    futures = [pool.submit(release.wait, 5) for _ in range(pool.capacity)]

    with pytest.raises(PoolFull):
        pool.submit(release.wait, 5)

    assert pool.has_capacity() is False

    release.set()
    for future in futures:
        future.result(timeout=5)

    assert pool.stats()["rejected"] == 1
    assert pool.has_capacity() is True


def test_slots_are_released_after_failures(pool):
    def boom():
        raise ValueError("nope")

    for _ in range(pool.capacity + 2):
        future = pool.submit(boom)
        with pytest.raises(ValueError):
            future.result(timeout=5)

    stats = pool.stats()
    assert stats["failed"] == pool.capacity + 2
    assert stats["in_flight"] == 0
    assert stats["rejected"] == 0


def test_waiting_callers_get_a_slot_when_one_frees_up(pool):
    release = threading.Event()
    futures = [pool.submit(release.wait, 5) for _ in range(pool.capacity)]
    threading.Timer(0.1, release.set).start()

    started = time.perf_counter()
    assert pool.submit(lambda: "queued", wait=5).result(timeout=5) == "queued"
    assert time.perf_counter() - started >= 0.05

    for future in futures:
        future.result(timeout=5)


def test_never_runs_more_than_the_worker_count_at_once():
    pool = RenderPool(workers=3, queue_size=10)
    peak = 0
    running = 0
    lock = threading.Lock()

    def job():
        nonlocal peak, running
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.02)
        with lock:
            running -= 1

    futures = [pool.submit(job) for _ in range(13)]
    for future in futures:
        future.result(timeout=10)
    pool.shutdown()

    assert peak <= 3
