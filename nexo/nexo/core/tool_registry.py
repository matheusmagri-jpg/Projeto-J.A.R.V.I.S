"""Registro central de ferramentas do JARVIS.

Esse módulo estabelece a base para padronizar ferramentas e reduzir a
tendência de cada parte do projeto agir de forma isolada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional


@dataclass
class ToolResult:
    ok: bool = True
    value: Any = None
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Tool:
    name: str
    description: str
    executor: Callable[..., Any]
    confirm: bool = False

    def run(self, **kwargs: Any) -> ToolResult:
        if self.confirm and kwargs.get("_confirmation") is None:
            return ToolResult(
                ok=False,
                value=None,
                message=f"A ferramenta '{self.name}' exige confirmação explícita.",
                metadata={"requires_confirmation": True},
            )

        try:
            value = self.executor(**kwargs)
            return ToolResult(ok=True, value=value, message="ok")
        except Exception as exc:  # pragma: no cover - proteção simples da estrutura
            return ToolResult(
                ok=False,
                value=None,
                message=f"Erro ao executar '{self.name}': {exc}",
                metadata={"error": str(exc)},
            )


class ToolRegistry:
    """Armazena as ferramentas do assistente em um único local."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        self._tools[tool.name] = tool
        return tool

    def register_many(self, tools: Iterable[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list(self) -> List[str]:
        return sorted(self._tools.keys())

    def run(self, name: str, **kwargs: Any) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(
                ok=False,
                value=None,
                message=f"Ferramenta '{name}' não está registrada.",
                metadata={"missing_tool": name},
            )
        return tool.run(**kwargs)
