"""Entry point for the Kafka worker process.

Run one of these per box (or per container). Scale out by starting more of
them: they join the same consumer group, so partitions - and therefore users -
are split between them.
"""

import logging
import signal
from threading import Event
from types import FrameType

from .messaging.bridge import KafkaBridge, build_consumer, build_producer
from .settings import settings

logger = logging.getLogger(__name__)


def run_worker() -> None:
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    stop = Event()

    def request_stop(signum: int, frame: FrameType | None) -> None:
        logger.info("Signal %s received, finishing in-flight cards", signum)
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    bridge = KafkaBridge(consumer=build_consumer(settings), producer=build_producer(settings))
    bridge.run(stop)
    logger.info("Worker stopped")


if __name__ == "__main__":
    run_worker()
