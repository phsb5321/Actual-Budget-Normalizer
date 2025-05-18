"""FastAPI endpoints for the Actual Budget Normalizer API.

This module defines the main API routes for uploading CSV files, checking job status, downloading normalized results, and health checks. It wires together the agent, file service, and job runner components.
"""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app.api.dependencies import get_agent, get_db_conn, get_settings
from app.core.models import JobStatus
from app.core.utils import get_logger
from app.services.file_service import save_upload_file, stream_csv_file
from app.workers.job_runner import run_job

router = APIRouter()
logger = get_logger("bank-normalizer.api")


@router.post(
    "/upload-csv",
    status_code=202,
    summary="Upload a bank transaction CSV and start normalization job",
    description=(
        "Upload a CSV file containing bank transactions. "
        "The server will start a background job to normalize the transactions using LLM-powered categorization. "
        "Returns a unique job_id that can be used to check job status and download results.\n\n"
        "**Request:**\n"
        "- Content-Type: multipart/form-data\n"
        "- Form field: `file` (CSV file)\n\n"
        "**Response:**\n"
        "- 202 Accepted: `{ 'job_id': '<uuid>' }` if upload is successful.\n"
        "- 400 Bad Request: If the file is not a CSV.\n"
        "- 500 Internal Server Error: On unexpected errors."
    ),
    response_description="Job accepted. Returns job_id.",
    responses={
        202: {
            "description": "Job accepted. Returns job_id.",
            "content": {"application/json": {"example": {"job_id": "123e4567-e89b-12d3-a456-426614174000"}}},
        },
        400: {
            "description": "Only CSV files accepted.",
            "content": {"application/json": {"example": {"detail": "Only CSV files accepted"}}},
        },
        500: {"description": "Internal server error."},
    },
)
async def upload_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    agent: object = Depends(get_agent),
) -> JSONResponse:
    """Upload a CSV file and start a normalization job."""
    logger.info(f"Received upload request: filename={file.filename}")
    if not file.filename.lower().endswith(".csv"):
        logger.warning(f"Rejected file (not CSV): {file.filename}")
        raise HTTPException(400, "Only CSV files accepted")
    try:
        job_id, in_path, out_path = save_upload_file(file)
        logger.info(f"Saved upload: job_id={job_id}, in_path={in_path}, out_path={out_path}")
        settings = get_settings()  # Only used internally, not as a parameter
        db = get_db_conn()
        from app.core.utils import utcnow_iso

        db.conn.execute(
            "INSERT INTO jobs (id, status, created_at, input_path, output_path) VALUES (?, ?, ?, ?, ?)",
            (job_id, "pending", utcnow_iso(), str(in_path), str(out_path)),
        )
        db.conn.commit()
        background_tasks.add_task(run_job, job_id, in_path, out_path, agent, settings)
        logger.info(f"Background job started: job_id={job_id}")
        return JSONResponse({"job_id": job_id})
    except Exception:
        logger.exception("Error in upload_csv")
        raise


@router.get(
    "/status/{job_id}",
    response_model=JobStatus,
    summary="Get normalization job status",
    description=(
        "Check the status of a normalization job by job_id.\n\n"
        "**Path parameter:**\n"
        "- `job_id`: The job identifier returned by /upload-csv.\n\n"
        "**Response:**\n"
        "- 200 OK: Returns job status, creation and completion timestamps, and error if any.\n"
        "- 404 Not Found: If the job_id does not exist."
    ),
    response_description="Job status and metadata.",
    responses={
        200: {
            "description": "Job found.",
            "content": {
                "application/json": {
                    "example": {
                        "status": "completed",
                        "created_at": "2025-05-18T10:30:49Z",
                        "completed_at": "2025-05-18T10:31:10Z",
                        "error": None,
                    }
                }
            },
        },
        404: {
            "description": "Job not found.",
            "content": {"application/json": {"example": {"detail": "Job not found"}}},
        },
    },
)
async def get_status(job_id: str, db: object = Depends(get_db_conn)) -> dict:
    """Get the status of a job."""
    row = db.get_job_status(job_id)
    if not row:
        raise HTTPException(404, "Job not found")
    return row


@router.get(
    "/download/{job_id}",
    response_class=FileResponse,
    summary="Download normalized CSV for completed job",
    description=(
        "Download the normalized CSV file for a completed job.\n\n"
        "**Path parameter:**\n"
        "- `job_id`: The job identifier returned by /upload-csv.\n\n"
        "**Response:**\n"
        "- 200 OK: Returns the normalized CSV file as an attachment.\n"
        "- 404 Not Found: If the job is not complete or does not exist."
    ),
    response_description="Normalized CSV file.",
    responses={
        200: {"description": "CSV file download."},
        404: {
            "description": "Job not found or not complete.",
            "content": {"application/json": {"example": {"detail": "Job not found"}}},
        },
    },
)
async def download(job_id: str, db: object = Depends(get_db_conn)) -> StreamingResponse:
    """Download the normalized CSV for a completed job."""
    out_path = db.get_job_output_path(job_id)
    if not out_path:
        raise HTTPException(404, "Job not found")
    return stream_csv_file(Path(out_path), job_id)


@router.get(
    "/health",
    summary="Health check",
    description="Simple health check endpoint. Returns status ok.",
    response_description="Status ok.",
    responses={200: {"description": "API is healthy.", "content": {"application/json": {"example": {"status": "ok"}}}}},
)
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}
