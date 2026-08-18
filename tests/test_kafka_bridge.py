"""Tests for the Kafka bridge, driven with fake clients so no broker is needed."""

import json
import threading

import pytest

from image_processing_service.conf.kafka import KafkaSettings
from image_processing_service.messaging.bridge import KafkaBridge
from image_processing_service.services.pool import RenderPool

REQUEST_TOPIC = "image-render-requests"
RESULT_TOPIC = "image-render-results"


class FakeMessage:
    def __init__(self, value, offset=0, partition=0, topic=REQUEST_TOPIC):
        self._value = value
        self._offset = offset
        self._partition = partition
        self._topic = topic

    def error(self):
        return None

    def value(self):
        return self._value

    def topic(self):
        return self._topic

    def partition(self):
        return self._partition

    def offset(self):
        return self._offset


class FakeConsumer:
    """Hands out a fixed list of messages then asks the bridge to stop."""

    def __init__(self, messages, stop, max_empty_polls=3):
        self.messages = list(messages)
        self.stop = stop
        self.max_empty_polls = max_empty_polls
        self.empty_polls = 0
        self.commits = []
        self.paused = False
        self.closed = False
        self.seeks = []

    def subscribe(self, topics, on_assign=None, on_revoke=None):
        self.topics = topics

    def poll(self, timeout=None):
        # A paused partition yields nothing, exactly like librdkafka.
        if self.messages and not self.paused:
            return self.messages.pop(0)

        self.empty_polls += 1
        if self.empty_polls >= self.max_empty_polls:
            self.stop.set()
        return None

    def assignment(self):
        return [("assignment",)]

    def pause(self, partitions):
        self.paused = True

    def resume(self, partitions):
        self.paused = False

    def commit(self, offsets=None, asynchronous=True):
        self.commits.append({(tp.topic, tp.partition): tp.offset for tp in offsets or []})

    def seek(self, partition):
        self.seeks.append((partition.topic, partition.partition, partition.offset))

    def close(self):
        self.closed = True


class FakeProducer:
    """Collects produced messages; delivery callbacks fire on poll/flush, the
    way librdkafka serves them."""

    def __init__(self, delivery_error=None, produce_error=None):
        self.messages = []
        self.pending = []
        self.delivery_error = delivery_error
        self.produce_error = produce_error

    def produce(self, topic, key=None, value=None, headers=None, on_delivery=None):
        if self.produce_error is not None:
            raise self.produce_error
        self.messages.append({"topic": topic, "key": key, "value": value, "headers": headers})
        if on_delivery is not None:
            self.pending.append(on_delivery)

    def poll(self, timeout=None):
        while self.pending:
            self.pending.pop(0)(self.delivery_error, None)

    def flush(self, timeout=None):
        self.poll()
        return 0


@pytest.fixture
def config():
    return KafkaSettings(
        kafka_request_topic=REQUEST_TOPIC,
        kafka_result_topic=RESULT_TOPIC,
        kafka_commit_interval_seconds=0.0,
    )


def render_request(request_id="req-1"):
    return json.dumps(
        {
            "requestId": request_id,
            "kind": "USER",
            "payload": {"title": "Aisyah Rahman", "shareUrl": "https://playbookapp.org/profile/abc"},
        }
    ).encode()


def results_of(producer):
    return [json.loads(message["value"]) for message in producer.messages]


def test_renders_a_request_and_replies_on_the_result_topic(config):
    stop = threading.Event()
    consumer = FakeConsumer([FakeMessage(render_request(), offset=0)], stop)
    producer = FakeProducer()
    pool = RenderPool(workers=1, queue_size=1)

    KafkaBridge(consumer, producer, config, pool).run(stop)

    assert len(producer.messages) == 1
    assert producer.messages[0]["topic"] == RESULT_TOPIC
    assert producer.messages[0]["key"] == b"req-1"

    result = results_of(producer)[0]
    assert result["status"] == "COMPLETED"
    assert result["requestId"] == "req-1"
    assert result["contentType"] == "image/png"
    assert len(result["imageBase64"]) > 1000
    assert consumer.closed is True


def test_commits_only_after_the_result_is_delivered(config):
    stop = threading.Event()
    consumer = FakeConsumer([FakeMessage(render_request(), offset=41)], stop)
    pool = RenderPool(workers=1, queue_size=1)

    KafkaBridge(consumer, FakeProducer(), config, pool).run(stop)

    assert consumer.commits, "the bridge should have committed once the result was delivered"
    assert consumer.commits[-1] == {(REQUEST_TOPIC, 0): 42}


def test_a_malformed_request_gets_an_error_result_rather_than_silence(config):
    stop = threading.Event()
    broken = json.dumps({"requestId": "req-broken", "kind": "USER", "payload": {}}).encode()
    consumer = FakeConsumer([FakeMessage(broken, offset=0)], stop)
    producer = FakeProducer()
    pool = RenderPool(workers=1, queue_size=1)

    KafkaBridge(consumer, producer, config, pool).run(stop)

    result = results_of(producer)[0]
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "INVALID_REQUEST"
    assert result["requestId"] == "req-broken"
    assert consumer.commits[-1] == {(REQUEST_TOPIC, 0): 1}


def test_unreadable_payloads_are_skipped_but_still_committed(config):
    stop = threading.Event()
    consumer = FakeConsumer([FakeMessage(b"<html>not json</html>", offset=0)], stop)
    producer = FakeProducer()
    pool = RenderPool(workers=1, queue_size=1)

    KafkaBridge(consumer, producer, config, pool).run(stop)

    assert producer.messages == []
    assert consumer.commits[-1] == {(REQUEST_TOPIC, 0): 1}


def test_consumption_pauses_while_the_pool_is_saturated(config):
    """The backlog belongs in Kafka, not in this process's memory."""
    stop = threading.Event()
    pool = RenderPool(workers=1, queue_size=0)
    release = threading.Event()
    busy = pool.submit(release.wait, 5)

    consumer = FakeConsumer([FakeMessage(render_request(), offset=0)], stop, max_empty_polls=2)
    bridge = KafkaBridge(consumer, FakeProducer(), config, pool)

    threading.Timer(0.3, release.set).start()
    bridge.run(stop)
    busy.result(timeout=5)

    assert consumer.paused is True
    assert consumer.messages, "the request should still be waiting in the topic"


def test_a_reply_topic_override_is_honoured(config):
    config.kafka_allowed_reply_topics = ["image-render-results-uat"]
    stop = threading.Event()
    payload = json.loads(render_request())
    payload["replyTopic"] = "image-render-results-uat"
    consumer = FakeConsumer([FakeMessage(json.dumps(payload).encode(), offset=0)], stop)
    producer = FakeProducer()
    pool = RenderPool(workers=1, queue_size=1)

    KafkaBridge(consumer, producer, config, pool).run(stop)

    assert producer.messages[0]["topic"] == "image-render-results-uat"


def test_an_unapproved_reply_topic_is_rejected_on_the_default_topic(config):
    stop = threading.Event()
    payload = json.loads(render_request())
    payload["replyTopic"] = "unrelated-sensitive-topic"
    consumer = FakeConsumer([FakeMessage(json.dumps(payload).encode(), offset=0)], stop)
    producer = FakeProducer()
    pool = RenderPool(workers=1, queue_size=1)

    KafkaBridge(consumer, producer, config, pool).run(stop)

    assert producer.messages[0]["topic"] == RESULT_TOPIC
    assert results_of(producer)[0]["error"]["code"] == "INVALID_REQUEST"


def test_delivery_failure_does_not_commit_past_the_request(config):
    stop = threading.Event()
    consumer = FakeConsumer([FakeMessage(render_request(), offset=41)], stop)
    producer = FakeProducer(delivery_error=RuntimeError("broker unavailable"))
    pool = RenderPool(workers=1, queue_size=1)

    KafkaBridge(consumer, producer, config, pool).run(stop)

    assert consumer.commits
    assert consumer.commits[-1][(REQUEST_TOPIC, 0)] == 41


def test_synchronous_produce_failure_does_not_commit_past_the_request(config):
    stop = threading.Event()
    consumer = FakeConsumer([FakeMessage(render_request(), offset=7)], stop)
    producer = FakeProducer(produce_error=RuntimeError("broker unavailable"))
    pool = RenderPool(workers=1, queue_size=1)

    KafkaBridge(consumer, producer, config, pool).run(stop)

    assert consumer.commits
    assert consumer.commits[-1][(REQUEST_TOPIC, 0)] == 7
