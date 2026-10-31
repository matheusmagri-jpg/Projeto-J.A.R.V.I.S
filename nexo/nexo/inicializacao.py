"""Início automático da vigia ao entrar no Windows.

Cria (ou apaga) um atalho na pasta Inicializar do usuário que roda `pythonw -m nexo vigia`
sem janela. Nada de serviço nem tarefa agendada: para desfazer, basta apagar o atalho
(ou rodar `python -m nexo inicializacao desativar`).
"""
import os
import subprocess
import sys
from pathlib import Path

from . import config

NOME_ATALHO = f"{config.NOME} (vigia).lnk"
# Atalhos de quando a assistente tinha outro nome: removidos ao ativar ou desativar.
ATALHOS_ANTIGOS = ["Sexta-Feira (vigia).lnk"]
ICONES_ANTIGOS = ["SEXTA FEIRA.lnk"]   # na Área de Trabalho

# Os valores vão por variável de ambiente, nunca dentro do comando.
_CRIAR = r"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:NEXO_ATALHO)
$s.TargetPath = $env:NEXO_ALVO
$s.Arguments = '-m nexo vigia'
$s.WorkingDirectory = $env:NEXO_PASTA
$s.Description = $env:NEXO_DESCRICAO
$s.WindowStyle = 7
$s.Save()
"""


_ATALHO_PAINEL = r"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:NEXO_ATALHO)
$s.TargetPath = $env:NEXO_ALVO
$s.Arguments = '"' + $env:NEXO_PARTIDA + '"'
$s.WorkingDirectory = $env:NEXO_PASTA
$s.IconLocation = $env:NEXO_ICONE
$s.Description = $env:NEXO_DESCRICAO
$s.Save()
"""


def area_de_trabalho() -> Path:
    """Pasta da Área de Trabalho do usuário (pode estar no OneDrive)."""
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; [Environment]::GetFolderPath('Desktop')"],
                       capture_output=True, text=True, encoding="utf-8", timeout=20, **config.SEM_JANELA)
    return Path(r.stdout.strip() or Path.home() / "Desktop")


def marcar_como_administrador(atalho_lnk: Path) -> None:
    """Liga o "Executar como administrador" do atalho (bit RunAsUser, 0x2000, dos LinkFlags do .lnk)."""
    dados = bytearray(atalho_lnk.read_bytes())
    dados[0x15] |= 0x20
    atalho_lnk.write_bytes(bytes(dados))


def criar_icone_painel(admin: bool = False) -> str:
    """Cria o ícone do assistente na Área de Trabalho: um clique abre o painel (sem janela de terminal).

    Com admin=True o painel abre como administrador: o Windows pede confirmação (UAC) a cada clique e
    tudo o que o Jarvis abrir herda o acesso total.
    """
    if os.name != "nt":
        return "O ícone na Área de Trabalho só está disponível no Windows."
    from .interface import icone
    ico = icone.DESTINO if icone.DESTINO.exists() else icone.gerar()
    destino = area_de_trabalho() / f"{config.NOME.upper()}.lnk"
    ambiente = dict(os.environ, NEXO_ATALHO=str(destino), NEXO_ALVO=str(pythonw()), NEXO_PASTA=str(config.RAIZ),
                    NEXO_ICONE=f"{ico},0", NEXO_DESCRICAO=f"Abrir o painel do {config.NOME}",
                    # painel.pyw acha o pacote sozinho: como administrador, a pasta de início pode ser ignorada.
                    NEXO_PARTIDA=str(config.RAIZ / "painel.pyw"))
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _ATALHO_PAINEL],
                       env=ambiente, capture_output=True, text=True, timeout=30, **config.SEM_JANELA)
    if r.returncode != 0 or not destino.exists():
        return f"Não consegui criar o ícone: {(r.stderr or r.stdout).strip()[-300:]}"
    if admin:
        marcar_como_administrador(destino)
    for nome in ICONES_ANTIGOS:
        (destino.parent / nome).unlink(missing_ok=True)
    return f"Ícone criado{' (abre como administrador)' if admin else ''}: {destino}"


def pasta_inicializar() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def atalho() -> Path:
    return pasta_inicializar() / NOME_ATALHO


def pythonw() -> Path:
    candidato = Path(sys.executable).with_name("pythonw.exe")
    return candidato if candidato.exists() else Path(sys.executable)


def ativar() -> str:
    if os.name != "nt":
        return "O início automático só está disponível no Windows."
    ambiente = dict(os.environ, NEXO_ATALHO=str(atalho()), NEXO_ALVO=str(pythonw()),
                    NEXO_PASTA=str(config.RAIZ), NEXO_DESCRICAO=f"{config.NOME}: lembretes, bom dia e avisos")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _CRIAR],
                       env=ambiente, capture_output=True, text=True, timeout=30, **config.SEM_JANELA)
    if r.returncode != 0 or not atalho().exists():
        return f"Não consegui criar o atalho: {(r.stderr or r.stdout).strip()[-300:]}"
    _remover_antigos()
    return f"Pronto: a vigia inicia sozinha quando você entrar no Windows. Atalho: {atalho()}"


def _remover_antigos() -> None:
    for nome in ATALHOS_ANTIGOS:
        (pasta_inicializar() / nome).unlink(missing_ok=True)


def desativar() -> str:
    _remover_antigos()
    if atalho().exists():
        atalho().unlink()
        return "Início automático desligado (atalho removido). A vigia que já está rodando segue até o PC desligar."
    return "O início automático já estava desligado."


def estado() -> str:
    return f"Início automático: {'ligado' if atalho().exists() else 'desligado'} ({atalho()})"
