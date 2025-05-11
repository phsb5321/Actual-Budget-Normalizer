import json
import logging
import os
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, List
from uuid import uuid4

import pandas as pd
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from groq import Groq
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from scalar_fastapi import get_scalar_api_reference

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("bank-normalizer")
# Persist logs
os.makedirs("jobs", exist_ok=True)
file_handler = logging.FileHandler("jobs/ai_processing.log")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)
logger.addHandler(file_handler)
logger.propagate = False


# --- Settings ---
class Settings(BaseSettings):
    groq_api_key: str
    deepseek_model: str = "deepseek-r1-distill-llama-70b"
    deepseek_temperature: float = 0.6
    deepseek_max_completion_tokens: int = 4096
    deepseek_top_p: float = 0.95
    deepseek_stream: bool = True
    deepseek_stop: List[str] | None = None
    categories_file: str = "categories.json"
    payees_file: str = "payees.json"
    database_url: str = "jobs.db"
    server_host: str = "0.0.0.0"
    server_port: int = 8000

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


# --- FastAPI Dependencies ---
def get_settings() -> Settings:
    return Settings()


def get_client(settings: Settings = Depends(get_settings)) -> Groq:
    return Groq(api_key=settings.groq_api_key)


# --- FastAPI App ---
app = FastAPI(docs_url=None, redoc_url=None, openapi_url="/openapi.json")


@app.get("/scalar", include_in_schema=False)
async def scalar_docs():
    return get_scalar_api_reference(openapi_url=app.openapi_url, title=app.title)


# --- Transaction Model ---
class Transaction(BaseModel):
    date: str
    payee: str
    notes: str
    category: str = ""
    amount: float


# --- Database Initialization ---
@app.on_event("startup")
def startup_db():
    settings = get_settings()
    with sqlite3.connect(settings.database_url) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                input_path TEXT NOT NULL,
                output_path TEXT NOT NULL,
                error TEXT
            )
            """
        )


# --- Utility Functions ---
def json_safe(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def extract_json(raw: str) -> Dict[str, Any]:
    if not raw or not raw.strip():
        raise ValueError("AI response is empty, cannot extract JSON.")
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(raw)
    except Exception as e:
        logger.error(f"Failed to decode JSON from AI output: {raw}")
        raise ValueError(f"Failed to decode JSON: {e}")
    return obj


def validate_transaction_data(data: dict) -> dict:
    required_keys = {"date", "payee", "notes", "category", "amount"}
    missing = required_keys - data.keys()
    if missing:
        raise ValueError(f"AI response missing keys: {missing}")
    return data


# --- AI Parsing ---
def ai_parse_row(
    row: Dict[str, Any],
    categories: List[str],
    payees: List[str],
    settings: Settings,
    client: Groq,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> Transaction:
    payload = {k: json_safe(v) for k, v in row.items()}
    payload["existing_categories"] = categories
    payload["existing_payees"] = payees

    system_msg = {
        "role": "system",
        "content": (
            "Parse bank transaction data. Return ONLY a valid CSV row with the columns: date,payee,notes,category,amount. "
            "Do not include any explanations, thoughts, or extra text. Output must be a single CSV row."
        ),
    }
    user_msg = {"role": "user", "content": json.dumps(payload)}

    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            completion = client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[system_msg, user_msg],
                temperature=settings.deepseek_temperature,
                max_completion_tokens=settings.deepseek_max_completion_tokens,
                top_p=settings.deepseek_top_p,
                stream=settings.deepseek_stream,
                stop=settings.deepseek_stop,
            )
            raw_output = ""
            for chunk in completion:
                text = chunk.choices[0].delta.content or ""
                raw_output += text
                logger.debug(f"AI chunk: {text}")
            logger.info(f"AI raw output: {raw_output}")
            if not raw_output.strip():
                raise ValueError("Empty AI response")
            data = extract_json(raw_output)
            data["category"] = data.get("category") or ""
            validate_transaction_data(data)
            logger.info(f"AI parsed: {data}")
            return Transaction(**data)
        except Exception as e:
            logger.warning(f"AI parse attempt {attempt} failed: {e}")
            last_exception = e
            time.sleep(retry_delay)
    # Fallback: return a default Transaction with error info in notes
    logger.error(f"AI failed after {max_retries} attempts: {last_exception}")
    fallback = {
        "date": row.get("Data") or row.get("date") or "",
        "payee": row.get("Identificador") or row.get("payee") or "",
        "notes": f"AI parse failed: {last_exception}",
        "category": "",
        "amount": float(row.get("Valor") or row.get("amount") or 0),
    }
    return Transaction(**fallback)


# --- Background Job Runner ---
def run_job(job_id: str, settings: Settings, client: Groq):
    in_path = f"jobs/{job_id}.csv"
    out_path = f"jobs/{job_id}_out.csv"
    with sqlite3.connect(settings.database_url) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE jobs SET status='in_progress' WHERE id=?", (job_id,))
        conn.commit()
        try:
            df = pd.read_csv(in_path, parse_dates=["Data"], dayfirst=True)
            cats = (
                json.load(open(settings.categories_file))
                if os.path.exists(settings.categories_file)
                else []
            )
            pays = (
                json.load(open(settings.payees_file))
                if os.path.exists(settings.payees_file)
                else []
            )

            results = []
            for record in df.to_dict(orient="records"):
                txn = ai_parse_row(record, cats, pays, settings, client)
                if txn.category and txn.category not in cats:
                    cats.append(txn.category)
                if txn.payee and txn.payee not in pays:
                    pays.append(txn.payee)
                results.append(txn.dict())

            json.dump(cats, open(settings.categories_file, "w"), indent=2)
            json.dump(pays, open(settings.payees_file, "w"), indent=2)
            pd.DataFrame(results).to_csv(out_path, index=False)

            cur.execute(
                "UPDATE jobs SET status='completed', completed_at=? WHERE id=?",
                (datetime.utcnow().isoformat(), job_id),
            )
        except Exception as e:
            logger.exception(f"Job {job_id} failed")
            cur.execute(
                "UPDATE jobs SET status='error', completed_at=?, error=? WHERE id=?",
                (datetime.utcnow().isoformat(), str(e), job_id),
            )
        conn.commit()


# --- Routes ---
@app.post("/upload-csv", status_code=202)
async def upload_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    client: Groq = Depends(get_client),
) -> JSONResponse:
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Only CSV files accepted")
    data = await file.read()
    job_id = str(uuid4())
    in_path = f"jobs/{job_id}.csv"
    out_path = f"jobs/{job_id}_out.csv"
    with open(in_path, "wb") as f:
        f.write(data)

    with sqlite3.connect(settings.database_url) as conn:
        conn.execute(
            "INSERT INTO jobs VALUES (?, 'pending', ?, NULL, ?, ?, NULL)",
            (job_id, datetime.utcnow().isoformat(), in_path, out_path),
        )
        conn.commit()

    background_tasks.add_task(run_job, job_id, settings, client)
    return JSONResponse({"job_id": job_id})


@app.get("/status/{job_id}")
async def get_status(job_id: str, settings: Settings = Depends(get_settings)):
    with sqlite3.connect(settings.database_url) as conn:
        row = conn.execute(
            "SELECT status, created_at, completed_at, error FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    return dict(row)


@app.get("/download/{job_id}")
async def download(job_id: str, settings: Settings = Depends(get_settings)):
    with sqlite3.connect(settings.database_url) as conn:
        row = conn.execute(
            "SELECT status, output_path FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    status_val, out_path = row
    if status_val != "completed":
        raise HTTPException(400, "Job not completed")
    if not os.path.exists(out_path):
        raise HTTPException(404, "Output file missing")

    return StreamingResponse(
        open(out_path, "rb"),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=normalized_{job_id}.csv"
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


# --- Entrypoint ---
if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app", host=settings.server_host, port=settings.server_port, reload=True
    )
