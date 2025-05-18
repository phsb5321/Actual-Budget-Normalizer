"""Background job orchestration for transaction normalization."""

import json
import sqlite3
from pathlib import Path

import pandas as pd

from app.agents.transaction_agent import TransactionAgent
from app.core.settings import Settings
from app.core.utils import get_logger, utcnow_iso

logger = get_logger("bank-normalizer.worker")

MAX_ROW_LOG_LEN = 300


def run_job(job_id: str, in_path: Path, out_path: Path, agent: TransactionAgent, settings: Settings) -> None:
    """Run a background job to normalize transactions using the provided agent."""
    logger.info(f"Starting job: {job_id}, input: {in_path}, output: {out_path}")
    with sqlite3.connect(settings.database_url) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE jobs SET status='in_progress' WHERE id=?", (job_id,))
        conn.commit()
        try:
            logger.info(f"Reading CSV: {in_path}")
            data_frame = pd.read_csv(in_path, parse_dates=["Data"], dayfirst=True)
            logger.info(f"Loaded {len(data_frame)} rows from {in_path}")
            cats_path = Path(settings.categories_file)
            pays_path = Path(settings.payees_file)
            cats = json.load(cats_path.open()) if cats_path.exists() else []
            pays = json.load(pays_path.open()) if pays_path.exists() else []
            results = []
            for idx, record in enumerate(data_frame.to_dict(orient="records")):
                # Log the raw CSV row as a string (truncate if too long)
                raw_row_str = str(record)
                if len(raw_row_str) > MAX_ROW_LOG_LEN:
                    raw_row_str = raw_row_str[: MAX_ROW_LOG_LEN - 3] + "..."
                logger.info(f"[AI ROW {idx + 1}/{len(data_frame)}] Raw CSV: {raw_row_str}")
                logger.info(f"[AI ROW {idx + 1}/{len(data_frame)}] Processing...")
                try:
                    txn = agent.parse_transaction(record, cats, pays, row_index=idx + 1, total_rows=len(data_frame))
                except Exception:
                    logger.exception(f"[AI ROW {idx + 1}/{len(data_frame)}] Failed to normalize: {record}")
                    raise
                if txn.category and txn.category not in cats:
                    cats.append(txn.category)
                if txn.payee and txn.payee not in pays:
                    pays.append(txn.payee)
                results.append(txn.dict())
            logger.info(f"Writing updated categories to {cats_path}")
            json.dump(cats, cats_path.open("w"), indent=2)
            logger.info(f"Writing updated payees to {pays_path}")
            json.dump(pays, pays_path.open("w"), indent=2)
            logger.info(f"Writing normalized CSV to {out_path}")
            pd.DataFrame(results).to_csv(out_path, index=False)
            logger.info(f"Wrote normalized CSV to {out_path}")
            cur.execute(
                "UPDATE jobs SET status='completed', completed_at=? WHERE id=?",
                (utcnow_iso(), job_id),
            )
        except Exception as exc:
            logger.exception(f"Error processing job {job_id}")
            cur.execute(
                "UPDATE jobs SET status='error', completed_at=?, error=? WHERE id=?",
                (utcnow_iso(), str(exc), job_id),
            )
        conn.commit()
