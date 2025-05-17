"""FastAPI dependencies for DI (settings, DB, agent, etc)."""

from groq import Groq

from app.agents.transaction_agent import TransactionAgent
from app.core.db import get_db
from app.core.settings import Settings, get_settings


def get_agent(settings: Settings = None) -> TransactionAgent:
    """Provide a TransactionAgent instance for dependency injection."""
    if settings is None:
        settings = get_settings()
    client = Groq(api_key=settings.groq_api_key)
    return TransactionAgent(client, settings)


def get_db_conn(settings: Settings = None) -> object:
    """Provide a database connection helper for dependency injection."""
    if settings is None:
        settings = get_settings()
    return get_db(settings.database_url)
