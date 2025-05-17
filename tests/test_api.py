"""API integration tests for Actual Budget Normalizer."""

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)
HTTP_200_OK = 200


def test_health() -> None:
    """Test the /health endpoint returns status ok."""
    response = client.get("/health")
    if response.status_code != HTTP_200_OK:
        msg = f"Expected status {HTTP_200_OK}, got {response.status_code}"
        raise AssertionError(msg)
    if response.json() != {"status": "ok"}:
        msg = f"Expected response {{'status': 'ok'}}, got {response.json()}"
        raise AssertionError(msg)


def test_scalar_docs() -> None:
    """Test the /scalar endpoint returns OpenAPI or Swagger docs."""
    response = client.get("/scalar")
    if response.status_code != HTTP_200_OK:
        msg = f"Expected status {HTTP_200_OK}, got {response.status_code}"
        raise AssertionError(msg)
    if not ("openapi" in response.text or "swagger" in response.text):
        msg = "Expected 'openapi' or 'swagger' in response text"
        raise AssertionError(msg)


# Additional tests for /upload-csv, /status/{job_id}, /download/{job_id} would require
# mocking file uploads and background jobs, which can be added as needed.
