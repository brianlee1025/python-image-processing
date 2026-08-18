"""Tests for the HTTP twin of the Kafka contract."""

import base64
import threading
from io import BytesIO

from PIL import Image
from pydantic import SecretStr

from image_processing_service.services import share_cards

REQUEST = {
    "requestId": "http-1",
    "kind": "USER",
    "layout": "POSTER",
    "payload": {
        "title": "Aisyah Rahman",
        "subtitle": "@aisyahplays",
        "shareUrl": "https://playbookapp.org/profile/abc",
        "stats": [{"label": "Matches", "value": "128"}],
    },
}


def test_render_returns_base64(fastapi_client):
    response = fastapi_client.post("/share-cards/render", json=REQUEST)

    assert response.status_code == 200
    body = response.json()
    assert body["requestId"] == "http-1"
    assert body["status"] == "COMPLETED"
    assert body["contentType"] == "image/png"
    assert Image.open(BytesIO(base64.b64decode(body["imageBase64"]))).size == (1080, 1350)


def test_preview_returns_the_image_itself(fastapi_client):
    response = fastapi_client.post("/share-cards/preview", json=REQUEST)

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert Image.open(BytesIO(response.content)).size == (1080, 1350)


def test_sample_endpoint_renders_a_demo_card(fastapi_client):
    response = fastapi_client.get("/share-cards/sample/EVENT", params={"layout": "CARD"})

    assert response.status_code == 200
    assert Image.open(BytesIO(response.content)).size == (1200, 630)


def test_bad_request_is_a_validation_error(fastapi_client):
    response = fastapi_client.post("/share-cards/render", json={"kind": "USER", "payload": {}})

    assert response.status_code == 422


def test_unusable_avatar_still_produces_a_card(fastapi_client):
    response = fastapi_client.post(
        "/share-cards/render",
        json={"kind": "USER", "payload": {"title": "Aisyah", "avatarBase64": "nonsense"}},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"


def test_pool_endpoint_reports_saturation(fastapi_client):
    response = fastapi_client.get("/share-cards/pool")

    assert response.status_code == 200
    assert response.json()["capacity"] >= 1


def test_a_saturated_service_answers_503_instead_of_queueing_forever(fastapi_client, monkeypatch):
    """The frontend waits on this call, so being told to retry beats waiting."""
    monkeypatch.setattr(share_cards.settings, "render_admission_wait_seconds", 0.1)

    pool = share_cards.get_render_pool()
    release = threading.Event()
    busy = [pool.submit(release.wait, 5) for _ in range(pool.capacity)]

    try:
        response = fastapi_client.post("/share-cards/render", json=REQUEST)
    finally:
        release.set()
        for future in busy:
            future.result(timeout=5)

    assert response.status_code == 503
    assert response.headers["retry-after"] == "2"
    body = response.json()
    assert body["status"] == "REJECTED"
    assert body["error"]["code"] == "OVERLOADED"


def test_oversized_request_is_rejected_before_json_parsing(fastapi_client):
    response = fastapi_client.post(
        "/share-cards/render",
        content=b"x" * (share_cards.settings.http_max_request_bytes + 1),
    )

    assert response.status_code == 413


def test_production_http_renderer_requires_api_key(fastapi_client, monkeypatch):
    monkeypatch.setattr(share_cards.settings, "environment", "production")
    monkeypatch.setattr(share_cards.settings, "http_api_key", SecretStr("test-render-key"))

    assert fastapi_client.post("/share-cards/render", json=REQUEST).status_code == 401
    assert (
        fastapi_client.post("/share-cards/render", json=REQUEST, headers={"X-API-Key": "test-render-key"}).status_code
        == 200
    )


def test_production_hides_diagnostic_render_routes(fastapi_client, monkeypatch):
    monkeypatch.setattr(share_cards.settings, "environment", "production")
    monkeypatch.setattr(share_cards.settings, "http_api_key", SecretStr("test-render-key"))

    response = fastapi_client.get("/share-cards/pool", headers={"X-API-Key": "test-render-key"})

    assert response.status_code == 404
