"""Pydantic models and DB models for the Actual Budget Normalizer."""

from pydantic import BaseModel


class Transaction(BaseModel):
    """Pydantic model representing a normalized transaction."""

    date: str
    payee: str
    notes: str
    category: str = ""
    amount: float


class JobStatus(BaseModel):
    """Pydantic model representing the status of a normalization job."""

    status: str
    created_at: str
    completed_at: str | None = None
    error: str | None = None
