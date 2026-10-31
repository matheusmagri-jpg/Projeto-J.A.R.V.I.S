"""Ferramentas do NEXO, descobertas automaticamente.

Para criar uma ferramenta nova, crie um arquivo nesta pasta (sem "_" no início) com:

    FERRAMENTAS = [
        Ferramenta(
            nome="minha_ferramenta",
            descricao="Quando a IA deve usar esta ferramenta.",
            parametros={"texto": {"type": "string", "description": "..."}},
            obrigatorios=["texto"],
            executar=minha_funcao,     # recebe os parâmetros, devolve um texto curto
            confirmar=False,           # True = pede um "sim" antes de executar
        ),
    ]

Nenhum outro arquivo precisa mudar.
"""
import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Ferramenta:
    nome: str
    descricao: str
    executar: Callable[..., str]
    parametros: dict = field(default_factory=dict)
    obrigatorios: list[str] = field(default_factory=list)
    confirmar: bool = False

    @property
    def esquema(self) -> dict:
        return {"type": "object", "properties": self.parametros, "required": self.obrigatorios}


def carregar() -> dict[str, Ferramenta]:
    """Importa todos os módulos desta pasta. Um módulo com erro é ignorado, não derruba o resto."""
    todas: dict[str, Ferramenta] = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        try:
            modulo = importlib.import_module(f"{__name__}.{info.name}")
        except Exception as e:
            print(f"[nexo] ferramenta {info.name} ignorada: {e}")
            continue
        for f in getattr(modulo, "FERRAMENTAS", []):
            todas[f.nome] = f
    return todas
