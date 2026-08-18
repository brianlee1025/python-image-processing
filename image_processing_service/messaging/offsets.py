"""Offset bookkeeping for out of order completion.

Requests are handed to a thread pool, so message 7 can finish before message 3.
Committing "the offset I just finished" would then skip 3 if the worker died in
between. This tracker only ever advances a partition to the lowest offset that
is still in flight, which keeps redelivery honest: at worst the backend sees a
card twice and drops the duplicate by `requestId`.
"""

from threading import Lock

# (topic, partition)
PartitionKey = tuple[str, int]


class OffsetTracker:
    def __init__(self) -> None:
        self._lock = Lock()
        self._in_flight: dict[PartitionKey, set[int]] = {}
        self._highest_done: dict[PartitionKey, int] = {}
        self._committed: dict[PartitionKey, int] = {}

    def start(self, partition: PartitionKey, offset: int) -> None:
        with self._lock:
            self._in_flight.setdefault(partition, set()).add(offset)

    def complete(self, partition: PartitionKey, offset: int) -> None:
        with self._lock:
            self._in_flight.get(partition, set()).discard(offset)
            current = self._highest_done.get(partition)
            if current is None or offset > current:
                self._highest_done[partition] = offset

    def abandon(self, partition: PartitionKey, offset: int) -> None:
        """Give an offset back without completing it, e.g. when the pool
        rejected the job and we are going to re-consume the message."""
        with self._lock:
            self._in_flight.get(partition, set()).discard(offset)

    def forget(self, partitions: list[PartitionKey]) -> None:
        """Drop state for revoked partitions."""
        with self._lock:
            for partition in partitions:
                self._in_flight.pop(partition, None)
                self._highest_done.pop(partition, None)
                self._committed.pop(partition, None)

    def committable(self) -> dict[PartitionKey, int]:
        """Next offset to consume per partition, for partitions that have moved
        since the last commit."""
        with self._lock:
            pending: dict[PartitionKey, int] = {}

            for partition in set(self._in_flight) | set(self._highest_done):
                in_flight = self._in_flight.get(partition)
                if in_flight:
                    position = min(in_flight)
                elif partition in self._highest_done:
                    position = self._highest_done[partition] + 1
                else:
                    continue

                if position > self._committed.get(partition, -1):
                    pending[partition] = position

            return pending

    def mark_committed(self, offsets: dict[PartitionKey, int]) -> None:
        with self._lock:
            for partition, offset in offsets.items():
                self._committed[partition] = offset

    def in_flight(self) -> int:
        with self._lock:
            return sum(len(offsets) for offsets in self._in_flight.values())
