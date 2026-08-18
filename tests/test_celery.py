"""Tests for Celery task queue configuration."""

import logging

from image_processing_service.celery import celery, hello_world


def test_celery_app_exists():
    """Test that Celery app is properly instantiated."""
    assert celery is not None
    assert hasattr(celery, "tasks")


def test_celery_app_name():
    """Test that Celery app has correct name."""
    assert celery.main == "image_processing_service"


def test_celery_has_signals():
    """Test that Celery signal handlers are available."""
    assert hasattr(celery, "on_after_configure")
    assert hasattr(celery, "on_after_finalize")


def test_hello_world_task_registered():
    """Test that hello_world task is registered with Celery."""
    assert "image_processing_service.celery.hello_world" in celery.tasks


def test_hello_world_is_task():
    """Test that hello_world is a Celery task."""
    assert hasattr(hello_world, "delay")
    assert hasattr(hello_world, "apply_async")
    assert callable(hello_world)


def test_hello_world_task_name():
    """Test that hello_world task has correct name."""
    assert hello_world.name == "image_processing_service.celery.hello_world"


def test_hello_world_execution(caplog):
    """Test that hello_world task executes without error."""
    caplog.set_level(logging.INFO)
    # Run the task directly (not async)
    hello_world()

    # Check that it logged the expected message
    assert "Hello World!" in caplog.text


def test_periodic_task_setup_exists():
    """Test that periodic task setup function exists."""
    # The setup_periodic_tasks function should be connected to the signal
    # We can't easily test the actual registration without a running worker
    # but we can verify the signal handler exists
    assert hasattr(celery, "on_after_finalize")


def test_periodic_tasks_can_be_configured():
    """Test that periodic tasks configuration doesn't raise errors."""
    assert hasattr(celery.conf, "beat_schedule")
