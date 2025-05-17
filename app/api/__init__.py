"""API package: provides FastAPI dependencies and route definitions for the application."""

from .dependencies import get_agent, get_db, get_settings  # noqa: F401
from .routes import router  # noqa: F401
