"""FastAPI endpoints for the Actual Budget Normalizer API.

This module defines the main API routes for uploading CSV files, checking job status, downloading normalized results, and health checks. It wires together the agent, file service, and job runner components.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from app.agents.transaction_agent import TransactionAgent
from app.api.dependencies import get_agent, get_db_conn, get_settings
from app.services.file_service import save_upload_file, stream_csv_file
from app.workers.job_runner import run_job

router = APIRouter()
logger = logging.getLogger("bank-normalizer")


@router.post("/upload-csv", status_code=202)
async def upload_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    agent: TransactionAgent = Depends(get_agent),
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
        background_tasks.add_task(run_job, job_id, in_path, out_path, agent, settings)
        logger.info(f"Background job started: job_id={job_id}")
        return JSONResponse({"job_id": job_id})
    except Exception:
        logger.exception("Error in upload_csv")
        raise


@router.get("/status/{job_id}")
async def get_status(job_id: str, db: object = Depends(get_db_conn)) -> dict:
    """Get the status of a job."""
    row = db.get_job_status(job_id)
    if not row:
        raise HTTPException(404, "Job not found")
    return row


@router.get("/download/{job_id}")
async def download(job_id: str, db: object = Depends(get_db_conn)) -> StreamingResponse:
    """Download the normalized CSV for a completed job."""
    out_path = db.get_job_output_path(job_id)
    if not out_path:
        raise HTTPException(404, "Job not found")
    return stream_csv_file(out_path, job_id)


@router.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}
