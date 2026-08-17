from logging import getLogger
from typing import Any

from celery import Celery  # type: ignore[import-untyped]

logger = getLogger(__name__)

celery = Celery("image_processing_service")


@celery.task
def hello_world() -> None:
    logger.info("Hello World!")


@celery.on_after_finalize.connect
def setup_periodic_tasks(sender: Any, **kwargs: Any) -> None:
    logger.info("Enabling Test Task")
    sender.add_periodic_task(15.0, hello_world.s(), name="Test Task")
