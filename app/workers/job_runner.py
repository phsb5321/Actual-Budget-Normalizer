"""Background job orchestration for transaction normalization."""

import concurrent.futures
import io
import json
from pathlib import Path

import pandas as pd
from sqlalchemy import Column, MetaData, String, Table, Text, create_engine, update
from sqlalchemy.orm import sessionmaker

from app.agents.transaction_agent import TransactionAgent
from app.core.settings import Settings
from app.core.utils import get_logger, utcnow_iso
from app.services.file_service import FileService
from app.services.s3_file_service import S3FileService

logger = get_logger("bank-normalizer.worker")

MAX_ROW_LOG_LEN = 300


class JobRunner:
    """JobRunner executes jobs using S3-backed file storage."""

    def __init__(self) -> None:
        """Initialize JobRunner with S3 and FileService."""
        self.s3_service = S3FileService()
        self.file_service = FileService(self.s3_service)
        # Set up SQLAlchemy for jobs table
        from app.core.settings import get_settings

        self.engine = create_engine(get_settings().database_url)
        self.Session = sessionmaker(bind=self.engine)
        self.metadata = MetaData()
        self.jobs_table = Table(
            "jobs",
            self.metadata,
            Column("id", String, primary_key=True),
            Column("status", String, nullable=False),
            Column("created_at", String, nullable=False),
            Column("completed_at", String, nullable=True),
            Column("input_path", String, nullable=False),
            Column("output_path", String, nullable=False),
            Column("error", Text, nullable=True),
        )

    def run_job(
        self, job_id: str, input_key: str, output_key: str, agent: TransactionAgent, settings: Settings
    ) -> None:
        """Run a background job to normalize transactions using the provided agent."""
        logger.info(f"Starting job: {job_id}, input: {input_key}, output: {output_key}")
        session = self.Session()
        try:
            # Update job status to in_progress
            stmt = update(self.jobs_table).where(self.jobs_table.c.id == job_id).values(status="in_progress")
            session.execute(stmt)
            session.commit()
            try:
                logger.info(f"Downloading input from S3: {input_key}")
                input_data = self.file_service.get_file(input_key)
                data_frame = pd.read_csv(io.BytesIO(input_data), parse_dates=["Data"], dayfirst=True)
                logger.info(f"Loaded {len(data_frame)} rows from {input_key}")
                cats_path = Path(settings.categories_file)
                pays_path = Path(settings.payees_file)
                cats = json.load(cats_path.open()) if cats_path.exists() else []
                pays = json.load(pays_path.open()) if pays_path.exists() else []
                results = [None] * len(data_frame)
                row_dicts = data_frame.to_dict(orient="records")

                def process_row(idx_record: tuple[int, dict]) -> tuple[int, dict]:
                    idx, record = idx_record
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
                    return idx, txn.dict()

                with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                    futures = [executor.submit(process_row, (idx, record)) for idx, record in enumerate(row_dicts)]
                    for future in concurrent.futures.as_completed(futures):
                        idx, txn_dict = future.result()
                        results[idx] = txn_dict
                logger.info(f"Writing updated categories to {cats_path}")
                json.dump(cats, cats_path.open("w"), indent=2)
                logger.info(f"Writing updated payees to {pays_path}")
                json.dump(pays, pays_path.open("w"), indent=2)
                logger.info(f"Uploading normalized CSV to S3: {output_key}")
                output_data = pd.DataFrame(results).to_csv(index=False)
                self.file_service.save_file(output_key, output_data)
                logger.info(f"Uploaded normalized CSV to {output_key}")
                stmt = (
                    update(self.jobs_table)
                    .where(self.jobs_table.c.id == job_id)
                    .values(status="completed", completed_at=utcnow_iso())
                )
                session.execute(stmt)
            except Exception as exc:
                logger.exception(f"Error processing job {job_id}")
                stmt = (
                    update(self.jobs_table)
                    .where(self.jobs_table.c.id == job_id)
                    .values(status="error", completed_at=utcnow_iso(), error=str(exc))
                )
                session.execute(stmt)
            session.commit()
        finally:
            session.close()


def run_job(job_id: str, input_key: str, output_key: str, agent: TransactionAgent, settings: Settings) -> None:
    """Top-level function to run a job using JobRunner (for background tasks)."""
    runner = JobRunner()
    runner.run_job(job_id, input_key, output_key, agent, settings)
