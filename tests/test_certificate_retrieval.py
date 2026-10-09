"""Required test area 6: retrieving generated certificates."""

import io
import zipfile
from pathlib import Path

from app.models import Job
from tests.conftest import API, create_job


def test_listing_certificates_for_a_job(client):
    body = create_job(client, ["Aarav Sharma", "Diya Patel", "Rohan Verma"])

    listing = client.get(f"{API}/jobs/{body['job_id']}/certificates").json()

    assert listing["total"] == 3
    assert len(listing["items"]) == 3
    assert [item["sequence"] for item in listing["items"]] == [1, 2, 3]
    for item in listing["items"]:
        assert item["download_url"].endswith(f"/certificates/{item['id']}/download")


def test_certificate_listing_is_paginated(client):
    body = create_job(client, [f"Recipient {i:02d}" for i in range(10)])

    page = client.get(
        f"{API}/jobs/{body['job_id']}/certificates", params={"limit": 4, "offset": 4}
    ).json()

    assert page["total"] == 10
    assert page["limit"] == 4
    assert page["offset"] == 4
    assert [item["sequence"] for item in page["items"]] == [5, 6, 7, 8]


def test_listing_can_be_filtered_by_status(client):
    body = create_job(client, [{"name": "Aarav Sharma"}, {"name": ""}])

    failed = client.get(
        f"{API}/jobs/{body['job_id']}/certificates", params={"status": "FAILED"}
    ).json()

    assert failed["total"] == 1
    assert failed["items"][0]["download_url"] is None


def test_an_invalid_status_filter_is_rejected(client):
    body = create_job(client, ["Aarav Sharma"])

    response = client.get(
        f"{API}/jobs/{body['job_id']}/certificates", params={"status": "NONSENSE"}
    )

    assert response.status_code == 422


def test_downloading_a_single_certificate(client, db):
    body = create_job(client, ["Aarav Sharma"])
    certificate = db.get(Job, body["job_id"]).certificates[0]

    response = client.get(f"{API}/certificates/{certificate.id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert certificate.certificate_number in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF-")


def test_fetching_one_certificate_record(client, db):
    body = create_job(client, ["Aarav Sharma"])
    certificate = db.get(Job, body["job_id"]).certificates[0]

    record = client.get(f"{API}/certificates/{certificate.id}").json()

    assert record["recipient_name"] == "Aarav Sharma"
    assert record["certificate_number"] == certificate.certificate_number
    assert record["status"] == "GENERATED"


def test_downloading_a_failed_certificate_returns_409(client, db):
    body = create_job(client, [{"name": "Aarav Sharma"}, {"name": ""}])
    failed = next(
        c for c in db.get(Job, body["job_id"]).certificates if c.status == "FAILED"
    )

    response = client.get(f"{API}/certificates/{failed.id}/download")

    assert response.status_code == 409
    assert "FAILED" in response.json()["detail"]


def test_downloading_an_unknown_certificate_returns_404(client):
    response = client.get(f"{API}/certificates/does-not-exist/download")
    assert response.status_code == 404


def test_missing_file_on_disk_returns_404_not_500(client, db):
    """The database says GENERATED but the file is gone — report it cleanly."""
    body = create_job(client, ["Aarav Sharma"])
    certificate = db.get(Job, body["job_id"]).certificates[0]
    Path(certificate.file_path).unlink()

    response = client.get(f"{API}/certificates/{certificate.id}/download")

    assert response.status_code == 404
    assert "missing from storage" in response.json()["detail"]


def test_downloading_the_whole_job_as_a_zip(client):
    body = create_job(client, ["Aarav Sharma", "Diya Patel", "Rohan Verma"])

    response = client.get(f"{API}/jobs/{body['job_id']}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert len(names) == 3
        assert all(name.endswith(".pdf") for name in names)
        assert archive.read(names[0]).startswith(b"%PDF-")


def test_zip_download_excludes_failed_certificates(client):
    body = create_job(client, [{"name": "Aarav Sharma"}, {"name": ""}])

    response = client.get(f"{API}/jobs/{body['job_id']}/download")

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == 1


def test_zip_download_for_a_job_with_nothing_generated_returns_404(client):
    body = create_job(client, [{"name": ""}])

    response = client.get(f"{API}/jobs/{body['job_id']}/download")

    assert response.status_code == 404
