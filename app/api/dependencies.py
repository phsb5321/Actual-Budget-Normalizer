"""FastAPI dependencies for DI (settings, DB, agent, etc).

This module provides dependency injection helpers for settings, database connections, and agent instantiation, enabling modular and testable API endpoints.
"""

from groq import Groq

from app.agents.transaction_agent import TransactionAgent
from app.core.db import get_db
from app.core.settings import get_settings


def get_agent() -> TransactionAgent:
    """Provide a TransactionAgent instance for dependency injection."""
    settings = get_settings()
    client = Groq(api_key=settings.groq_api_key)
    return TransactionAgent(client, settings)


def get_db_conn() -> object:
    """Provide a database connection helper for dependency injection."""
    return get_db()
