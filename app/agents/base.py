"""Base agent abstraction for transaction normalization agents."""

from abc import ABC, abstractmethod

from app.core.models import Transaction


class BaseAgent(ABC):
    """Abstract base class for all agents."""

    @abstractmethod
    def parse_transaction(self, row: dict, categories: list[str], payees: list[str]) -> Transaction:
        """Parse and normalize a transaction row."""
