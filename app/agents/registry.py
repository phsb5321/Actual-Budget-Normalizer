"""Agent registry for managing agent types and instances.

This module provides a registry for agent classes, allowing dynamic registration and retrieval of agent implementations by name. Useful for extensibility and agent selection.
"""

from typing import ClassVar

from app.agents.base import BaseAgent


class AgentRegistry:
    """Registry for agent classes."""

    _registry: ClassVar[dict[str, type[BaseAgent]]] = {}

    @classmethod
    def register(cls, name: str, agent_cls: type[BaseAgent]) -> None:
        """Register an agent class with a given name."""
        cls._registry[name] = agent_cls

    @classmethod
    def get(cls, name: str) -> type[BaseAgent]:
        """Retrieve an agent class by name."""
        return cls._registry[name]

    @classmethod
    def available(cls) -> list[str]:
        """List all available agent names."""
        return list(cls._registry.keys())
