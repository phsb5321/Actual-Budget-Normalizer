"""Main module for Actual Budget Normalizer API."""

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple
from uuid import uuid4

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from groq import Groq
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from scalar_fastapi import get_scalar_api_reference

# --- Logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bank-normalizer")
Path("jobs").mkdir(parents=True, exist_ok=True)
file_handler = logging.FileHandler("jobs/ai_processing.log")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logger.addHandler(file_handler)
logger.propagate = False


# --- Settings ---
class Settings(BaseSettings):
    """Application settings."""

    groq_api_key: str
    deepseek_model: str = "deepseek-r1-distill-llama-70b"
    deepseek_temperature: float = 0.6
    deepseek_max_completion_tokens: int = 4096
    deepseek_top_p: float = 0.95
    deepseek_stream: bool = True
    deepseek_stop: list[str] | None = None
    categories_file: str = "categories.json"
    payees_file: str = "payees.json"
    database_url: str = "jobs.db"
    server_host: str = "127.0.0.1"  # safer default
    server_port: int = 8000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


def get_settings() -> Settings:
    """Get application settings."""
    return Settings()


def get_client(settings: Settings = None) -> Groq:
    """Get Groq client."""
    if settings is None:
        settings = get_settings()
    return Groq(api_key=settings.groq_api_key)


# --- App and Docs ---
app = FastAPI(
    title="Actual Budget Normalizer API",
    description="""
    The Actual Budget Normalizer API provides endpoints to upload, normalize, and download bank transaction CSV files
    using LLM-powered categorization.

    **Features:**
    - Upload CSVs for normalization
    - Track job status
    - Download normalized results
    - Health check
    - Interactive Scalar OpenAPI documentation at `/scalar`
    """,
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json",
)


@app.get(
    "/scalar",
    include_in_schema=False,
    summary="Scalar OpenAPI Reference",
    description="Interactive Scalar documentation for the Actual Budget Normalizer API.",
)
async def scalar_docs() -> JSONResponse:
    """Return Scalar API reference (OpenAPI/Swagger UI alternative)."""
    return get_scalar_api_reference(openapi_url=app.openapi_url, title=app.title)


# --- Models ---
class Transaction(BaseModel):
    """A single normalized bank transaction.

    Attributes:
        date: Transaction date (YYYY-MM-DD).
        payee: Name of the payee.
        notes: Additional notes or memo.
        category: Transaction category (optional).
        amount: Transaction amount (positive for income, negative for expense).

    """

    date: str
    payee: str
    notes: str
    category: str = ""
    amount: float


# --- DB Init ---
@app.on_event("startup")
def startup_db() -> None:
    """Initialize the jobs database."""
    with sqlite3.connect(get_settings().database_url) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                input_path TEXT NOT NULL,
                output_path TEXT NOT NULL,
                error TEXT
            )"""
        )


def _raise_missing_key(key: str) -> None:
    msg = f"Missing {key} in AI response"
    raise ValueError(msg)


class AIParseContext(NamedTuple):
    """Context for AI row parsing.

    Attributes:
        row: The transaction row as a dict.
        categories: List of known categories.
        payees: List of known payees.
        settings: Application settings.
        client: Groq client instance.
        max_retries: Maximum number of retries for AI call.
        retry_delay: Delay between retries in seconds.

    """

    row: dict
    categories: list
    payees: list
    settings: Settings
    client: Groq
    max_retries: int = 3
    retry_delay: float = 2.0


# --- AI Parse Helper ---
def ai_parse_row(ctx: AIParseContext) -> Transaction:
    """Parse a row using AI, retrying if needed."""
    import time

    payload = dict(ctx.row)
    payload["existing_categories"] = ctx.categories
    payload["existing_payees"] = ctx.payees
    system_msg = {
        "role": "system",
        "content": (
            "Parse bank transaction data. Return ONLY a valid CSV row with the columns: "
            "date,payee,notes,category,amount. Do not include any explanations, thoughts, or extra text. "
            "Output must be a single CSV row."
        ),
    }
    user_msg = {"role": "user", "content": json.dumps(payload)}
    last_exception = None
    for _ in range(ctx.max_retries):
        try:
            completion = ctx.client.chat.completions.create(
                model=ctx.settings.deepseek_model,
                messages=[system_msg, user_msg],
                temperature=ctx.settings.deepseek_temperature,
                max_completion_tokens=ctx.settings.deepseek_max_completion_tokens,
                top_p=ctx.settings.deepseek_top_p,
                stream=ctx.settings.deepseek_stream,
                stop=ctx.settings.deepseek_stop,
            )
            raw_output = ""
            for chunk in completion:
                text = chunk.choices[0].delta.content or ""
                raw_output += text
            logger.info(f"AI raw output: {raw_output}")
            data = json.loads(raw_output)
            for k in ("date", "payee", "notes", "amount"):
                if k not in data:
                    _raise_missing_key(k)
            data["category"] = data.get("category") or ""
            return Transaction(**data)
        except Exception as exc:
            last_exception = exc
            logger.warning("AI parse failed: %s", exc)
            time.sleep(ctx.retry_delay)
    logger.error("AI failed after retries: %s", last_exception)
    return Transaction(
        date=ctx.row.get("Data") or ctx.row.get("date") or "",
        payee=ctx.row.get("Identificador") or ctx.row.get("payee") or "",
        notes=f"AI parse failed: {last_exception}",
        category="",
        amount=float(ctx.row.get("Valor") or ctx.row.get("amount") or 0),
    )


# --- Job Worker ---
def run_job(job_id: str, settings: Settings, client: Groq) -> None:
    """Run a normalization job."""
    in_path = Path(f"jobs/{job_id}.csv")
    out_path = Path(f"jobs/{job_id}_out.csv")
    with sqlite3.connect(settings.database_url) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE jobs SET status='in_progress' WHERE id=?", (job_id,))
        conn.commit()
        try:
            data_frame = pd.read_csv(in_path, parse_dates=["Data"], dayfirst=True)
            cats = []
            pays = []
            cats_path = Path(settings.categories_file)
            pays_path = Path(settings.payees_file)
            if cats_path.exists():
                with cats_path.open() as f:
                    cats = json.load(f)
            if pays_path.exists():
                with pays_path.open() as f:
                    pays = json.load(f)
            results = []
            for record in data_frame.to_dict(orient="records"):
                ctx = AIParseContext(record, cats, pays, settings, client)
                txn = ai_parse_row(ctx)
                if txn.category and txn.category not in cats:
                    cats.append(txn.category)
                if txn.payee and txn.payee not in pays:
                    pays.append(txn.payee)
                results.append(txn.dict())
            with cats_path.open("w") as f:
                json.dump(cats, f, indent=2)
            with pays_path.open("w") as f:
                json.dump(pays, f, indent=2)
            pd.DataFrame(results).to_csv(out_path, index=False)
            cur.execute(
                "UPDATE jobs SET status='completed', completed_at=? WHERE id=?",
                (datetime.now(UTC).isoformat(), job_id),
            )
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            cur.execute(
                "UPDATE jobs SET status='error', completed_at=?, error=? WHERE id=?",
                (datetime.now(UTC).isoformat(), str(exc), job_id),
            )
        conn.commit()


# --- Endpoints ---
@app.post(
    "/upload-csv",
    status_code=202,
    summary="Upload CSV for Normalization",
    response_description="Job ID for tracking normalization progress.",
    tags=["Jobs"],
)
async def upload_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = None,
    settings: Settings = None,
    client: Groq = None,
) -> JSONResponse:
    """Upload a CSV file and start a normalization job.

    Accepts a CSV file with bank transactions. Returns a job ID to track progress and download results later.
    """
    if file is None:
        from fastapi import File

        file = File(...)
    if settings is None:
        settings = get_settings()
    if client is None:
        client = get_client(settings)
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Only CSV files accepted")
    data = await file.read()
    job_id = str(uuid4())
    in_path = Path(f"jobs/{job_id}.csv")
    out_path = Path(f"jobs/{job_id}_out.csv")
    with in_path.open("wb") as f:
        f.write(data)
    with sqlite3.connect(settings.database_url) as conn:
        conn.execute(
            "INSERT INTO jobs VALUES (?, 'pending', ?, NULL, ?, ?, NULL)",
            (job_id, datetime.now(UTC).isoformat(), str(in_path), str(out_path)),
        )
        conn.commit()
    background_tasks.add_task(run_job, job_id, settings, client)
    return JSONResponse({"job_id": job_id})


@app.get(
    "/status/{job_id}",
    summary="Get Job Status",
    response_description="Current status and metadata for a normalization job.",
    tags=["Jobs"],
)
async def get_status(job_id: str, settings: Settings = None) -> dict:
    """Get the status of a normalization job by job ID."""
    if settings is None:
        settings = get_settings()
    with sqlite3.connect(settings.database_url) as conn:
        row = conn.execute(
            "SELECT status, created_at, completed_at, error FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    return dict(zip(["status", "created_at", "completed_at", "error"], row, strict=False))


@app.get(
    "/download/{job_id}",
    summary="Download Normalized CSV",
    response_description="Download the normalized CSV for a completed job.",
    tags=["Jobs"],
)
async def download(job_id: str, settings: Settings = None) -> StreamingResponse:
    """Download the normalized CSV for a completed job."""
    if settings is None:
        settings = get_settings()
    with sqlite3.connect(settings.database_url) as conn:
        row = conn.execute("SELECT status, output_path FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    status_val, out_path = row
    out_path = Path(out_path)
    if status_val != "completed":
        raise HTTPException(400, "Job not completed")
    if not out_path.exists():
        raise HTTPException(404, "Output file missing")
    return StreamingResponse(
        out_path.open("rb"),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=normalized_{job_id}.csv"},
    )


@app.get(
    "/health",
    summary="Health Check",
    response_description="API health status.",
    tags=["System"],
)
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


# --- Entrypoint ---
if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("main:app", host=settings.server_host, port=settings.server_port, reload=True)
