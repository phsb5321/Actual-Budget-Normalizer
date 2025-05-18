"""File I/O and CSV handling utilities."""

import uuid
from pathlib import Path

from fastapi import UploadFile
from fastapi.responses import StreamingResponse

from .s3_file_service import S3FileService

"""FileService provides an S3-backed interface for file operations in the app."""


class FileService:
    """Service for file operations using S3 as backend."""

    def __init__(self, s3_service: S3FileService) -> None:
        """Initialize FileService with an S3FileService instance."""
        self.s3 = s3_service

    def save_file(self, key: str, data: bytes) -> None:
        """Save a file to S3 under the given key."""
        self.s3.upload_fileobj(key, data)

    def get_file(self, key: str) -> bytes:
        """Retrieve a file from S3 by key."""
        return self.s3.download_fileobj(key)

    def list_files(self, prefix: str = "") -> list[str]:
        """List files in S3 with the given prefix."""
        return self.s3.list_files(prefix)

    def file_exists(self, key: str) -> bool:
        """Check if a file exists in S3 by key."""
        return self.s3.file_exists(key)


def save_upload_file(file: UploadFile) -> tuple[str, str, str]:
    """Save an uploaded file directly to S3 and return job_id, input key, and output key (all S3 keys)."""
    job_id = str(uuid.uuid4())
    in_key = f"jobs/{job_id}.csv"
    out_key = f"jobs/{job_id}_out.csv"
    data = file.file.read()
    s3_service = S3FileService()
    s3_service.upload_fileobj(in_key, data)
    return job_id, in_key, out_key


def stream_csv_file(out_path: Path, job_id: str) -> StreamingResponse:
    """Stream a CSV file as a FastAPI StreamingResponse for download."""
    if not out_path.exists():
        from fastapi import HTTPException

        raise HTTPException(404, "Output file missing")
    return StreamingResponse(
        out_path.open("rb"),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=normalized_{job_id}.csv"},
    )
