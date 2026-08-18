"""Kafka side of the share card service.

Shape of the flow:

    playbook-be --(image-render-requests)--> bridge --> render pool
    playbook-be <--(image-render-results)--- bridge <-- render pool

Backpressure is the point of this module. The bridge only consumes while the
render pool has a free slot; when the pool fills up it pauses its partitions,
so unserved requests stay in Kafka - durable, ordered and visible as consumer
lag - instead of piling up in this process. Offsets are committed only after a
result has actually been delivered back to the backend.
"""

import json
import time
from concurrent.futures import Future
from functools import partial
from logging import getLogger
from pathlib import Path
from threading import Event
from typing import Any

from confluent_kafka import Consumer, KafkaError, Message, Producer, TopicPartition

from ..conf.kafka import KafkaSettings
from ..schemas.cards import RenderRequest, RenderResult
from ..services.pool import PoolFull, RenderPool
from ..services.share_cards import get_render_pool, submit_render
from ..settings import settings
from .offsets import OffsetTracker, PartitionKey

logger = getLogger(__name__)

# How long a single produce may keep retrying its local queue before we give up
# on the result. The backend's own request timeout is the real deadline.
PRODUCE_RETRY_SECONDS = 5.0


def build_consumer(config: KafkaSettings) -> Consumer:
    return Consumer(config.consumer_config())


def build_producer(config: KafkaSettings) -> Producer:
    return Producer(config.producer_config())


class KafkaBridge:
    """Consumes render requests and produces rendered cards.

    The consumer, producer and pool are injected so tests can drive the loop
    with fakes and no broker.
    """

    def __init__(
        self,
        consumer: Consumer,
        producer: Producer,
        config: KafkaSettings | None = None,
        pool: RenderPool | None = None,
    ) -> None:
        self._consumer = consumer
        self._producer = producer
        self._config = config or settings
        self._pool = pool or get_render_pool()
        self._offsets = OffsetTracker()
        self._paused = False
        self._last_commit = 0.0
        self._fatal = Event()
        self._last_heartbeat = 0.0

    def run(self, stop: Event | None = None) -> None:
        """Consume until `stop` is set. Blocking; call it from the main thread
        so signal handlers can set the event."""
        stop = stop or Event()
        topic = self._config.kafka_request_topic

        self._consumer.subscribe([topic], on_assign=self._on_assign, on_revoke=self._on_revoke)
        logger.info(
            "Bridge listening on %s, replying on %s, %d render slots",
            topic,
            self._config.kafka_result_topic,
            self._pool.capacity,
        )

        try:
            while not stop.is_set() and not self._fatal.is_set():
                self._write_heartbeat()
                # Serves delivery callbacks, which is what advances offsets.
                self._producer.poll(0)
                self._commit_if_due()

                if not self._pool.has_capacity():
                    self._pause()
                    # Still polling: paused partitions return nothing but the
                    # consumer keeps its group membership.
                    self._consumer.poll(0.1)
                    continue

                self._resume()
                message = self._consumer.poll(0.5)
                if message is not None:
                    self._handle(message)
        finally:
            self._drain()

    def _handle(self, message: Message) -> None:
        error = message.error()
        if error is not None:
            if error.code() != KafkaError._PARTITION_EOF:
                logger.error("Consumer error: %s", error)
            return

        raw = message.value()
        topic, index, offset = message.topic(), message.partition(), message.offset()
        if topic is None or index is None or offset is None:
            logger.error("Message without a position, ignoring it")
            return

        partition: PartitionKey = (topic, index)
        reply_topic = self._config.kafka_result_topic

        if raw is None:
            logger.warning("Skipping tombstone at %s/%s", partition, offset)
            return

        self._offsets.start(partition, offset)

        try:
            # pydantic's ValidationError is a ValueError, as is bad UTF-8.
            request = RenderRequest.model_validate_json(raw)
        except ValueError as parse_error:
            request_id = _request_id_of(raw)
            logger.warning("Unparseable request at %s/%s: %s", partition, offset, parse_error)
            if request_id:
                self._publish(
                    RenderResult.failure(request_id, "INVALID_REQUEST", str(parse_error)),
                    reply_topic,
                    partition,
                    offset,
                )
            else:
                self._offsets.complete(partition, offset)
            return

        if request.reply_topic:
            allowed_topics = {self._config.kafka_result_topic, *self._config.kafka_allowed_reply_topics}
            if request.reply_topic not in allowed_topics:
                logger.warning("Rejected reply topic %s for request %s", request.reply_topic, request.request_id)
                self._publish(
                    RenderResult.failure(request.request_id, "INVALID_REQUEST", "Reply topic is not allowed"),
                    reply_topic,
                    partition,
                    offset,
                )
                return
            reply_topic = request.reply_topic

        try:
            future = submit_render(request, pool=self._pool)
        except PoolFull:
            # Lost the race against another partition's job. Rewind so the
            # message is redelivered once a slot frees up.
            self._offsets.abandon(partition, offset)
            self._rewind(partition, offset)
            self._pause()
            return

        future.add_done_callback(
            partial(
                self._on_rendered,
                request_id=request.request_id,
                topic=reply_topic,
                partition=partition,
                offset=offset,
            )
        )

    def _on_rendered(
        self,
        future: "Future[RenderResult]",
        *,
        request_id: str,
        topic: str,
        partition: PartitionKey,
        offset: int,
    ) -> None:
        """Runs on the worker thread that finished the card."""
        try:
            result = future.result()
        except Exception:
            logger.exception("Render job for %s did not produce a result", request_id)
            result = RenderResult.failure(request_id, "RENDER_FAILED", "Card rendering failed")

        self._publish(result, topic, partition, offset)

    def _publish(self, result: RenderResult, topic: str, partition: PartitionKey, offset: int) -> None:
        payload = result.model_dump_json(by_alias=True).encode("utf-8")
        headers: list[tuple[str, str | bytes | None]] = [
            ("kind", (result.kind or "").encode()),
            ("status", result.status.encode()),
        ]
        deadline = time.monotonic() + PRODUCE_RETRY_SECONDS

        while True:
            try:
                self._producer.produce(
                    topic,
                    key=result.request_id.encode("utf-8"),
                    value=payload,
                    headers=headers,
                    on_delivery=partial(self._on_delivery, partition=partition, offset=offset),
                )
                return
            except BufferError:
                # Local produce queue is full; give librdkafka time to drain.
                if time.monotonic() > deadline:
                    logger.error("Producer queue stayed full for %s; stopping for replay", result.request_id)
                    self._fatal.set()
                    return
                self._producer.poll(0.2)
            except Exception:
                # Stop cleanly without committing this offset. The supervisor
                # restarts the worker and Kafka replays the request.
                logger.exception("Could not produce result for %s; stopping for replay", result.request_id)
                self._fatal.set()
                return

    def _on_delivery(self, error: Any, message: Any, *, partition: PartitionKey, offset: int) -> None:
        """Delivery report. The request offset only becomes committable here,
        so a crash before delivery replays the request."""
        if error is not None:
            logger.error("Result delivery failed for %s/%s: %s; stopping for replay", partition, offset, error)
            self._fatal.set()
            return
        self._offsets.complete(partition, offset)

    def _commit_if_due(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_commit < self._config.kafka_commit_interval_seconds:
            return
        self._last_commit = now

        pending = self._offsets.committable()
        if not pending:
            return

        offsets = [TopicPartition(topic, index, offset) for (topic, index), offset in pending.items()]
        try:
            # Synchronous commits make the in-memory tracker reflect what the
            # broker has actually stored. This runs at most once per configured
            # interval, never on a render thread.
            self._consumer.commit(offsets=offsets, asynchronous=False)
        except Exception:
            # Left uncommitted on purpose: the next tick retries.
            logger.exception("Offset commit failed")
            return

        self._offsets.mark_committed(pending)

    def _pause(self) -> None:
        if self._paused:
            return
        assignment = self._consumer.assignment()
        if assignment:
            self._consumer.pause(assignment)
        self._paused = True
        logger.debug("Paused consumption, render pool is saturated: %s", self._pool.stats())

    def _write_heartbeat(self) -> None:
        path: Path | None = settings.worker_heartbeat_file
        now = time.monotonic()
        if path is None or now - self._last_heartbeat < 5:
            return
        self._last_heartbeat = now
        try:
            path.touch()
        except OSError:
            logger.exception("Could not update worker heartbeat %s", path)

    def _resume(self) -> None:
        if not self._paused:
            return
        assignment = self._consumer.assignment()
        if assignment:
            self._consumer.resume(assignment)
        self._paused = False
        logger.debug("Resumed consumption")

    def _rewind(self, partition: PartitionKey, offset: int) -> None:
        try:
            self._consumer.seek(TopicPartition(partition[0], partition[1], offset))
        except Exception:
            # Worst case the message is redelivered after the next rebalance.
            logger.exception("Could not rewind %s to %s", partition, offset)

    def _on_assign(self, consumer: Consumer, partitions: list[TopicPartition]) -> None:
        logger.info("Assigned %s", [f"{p.topic}[{p.partition}]" for p in partitions])
        self._paused = False

    def _on_revoke(self, consumer: Consumer, partitions: list[TopicPartition]) -> None:
        logger.info("Revoked %s", [f"{p.topic}[{p.partition}]" for p in partitions])
        self._commit_if_due(force=True)
        self._offsets.forget([(p.topic, p.partition) for p in partitions])

    def _drain(self) -> None:
        """Finish what was accepted before shutting down: in-flight cards still
        get delivered and committed."""
        logger.info("Draining %d in-flight requests", self._offsets.in_flight())
        self._pool.shutdown(wait=True)
        undelivered = self._producer.flush(30)
        if undelivered:
            logger.error("Shutdown left %d result messages undelivered; their requests will replay", undelivered)
        self._commit_if_due(force=True)
        try:
            self._consumer.close()
        except Exception:
            logger.exception("Consumer did not close cleanly")


def _request_id_of(raw: bytes) -> str | None:
    """Best effort id lookup so even a malformed request gets an answer."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None

    if isinstance(data, dict):
        value = data.get("requestId") or data.get("request_id")
        if isinstance(value, str):
            return value
    return None


__all__ = ["KafkaBridge", "build_consumer", "build_producer"]
