"""Motor central de orquestração do JARVIS.

O objetivo aqui é evitar que a lógica do sistema fique espalhada por vários
módulos sem um ponto único de decisão sobre contexto, ferramentas, IA e resposta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .. import busca, cerebro
from ..ferramentas import Ferramenta, carregar as carregar_ferramentas
from .tool_registry import Tool, ToolRegistry


@dataclass
class OrchestrationResult:
    intent: str
    tools: List[str] = field(default_factory=list)
    response: str = ""
    provider: str = "local"
    metadata: Dict[str, Any] = field(default_factory=dict)


class AssistantOrchestrator:
    """Coordena o movimento do assistente: intenção, memória, ferramentas e resposta."""

    def __init__(self, registry: Optional[ToolRegistry] = None) -> None:
        self.registry = registry or ToolRegistry()
        self._register_default_tools()
        self._register_real_tools()

    def _register_default_tools(self) -> None:
        self.registry.register(
            Tool(
                name="buscar_cerebro",
                description="Busca notas e contexto no cérebro do usuário.",
                executor=lambda **kwargs: busca.buscar(kwargs.get("consulta", kwargs.get("query", "")), limite=kwargs.get("limit", 5)),
            )
        )

        self.registry.register(
            Tool(
                name="guardar",
                description="Salva um texto relevante no cérebro do usuário.",
                executor=lambda **kwargs: cerebro.guardar(kwargs.get("texto", kwargs.get("text", "")), origem=kwargs.get("source", "orquestrador")),
            )
        )

        self.registry.register(
            Tool(
                name="registrar_diario",
                description="Registra uma entrada no diário do dia.",
                executor=lambda **kwargs: cerebro.registrar_diario(kwargs.get("texto", kwargs.get("text", "")), origem=kwargs.get("source", "orquestrador")),
            )
        )

    def _register_real_tools(self) -> None:
        """Carrega as ferramentas reais do módulo ferramens/ e registra no orquestrador."""
        try:
            ferramentas = carregar_ferramentas()
        except Exception:
            return

        for nome, ferramenta in ferramentas.items():
            if self.registry.get(nome) is not None:
                continue
            self.registry.register(
                Tool(
                    name=nome,
                    description=ferramenta.descricao,
                    executor=lambda **kwargs, _exec=ferramenta.executar: _exec(**kwargs),
                    confirm=ferramenta.confirmar,
                )
            )

    def classify_intent(self, user_text: str) -> str:
        texto = (user_text or "").lower()

        if any(p in texto for p in ("lembr", "agendar", "agenda", "alarme", "notificar")):
            return "reminder"
        if any(p in texto for p in ("buscar", "procura", "encontre", "pesquise", "buscar no cérebro", "procurar")):
            return "memory"
        if any(p in texto for p in ("diario", "registrar", "anotar", "guardar", "salvar")):
            return "memory"
        if any(p in texto for p in ("falar", "voz", "microfone", "escutar")):
            return "voice"
        if any(p in texto for p in ("clima", "tempo", "temperatura")):
            return "weather"
        return "general"

    def get_tool_plan(self, intent: str) -> List[str]:
        plan = {
            "reminder": ["registrar_diario", "guardar"],
            "memory": ["buscar_cerebro", "guardar"],
            "voice": ["registrar_diario"],
            "weather": ["clima"],
            "general": ["buscar_cerebro"],
        }
        tools = plan.get(intent, ["buscar_cerebro"])
        return [name for name in tools if self.registry.get(name) is not None] or ["buscar_cerebro"]

    def _tool_kwargs(self, tool_name: str, user_text: str) -> Dict[str, Any]:
        base = {"source": "orchestrator", "query": user_text, "text": user_text}
        if tool_name == "buscar_cerebro":
            base.update({"consulta": user_text, "limit": 5})
        elif tool_name in {"guardar", "registrar_diario"}:
            base.update({"texto": user_text})
        return base

    def run(self, user_text: str, mode: str = "rapido") -> OrchestrationResult:
        intent = self.classify_intent(user_text)
        tools = self.get_tool_plan(intent)

        for tool_name in tools:
            result = self.registry.run(tool_name, **self._tool_kwargs(tool_name, user_text))
            if not result.ok:
                continue

        response = (
            f"Intento detectada: {intent}. "
            f"Ferramentas acionadas: {', '.join(tools)}. "
            f"A lógica do assistente foi centralizada em um orquestrador para evoluir o sistema."
        )

        return OrchestrationResult(
            intent=intent,
            tools=tools,
            response=response,
            provider="local",
            metadata={"mode": mode},
        )
