"""Main entrypoint and application factory for the Actual Budget Normalizer API.

This module initializes the FastAPI application, configures logging, sets up the database, and exposes the Scalar API reference endpoint for interactive OpenAPI documentation. It also includes the main entrypoint for running the app with Uvicorn.
"""

import logging
import sqlite3
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from scalar_fastapi import get_scalar_api_reference

from app.api.routes import router
from app.core.settings import get_settings

# Ensure the project root is in sys.path for 'uv run app/main.py' or 'python app/main.py'
PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent
for p in [str(PROJECT_ROOT), str(APP_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)


# --- Logging Setup ---
def setup_logging() -> None:
    """Configure logging to file and console, and ensure jobs directory exists."""
    Path("jobs").mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("bank-normalizer")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        file_handler = logging.FileHandler("jobs/ai_processing.log")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(file_handler)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(stream_handler)
    logger.propagate = False


setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan event handler to initialize the jobs database and ensure the jobs table exists."""
    _ = app  # Silence unused argument warning
    Path("jobs").mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    with sqlite3.connect(settings.database_url) as conn:
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
    yield


app = FastAPI(
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    title="Actual Budget Normalizer API",
    description="""
    The Actual Budget Normalizer API provides endpoints to upload, normalize, and download bank transaction CSV files using LLM-powered categorization.

    **Endpoints:**
    - `POST /upload-csv`: Upload a CSV file and start a normalization job. Returns a `job_id`.
    - `GET /status/{{job_id}}`: Check the status of a normalization job.
    - `GET /download/{{job_id}}`: Download the normalized CSV for a completed job.
    - `GET /health`: Health check endpoint.
    - `GET /scalar`: Interactive Scalar OpenAPI documentation.
    """,
    version="1.0.0",
)
app.include_router(router)


@app.get("/scalar", include_in_schema=False)
async def scalar_docs() -> JSONResponse:
    """Return Scalar API reference."""
    return get_scalar_api_reference(openapi_url=app.openapi_url, title=app.title)


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("main:app", host=settings.server_host, port=settings.server_port, reload=True)
