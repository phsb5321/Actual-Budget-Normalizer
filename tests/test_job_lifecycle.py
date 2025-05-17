"""Integration test for the job lifecycle: upload, status, and download."""

import time

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

CSV_CONTENT = """date,payee,notes,category,amount\n2024-01-01,Test Payee,Test Note,,100.00\n"""
HTTP_200_OK = 200
HTTP_202_ACCEPTED = 202


def test_job_lifecycle() -> None:
    """Test the full job lifecycle: upload, poll status, and download result."""
    # Upload CSV
    files = {"file": ("test.csv", CSV_CONTENT, "text/csv")}
    response = client.post("/upload-csv", files=files)
    if response.status_code != HTTP_202_ACCEPTED:
        msg = f"Expected status {HTTP_202_ACCEPTED}, got {response.status_code}"
        raise AssertionError(msg)
    job_id = response.json().get("job_id")
    if not job_id:
        msg = "Expected a job_id in the response"
        raise AssertionError(msg)

    # Poll status until completed or error
    for _ in range(20):
        status_resp = client.get(f"/status/{job_id}")
        if status_resp.status_code != HTTP_200_OK:
            msg = f"Expected status {HTTP_200_OK}, got {status_resp.status_code}"
            raise AssertionError(msg)
        status = status_resp.json()["status"]
        if status in ("completed", "error"):
            break
        time.sleep(0.5)
    if status != "completed":
        msg = f"Expected status 'completed', got '{status}'"
        raise AssertionError(msg)

    # Download result
    download_resp = client.get(f"/download/{job_id}")
    if download_resp.status_code != HTTP_200_OK:
        msg = f"Expected status {HTTP_200_OK}, got {download_resp.status_code}"
        raise AssertionError(msg)
    if b"Test Payee" not in download_resp.content:
        msg = "Expected 'Test Payee' in the downloaded CSV content"
        raise AssertionError(msg)
