"""Tests for offset bookkeeping under out of order completion."""

from image_processing_service.messaging.offsets import OffsetTracker

PARTITION = ("image-render-requests", 0)


def test_nothing_to_commit_before_anything_completes():
    tracker = OffsetTracker()
    tracker.start(PARTITION, 0)

    assert tracker.committable() == {PARTITION: 0}


def test_commits_past_a_completed_run():
    tracker = OffsetTracker()
    for offset in range(3):
        tracker.start(PARTITION, offset)
        tracker.complete(PARTITION, offset)

    assert tracker.committable() == {PARTITION: 3}


def test_does_not_commit_past_an_unfinished_message():
    """Offset 5 finishing first must not skip 3: a crash here has to replay 3,
    not lose it."""
    tracker = OffsetTracker()
    for offset in (3, 4, 5):
        tracker.start(PARTITION, offset)

    tracker.complete(PARTITION, 5)
    tracker.complete(PARTITION, 4)
    assert tracker.committable() == {PARTITION: 3}

    tracker.complete(PARTITION, 3)
    assert tracker.committable() == {PARTITION: 6}


def test_committed_offsets_are_not_repeated():
    tracker = OffsetTracker()
    tracker.start(PARTITION, 0)
    tracker.complete(PARTITION, 0)

    pending = tracker.committable()
    tracker.mark_committed(pending)

    assert tracker.committable() == {}


def test_abandoned_offsets_are_reconsumed():
    tracker = OffsetTracker()
    tracker.start(PARTITION, 7)
    tracker.abandon(PARTITION, 7)

    assert tracker.committable() == {}
    assert tracker.in_flight() == 0


def test_partitions_are_tracked_independently():
    other = ("image-render-requests", 1)
    tracker = OffsetTracker()

    tracker.start(PARTITION, 0)
    tracker.start(other, 10)
    tracker.complete(other, 10)

    assert tracker.committable() == {PARTITION: 0, other: 11}


def test_revoked_partitions_are_forgotten():
    tracker = OffsetTracker()
    tracker.start(PARTITION, 4)
    tracker.complete(PARTITION, 4)

    tracker.forget([PARTITION])

    assert tracker.committable() == {}
