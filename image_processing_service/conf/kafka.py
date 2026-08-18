from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings


class KafkaSettings(BaseSettings):
    """Kafka wiring for the request/result bridge.

    Defaults match a local broker with no auth. Deployed environments talk to
    Redpanda over mTLS, which is configured through the `kafka_ssl_*` fields.
    """

    # The bridge is opt-in so the API and the test suite never need a broker.
    kafka_enabled: bool = False

    kafka_brokers: str = "localhost:9092"
    kafka_request_topic: str = "image-render-requests"
    kafka_result_topic: str = "image-render-results"
    # Overrides are denied unless explicitly listed. This prevents a producer
    # on the request topic from using the renderer to write large payloads to
    # arbitrary Kafka topics.
    kafka_allowed_reply_topics: list[str] = []
    kafka_group_id: str = "image-render-workers"
    kafka_client_id: str = "image-processing-service"
    kafka_auto_offset_reset: str = "latest"

    # A worker that dies without leaving the group holds its partitions until
    # this expires, and every request on them waits. Kept below the backend's
    # 20s request timeout so a failover costs a retry, not a batch of cards.
    kafka_session_timeout_ms: int = Field(default=15_000, ge=6000, le=300_000)
    kafka_max_poll_interval_ms: int = Field(default=300_000, ge=1000)
    kafka_commit_interval_seconds: float = Field(default=1.0, ge=0, le=60)

    # Results carry a base64 image, so the broker and topic must allow messages
    # larger than the 1 MiB default if you raise `render_max_bytes`.
    kafka_max_message_bytes: int = Field(default=1_048_576, ge=100_000, le=100_000_000)
    kafka_compression_type: str = "lz4"

    kafka_security_protocol: str = "PLAINTEXT"
    kafka_ssl_ca_location: str | None = None
    kafka_ssl_certificate_location: str | None = None
    kafka_ssl_key_location: str | None = None
    kafka_ssl_key_password: str | None = None
    kafka_sasl_mechanism: str | None = None
    kafka_sasl_username: str | None = None
    kafka_sasl_password: str | None = None

    def _security_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {"security.protocol": self.kafka_security_protocol}
        optional = {
            "ssl.ca.location": self.kafka_ssl_ca_location,
            "ssl.certificate.location": self.kafka_ssl_certificate_location,
            "ssl.key.location": self.kafka_ssl_key_location,
            "ssl.key.password": self.kafka_ssl_key_password,
            "sasl.mechanism": self.kafka_sasl_mechanism,
            "sasl.username": self.kafka_sasl_username,
            "sasl.password": self.kafka_sasl_password,
        }
        config.update({key: value for key, value in optional.items() if value})
        return config

    def consumer_config(self) -> dict[str, Any]:
        """librdkafka config for the request consumer.

        Offsets are committed by the bridge itself, only once a result has been
        delivered, so auto commit stays off.
        """
        config: dict[str, Any] = {
            "bootstrap.servers": self.kafka_brokers,
            "client.id": f"{self.kafka_client_id}-consumer",
            "group.id": self.kafka_group_id,
            "auto.offset.reset": self.kafka_auto_offset_reset,
            "enable.auto.commit": False,
            "enable.partition.eof": False,
            "session.timeout.ms": self.kafka_session_timeout_ms,
            "max.poll.interval.ms": self.kafka_max_poll_interval_ms,
        }
        config.update(self._security_config())
        return config

    def producer_config(self) -> dict[str, Any]:
        """librdkafka config for the result producer."""
        config: dict[str, Any] = {
            "bootstrap.servers": self.kafka_brokers,
            "client.id": f"{self.kafka_client_id}-producer",
            "message.max.bytes": self.kafka_max_message_bytes,
            "compression.type": self.kafka_compression_type,
            "acks": "all",
            "enable.idempotence": True,
        }
        config.update(self._security_config())
        return config
