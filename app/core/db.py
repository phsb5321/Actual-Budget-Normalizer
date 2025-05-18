"""DB connection and helpers for the Actual Budget Normalizer."""

from typing import Any

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

Base = declarative_base()


class Category(Base):
    """A category for a payee, used for transaction normalization."""

    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    payee = Column(String, unique=True, index=True)
    category = Column(String)


def get_engine() -> Engine:
    """Create a SQLAlchemy engine using the configured database URL."""
    from app.core.settings import get_settings

    url = get_settings().database_url
    return create_engine(url)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


def get_db() -> "DBHelper":
    """Get a DBHelper instance using a SQLAlchemy session."""
    session = SessionLocal()
    return DBHelper(session)


class DBHelper:
    """Helper class for database operations in the Actual Budget Normalizer using SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        """Initialize the DBHelper with a SQLAlchemy session."""
        self.session = session
        # Define jobs table for Core queries
        metadata = MetaData()
        self.jobs_table = Table(
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

    def get_job_status(self, job_id: str) -> dict[str, Any] | None:
        """Retrieve the status and metadata for a job by its ID using SQLAlchemy."""
        stmt = select(
            self.jobs_table.c.status,
            self.jobs_table.c.created_at,
            self.jobs_table.c.completed_at,
            self.jobs_table.c.error,
        ).where(self.jobs_table.c.id == job_id)
        result = self.session.execute(stmt).first()
        if not result:
            return None
        return {
            "status": result.status,
            "created_at": result.created_at,
            "completed_at": result.completed_at,
            "error": result.error,
        }

    def get_job_output_path(self, job_id: str) -> str | None:
        """Retrieve the output file path for a job by its ID using SQLAlchemy."""
        stmt = select(self.jobs_table.c.output_path).where(self.jobs_table.c.id == job_id)
        result = self.session.execute(stmt).first()
        if not result:
            return None
        return result.output_path

    def close(self) -> None:
        """Close the SQLAlchemy session."""
        self.session.close()
