"""FastAPI endpoints for the Actual Budget Normalizer API."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from app.agents.transaction_agent import TransactionAgent
from app.api.dependencies import get_agent, get_db_conn, get_settings
from app.core.settings import Settings
from app.services.file_service import save_upload_file, stream_csv_file
from app.workers.job_runner import run_job

router = APIRouter()


@router.post("/upload-csv", status_code=202)
async def upload_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    agent: TransactionAgent = Depends(get_agent),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Upload a CSV file and start a normalization job."""
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Only CSV files accepted")
    job_id, in_path, out_path = save_upload_file(file)
    background_tasks.add_task(run_job, job_id, in_path, out_path, agent, settings)
    return JSONResponse({"job_id": job_id})


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
