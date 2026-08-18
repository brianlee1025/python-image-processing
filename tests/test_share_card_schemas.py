"""Tests for the playbook-be wire contract."""

import pytest
from pydantic import ValidationError

from image_processing_service.schemas.cards import MAX_TEXT_LENGTH, EventCard, RenderRequest, RenderResult, UserCard


def test_parses_backend_camel_case():
    request = RenderRequest.model_validate(
        {
            "requestId": "abc-123",
            "kind": "USER",
            "layout": "POSTER",
            "payload": {"title": "Aisyah", "shareUrl": "https://example.test/p/1", "avatarBase64": None},
        }
    )

    assert request.request_id == "abc-123"
    assert request.payload.share_url == "https://example.test/p/1"
    assert request.size == (1080, 1350)


def test_kind_selects_the_payload_model():
    request = RenderRequest.model_validate(
        {
            "kind": "EVENT",
            "payload": {"title": "Friday Futsal", "startsAt": "2026-09-12T19:30:00+08:00", "spotsLeft": 3},
        }
    )

    assert isinstance(request.payload, EventCard)
    assert request.payload.spots_left == 3
    assert request.payload.starts_at is not None


def test_lower_case_enums_are_accepted():
    request = RenderRequest.model_validate({"kind": "squad", "layout": "story", "payload": {"title": "Ballers"}})

    assert request.kind == "SQUAD"
    assert request.layout == "STORY"
    assert request.size == (1080, 1920)


def test_unknown_fields_are_ignored():
    """The backend must be able to add fields without breaking the renderer."""
    request = RenderRequest.model_validate(
        {"kind": "USER", "somethingNew": True, "payload": {"title": "Aisyah", "futureField": 42}}
    )

    assert request.payload.title == "Aisyah"


def test_request_id_defaults_to_a_uuid():
    request = RenderRequest.model_validate({"kind": "USER", "payload": {"title": "Aisyah"}})

    assert len(request.request_id) == 36


def test_long_text_is_clipped_not_rejected():
    request = RenderRequest.model_validate({"kind": "USER", "payload": {"title": "A", "description": "x" * 50_000}})

    assert request.payload.description is not None
    assert len(request.payload.description) == MAX_TEXT_LENGTH


def test_missing_title_is_rejected():
    with pytest.raises(ValidationError):
        RenderRequest.model_validate({"kind": "USER", "payload": {}})


def test_result_serialises_as_camel_case():
    result = RenderResult(
        request_id="abc-123",
        status="COMPLETED",
        kind="USER",
        image_base64="AAAA",
        content_type="image/png",
        width=1080,
        height=1350,
        byte_size=4,
    )

    dumped = result.model_dump(mode="json", by_alias=True)
    assert dumped["requestId"] == "abc-123"
    assert dumped["imageBase64"] == "AAAA"
    assert dumped["contentType"] == "image/png"
    assert "completedAt" in dumped


def test_failure_helper_sets_the_error_block():
    result = RenderResult.failure("abc-123", "OVERLOADED", "busy", status="REJECTED")

    assert result.status == "REJECTED"
    assert result.error is not None
    assert result.error.code == "OVERLOADED"
    assert result.image_base64 is None


def test_stats_and_badges_are_capped():
    with pytest.raises(ValidationError):
        UserCard(title="Aisyah", badges=["a", "b", "c", "d", "e"])
