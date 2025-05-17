"""Background job orchestration for transaction normalization."""

import json
import sqlite3
from pathlib import Path

import pandas as pd

from app.agents.transaction_agent import TransactionAgent
from app.core.settings import Settings
from app.core.utils import utcnow_iso


def run_job(job_id: str, in_path: Path, out_path: Path, agent: TransactionAgent, settings: Settings) -> None:
    """Run a background job to normalize transactions using the provided agent."""
    with sqlite3.connect(settings.database_url) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE jobs SET status='in_progress' WHERE id=?", (job_id,))
        conn.commit()
        try:
            data_frame = pd.read_csv(in_path, parse_dates=["Data"], dayfirst=True)
            cats_path = Path(settings.categories_file)
            pays_path = Path(settings.payees_file)
            cats = json.load(cats_path.open()) if cats_path.exists() else []
            pays = json.load(pays_path.open()) if pays_path.exists() else []
            results = []
            for record in data_frame.to_dict(orient="records"):
                txn = agent.parse_transaction(record, cats, pays)
                if txn.category and txn.category not in cats:
                    cats.append(txn.category)
                if txn.payee and txn.payee not in pays:
                    pays.append(txn.payee)
                results.append(txn.dict())
            json.dump(cats, cats_path.open("w"), indent=2)
            json.dump(pays, pays_path.open("w"), indent=2)
            pd.DataFrame(results).to_csv(out_path, index=False)
            cur.execute(
                "UPDATE jobs SET status='completed', completed_at=? WHERE id=?",
                (utcnow_iso(), job_id),
            )
        except Exception as exc:
            cur.execute(
                "UPDATE jobs SET status='error', completed_at=?, error=? WHERE id=?",
                (utcnow_iso(), str(exc), job_id),
            )
        conn.commit()
