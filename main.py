"""Main entrypoint and application factory for the Actual Budget Normalizer API.

This module initializes the FastAPI application, configures logging, sets up the database, and exposes the Scalar API reference endpoint for interactive OpenAPI documentation. It also includes the main entrypoint for running the app with Uvicorn.
"""

import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from scalar_fastapi import get_scalar_api_reference
from sqlalchemy import Column, MetaData, String, Table, Text, create_engine
from sqlalchemy.exc import ProgrammingError

from app.api.routes import router
from app.core.db import Base
from app.core.settings import get_settings
from app.core.utils import get_logger

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
    logger = get_logger("bank-normalizer")
    logger.setLevel(logging.INFO)
    # Add file handler for persistent logs (not colorized)
    if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        file_handler = logging.FileHandler("jobs/ai_processing.log")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(file_handler)
    logger.propagate = False


setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan event handler to initialize the jobs and categories tables using SQLAlchemy (PostgreSQL compatible)."""
    _ = app  # Silence unused argument warning
    Path("jobs").mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    engine = create_engine(settings.database_url)
    metadata = MetaData()
    jobs_table = Table(
        "jobs",
        metadata,
        Column("id", String, primary_key=True),
        Column("status", String, nullable=False),
        Column("created_at", String, nullable=False),
        Column("completed_at", String, nullable=True),
        Column("input_path", String, nullable=False),
        Column("output_path", String, nullable=False),
        Column("error", Text, nullable=True),
    )
    try:
        metadata.create_all(engine, tables=[jobs_table])
        # Also create categories table using ORM
        Base.metadata.create_all(engine)
    except ProgrammingError as exc:
        print(f"Failed to create jobs or categories table: {exc}")
        raise
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
