"""Pydantic models and DB models for the Actual Budget Normalizer.

This module defines the main Pydantic models used throughout the application, including the Transaction and JobStatus models for normalized transaction data and job tracking.
"""

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
