"""File I/O and CSV handling utilities."""

import uuid
from pathlib import Path

from fastapi import UploadFile
from fastapi.responses import StreamingResponse


def save_upload_file(file: UploadFile) -> tuple[str, Path, Path]:
    """Save an uploaded file to disk and return job_id, input path, and output path."""
    job_id = str(uuid.uuid4())
    in_path = Path(f"jobs/{job_id}.csv")
    out_path = Path(f"jobs/{job_id}_out.csv")
    with in_path.open("wb") as f:
        f.write(file.file.read())
    return job_id, in_path, out_path


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
