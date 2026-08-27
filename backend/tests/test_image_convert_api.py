"""HTTP-Ebene des WebP-Konverters: die beiden Regler als Formularfelder.

Die Konvertierung selbst hängt in `test_image_convert_service.py`; hier geht es
nur darum, dass `quality`/`scale` durchgereicht und Fehlwerte abgelehnt werden.
"""

import zipfile
from io import BytesIO

import pytest
from PIL import Image

from app.core import image_utils
from app.core.image_utils import MAX_SCALE, MIN_SCALE


def _png(size=(400, 300)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color="red").save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(name: str = "foto.png", size=(400, 300)):
    return {"files": (name, BytesIO(_png(size)), "image/png")}


def test_conversion_applies_the_requested_scale(client):
    response = client.post(
        "/convert-images", files=_upload(), data={"quality": 80, "scale": 25}
    )

    assert response.status_code == 200
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        with Image.open(BytesIO(archive.read("foto.webp"))) as image:
            assert image.size == (100, 75)


def test_conversion_without_a_scale_keeps_the_resolution(client):
    response = client.post("/convert-images", files=_upload(), data={"quality": 80})

    assert response.status_code == 200
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        with Image.open(BytesIO(archive.read("foto.webp"))) as image:
            assert image.size == (400, 300)


@pytest.mark.parametrize("scale", [0, MIN_SCALE - 1, MAX_SCALE + 1, 1000])
def test_an_out_of_range_scale_is_rejected(client, scale):
    # Die Core-Helfer klemmen den Wert ab; ein stillschweigend anderer Download
    # wäre schlimmer als ein Fehler.
    response = client.post(
        "/convert-images", files=_upload(), data={"quality": 80, "scale": scale}
    )

    assert response.status_code == 400
    assert "scale" in response.json()["detail"]


@pytest.mark.parametrize("quality", [0, 101])
def test_an_out_of_range_quality_is_still_rejected(client, quality):
    response = client.post(
        "/convert-images", files=_upload(), data={"quality": quality}
    )

    assert response.status_code == 400
    assert "quality" in response.json()["detail"]


def test_estimate_reports_the_scale_and_both_resolutions(client):
    response = client.post(
        "/convert-images/estimate", files=_upload(), data={"scale": 50}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scale"] == 50

    [estimate] = body["files"]
    assert estimate["supported"] is True
    assert (estimate["width"], estimate["height"]) == (400, 300)
    assert (estimate["scaled_width"], estimate["scaled_height"]) == (200, 150)
    assert [sample["quality"] for sample in estimate["samples"]] == body["qualities"]


def test_estimate_of_an_unreadable_file_has_no_resolution(client):
    response = client.post(
        "/convert-images/estimate",
        files={"files": ("notiz.txt", BytesIO(b"kein bild"), "text/plain")},
    )

    assert response.status_code == 200
    [estimate] = response.json()["files"]
    assert estimate["supported"] is False
    assert estimate["width"] is None and estimate["scaled_width"] is None


def test_estimate_rejects_an_out_of_range_scale(client):
    response = client.post(
        "/convert-images/estimate", files=_upload(), data={"scale": 250}
    )

    assert response.status_code == 400


def test_the_estimate_matches_what_the_download_weighs(client):
    """Die Vorschau ist nur dann etwas wert, wenn sie exakt trifft."""
    quality, scale = 55, 40

    estimate = client.post(
        "/convert-images/estimate", files=_upload(), data={"scale": scale}
    ).json()["files"][0]
    predicted = next(
        sample["size"]
        for sample in estimate["samples"]
        if sample["quality"] == quality  # 55 ist eine gemessene Stützstelle
    )

    download = client.post(
        "/convert-images", files=_upload(), data={"quality": quality, "scale": scale}
    )
    with zipfile.ZipFile(BytesIO(download.content)) as archive:
        assert len(archive.read("foto.webp")) == predicted


def test_an_oversized_image_is_rejected_with_an_actionable_reason(client):
    # Über der WebP-Grenze von 16383 px pro Kante. Die Meldung muss sagen, mit
    # welcher Auflösung es klappt — sonst probiert der Nutzer blind herum.
    response = client.post(
        "/convert-images",
        files={"files": ("panorama.png", BytesIO(_png((17000, 10))), "image/png")},
        data={"quality": 80},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "panorama.png" in detail
    assert "16383" in detail and "96 %" in detail


def test_the_same_image_converts_at_the_scale_the_error_named(client):
    response = client.post(
        "/convert-images",
        files={"files": ("panorama.png", BytesIO(_png((17000, 10))), "image/png")},
        data={"quality": 80, "scale": 50},
    )

    assert response.status_code == 200
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        with Image.open(BytesIO(archive.read("panorama.webp"))) as image:
            assert image.size == (8500, 5)


def test_a_file_over_the_preview_budget_reports_no_curve_but_still_converts(
    client, monkeypatch
):
    monkeypatch.setattr(image_utils, "ESTIMATE_PIXEL_BUDGET", 1_000)

    estimate = client.post("/convert-images/estimate", files=_upload()).json()["files"][
        0
    ]

    assert estimate["supported"] is True
    assert estimate["measurable"] is False
    assert estimate["samples"] == []
    assert "Vorschau" in estimate["note"]
    # Die Auflösung wird trotzdem gemeldet — dekodieren ist billig.
    assert (estimate["width"], estimate["height"]) == (400, 300)

    # Und die Konvertierung selbst ist davon unberührt.
    assert client.post("/convert-images", files=_upload()).status_code == 200


def test_a_measurable_file_says_so(client):
    estimate = client.post("/convert-images/estimate", files=_upload()).json()["files"][
        0
    ]

    assert estimate["measurable"] is True
    assert estimate["note"] is None
    assert estimate["samples"]


def _hdr_jpeg(main_size=(400, 300)) -> bytes:
    """HDR-JPEG (MPO): Hauptbild plus Gain Map in einer Datei."""
    buffer = BytesIO()
    Image.new("RGB", main_size, "red").save(
        buffer,
        format="MPO",
        append_images=[Image.new("L", (200, 150), 128).convert("RGB")],
    )
    return buffer.getvalue()


def test_an_hdr_jpeg_converts_over_http(client):
    """Der gemeldete Fall: eine HDR-Datei, an der beide Endpunkte scheiterten."""
    files = {"files": ("objekt-HDR.jpg", BytesIO(_hdr_jpeg()), "image/jpeg")}

    response = client.post("/convert-images", files=files, data={"quality": 80})

    assert response.status_code == 200
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        with Image.open(BytesIO(archive.read("objekt-HDR.webp"))) as image:
            assert image.size == (400, 300)


def test_the_preview_of_an_hdr_jpeg_works_too(client):
    files = {"files": ("objekt-HDR.jpg", BytesIO(_hdr_jpeg()), "image/jpeg")}

    response = client.post("/convert-images/estimate", files=files, data={"scale": 50})

    assert response.status_code == 200
    [estimate] = response.json()["files"]
    assert estimate["supported"] and estimate["measurable"]
    assert (estimate["scaled_width"], estimate["scaled_height"]) == (200, 150)
