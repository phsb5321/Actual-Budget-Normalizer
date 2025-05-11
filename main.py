import json
from datetime import date
from functools import lru_cache
from io import BytesIO
from typing import Dict, List, Optional

import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from groq import Groq
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from scalar_fastapi import get_scalar_api_reference


# --- 1. Settings via Pydantic BaseSettings ---
class Settings(BaseSettings):
    """Application configuration loaded from .env."""

    groq_api_key: str
    deepseek_model: str = "deepseek-r1-distill-llama-70b"
    deepseek_temperature: float = 0.6
    deepseek_max_completion_tokens: int = 4096
    deepseek_top_p: float = 0.95
    deepseek_stream: bool = True
    deepseek_stop: Optional[List[str]] = None
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    categories_file: str = "categories.json"
    payees_file: str = "payees.json"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache()
def get_settings() -> Settings:
    """Load and cache settings."""
    return Settings()


@lru_cache()
def get_client(settings: Settings) -> Groq:
    """Instantiate and cache the Groq client."""
    return Groq(api_key=settings.groq_api_key)


# --- 2. Transaction schema for parsed output ---
class Transaction(BaseModel):
    """Schema for parsed transaction data."""

    date: date = Field(..., description="Transaction date")
    payee: str = Field(..., description="Recipient or sender")
    notes: str = Field(..., description="Original description or memo")
    category: str = Field(..., description="Assigned category")
    amount: float = Field(..., description="Transaction amount")


# --- 3. Master list utilities ---
def load_master_list(path: str) -> List[str]:
    """Load existing categories or payees from JSON file."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def save_master_list(items: List[str], path: str) -> None:
    """Save updated categories or payees to JSON file."""
    with open(path, "w") as f:
        json.dump(items, f, indent=2)


# --- 4. CSV and processing utilities ---
def read_csv(content: bytes) -> pd.DataFrame:
    """Read bytes into a pandas DataFrame, parsing 'Data' as dates."""
    return pd.read_csv(BytesIO(content), parse_dates=["Data"], dayfirst=True)


def process_row(
    row: dict,
    categories: List[str],
    payees: List[str],
    settings: Settings,
    client: Groq,
) -> Transaction:
    """Use the Groq API (deepseek) to parse a single transaction row."""
    # Prepare prompt input as raw JSON
    prompt_input = {**row, "existing_categories": categories, "existing_payees": payees}
    raw_input = json.dumps(prompt_input)

    # Call deepseek via Groq client
    completion = client.chat.completions.create(
        model=settings.deepseek_model,
        messages=[{"role": "user", "content": raw_input}],
        temperature=settings.deepseek_temperature,
        max_completion_tokens=settings.deepseek_max_completion_tokens,
        top_p=settings.deepseek_top_p,
        stream=settings.deepseek_stream,
        stop=settings.deepseek_stop,
    )
    # Accumulate streamed content
    output_str = ""
    for chunk in completion:
        output_str += chunk.choices[0].delta.content or ""

    # Parse and validate
    parsed = json.loads(output_str)
    return Transaction.parse_obj(parsed)


def process_transactions(
    df: pd.DataFrame, settings: Settings, client: Groq
) -> List[Transaction]:
    """Process all DataFrame rows, update master lists, and return parsed transactions."""
    categories = load_master_list(settings.categories_file)
    payees = load_master_list(settings.payees_file)
    results: List[Transaction] = []

    for row in df.to_dict(orient="records"):
        txn = process_row(row, categories, payees, settings, client)
        # Update master lists
        if txn.category not in categories:
            categories.append(txn.category)
        if txn.payee not in payees:
            payees.append(txn.payee)
        results.append(txn)

    save_master_list(categories, settings.categories_file)
    save_master_list(payees, settings.payees_file)
    return results


# --- 5. FastAPI app and endpoints ---
app = FastAPI(
    title="Bank Transaction Normalizer",
    version="0.1.0",
    description="Upload bank CSVs and normalize transactions via AI-powered parsing.",
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json",
)


@app.get("/scalar", include_in_schema=False, summary="Scalar API Reference")
async def scalar_docs():
    """Serve Scalar API Reference UI."""
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title=app.title,
    )


@app.post(
    "/upload-csv",
    response_class=JSONResponse,
    summary="Upload and process bank CSV",
    response_description="List of normalized transactions",
)
async def upload_csv(
    file: UploadFile = File(
        ..., description="CSV file containing bank transactions", media_type="text/csv"
    ),
    settings: Settings = Depends(get_settings),
    client: Groq = Depends(get_client),
) -> List[Dict]:
    """Endpoint to upload a CSV and receive normalized transactions."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files accepted.")

    df = read_csv(await file.read())
    transactions = process_transactions(df, settings, client)
    return JSONResponse([t.dict() for t in transactions])


@app.get("/health", summary="Health Check", response_description="Service status")
async def health_check() -> Dict[str, str]:
    """Simple health check endpoint."""
    return {"status": "ok"}


# --- 6. Entrypoint for uv run ---
if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    client = get_client(settings)
    uvicorn.run(
        "main:app", host=settings.server_host, port=settings.server_port, reload=True
    )
