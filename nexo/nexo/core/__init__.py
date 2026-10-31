"""Camada de base para evolução do JARVIS.

Esta estrutura deixa o projeto menos improvisado e mais fácil de evoluir,
sem perder a identidade do assistente pessoal em português.
"""

from .orchestrator import AssistantOrchestrator, OrchestrationResult
from .tool_registry import Tool, ToolRegistry, ToolResult

__all__ = [
    "AssistantOrchestrator",
    "OrchestrationResult",
    "Tool",
    "ToolRegistry",
    "ToolResult",
]
