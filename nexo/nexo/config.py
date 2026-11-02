"""Caminhos e configuração. Lê o .env da raiz sem depender de bibliotecas extras."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
# Para subprocess no Windows: sem isto, cada PowerShell abre uma janela preta quando o painel
# roda sem console (pythonw).
SEM_JANELA = {"creationflags": 0x08000000} if os.name == "nt" else {}   # CREATE_NO_WINDOW


def _carregar_env(arquivo: Path) -> None:
    if not arquivo.exists():
        return
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        valor = valor.strip().strip('"').strip("'")
        # Variáveis já definidas no sistema têm prioridade sobre o .env.
        if valor:
            os.environ.setdefault(chave.strip(), valor)


_carregar_env(RAIZ / ".env")
# O .env da pasta de cima (C:\xampp\htdocs\jarvis) completa o daqui: lá ficam chaves usadas pelos
# dois projetos, como a do DeepSeek. O que estiver definido aqui vence.
_carregar_env(RAIZ.parent / ".env")

# Nome da assistente: aparece na fala, no painel e é a palavra que a acorda no modo contínuo.
NOME = os.environ.get("NEXO_NOME", "Jarvis")
# Como ela chama o usuário nas frases fixas (a ALMA define o tratamento nas respostas da IA).
TRATAMENTO = os.environ.get("NEXO_TRATAMENTO", "senhor")
# Atalho de teclado global que traz o painel para a frente de qualquer programa ("nenhum" desliga).
TECLA = os.environ.get("NEXO_TECLA", "ctrl+alt+j").strip().lower()
if TECLA in {"nenhum", "off", "0", "nao", "não"}:
    TECLA = ""

CEREBRO = Path(os.environ.get("NEXO_CEREBRO", RAIZ / "cerebro"))
DADOS = Path(os.environ.get("NEXO_DADOS", RAIZ / "dados"))
# Pasta de trabalho dos programas do ArtCraft: o NEXO só lê e escreve arquivos aqui.
ARQUIVOS = Path(os.environ.get("NEXO_ARQUIVOS", RAIZ / "arquivos"))

CLAUDE_MODELO = os.environ.get("NEXO_CLAUDE_MODELO", "claude-opus-5-5")
GEMINI_MODELO = os.environ.get("NEXO_GEMINI_MODELO", "gemini-3.5-flash")
DEEPSEEK_MODELO = (os.environ.get("NEXO_DEEPSEEK_MODELO") or os.environ.get("DEEPSEEK_MODEL")
                   or "deepseek-chat")
DEEPSEEK_BASE_URL = (os.environ.get("NEXO_DEEPSEEK_BASE_URL") or os.environ.get("DEEPSEEK_BASE_URL")
                     or "https://api.deepseek.com").rstrip("/")
# NVIDIA (build.nvidia.com), formato da OpenAI. Rápido e profundo usam modelos diferentes.
NVIDIA_BASE_URL = os.environ.get("NEXO_NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
NVIDIA_MODELOS = {
    "rapido": os.environ.get("NEXO_NVIDIA_MODELO_RAPIDO", "minimaxai/minimax-m3.1-flash"),
    "profundo": os.environ.get("NEXO_NVIDIA_MODELO_PROFUNDO", "nvidia/nemotron-3-ultra-550b-a55b"),
}
OLLAMA_URL = (os.environ.get("NEXO_OLLAMA_URL") or os.environ.get("OLLAMA_URL")
              or "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODELO = (os.environ.get("NEXO_OLLAMA_MODELO") or os.environ.get("OLLAMA_MODEL")
                 or "qwen2.5:3b")
# Habblaud (escritório dos agentes do Claude Code, no Docker): a miniatura do painel lê daqui.
HABBLAUD_URL = os.environ.get("NEXO_HABBLAUD_URL", "http://127.0.0.1:4747").rstrip("/")
# Última reserva: 45 s não bastavam para carregar o modelo (16 s), ler o contexto (14 s) e responder a 5,6 tokens/s.
OLLAMA_TIMEOUT = float(os.environ.get("NEXO_OLLAMA_TIMEOUT", "120"))
OLLAMA_PRIMEIRO = os.environ.get("NEXO_OLLAMA_PRIMEIRO", "0").strip().lower() in {"1", "true", "sim", "on"}
OLLAMA_ATIVO = os.environ.get("NEXO_OLLAMA_ATIVO", "1").strip().lower() not in {
    "0", "false", "nao", "não", "off"
}
# Reservas para quando o modelo principal bater no limite de uso (cada um tem cota própria).
GEMINI_MODELOS = [GEMINI_MODELO] + [m for m in os.environ.get(
    "NEXO_GEMINI_RESERVAS", "gemini-3.5-flash-lite,gemini-flash-lite-latest").split(",")
    if m.strip() and m.strip() != GEMINI_MODELO]
# No modo profundo o Gemini começa pelo modelo mais forte e só depois cai para os outros.
GEMINI_MODELO_PROFUNDO = os.environ.get("NEXO_GEMINI_MODELO_PROFUNDO", "gemini-3.1-pro-preview")

IA_PREAQUECER = os.environ.get("NEXO_IA_PREAQUECER", "1").strip().lower() not in {
    "0", "false", "nao", "não", "off"
}

CACHE_SEMANTICO_ATIVO = os.environ.get("NEXO_CACHE_SEMANTICO_ATIVO", "1").strip().lower() not in {
    "0", "false", "nao", "não", "off"
}
CACHE_SEMANTICO_TTL = float(os.environ.get("NEXO_CACHE_SEMANTICO_TTL", "90"))
CACHE_SEMANTICO_LIMIAR = float(os.environ.get("NEXO_CACHE_SEMANTICO_LIMIAR", "0.72"))
CACHE_SEMANTICO_MAX = int(os.environ.get("NEXO_CACHE_SEMANTICO_MAX", "80"))

# Agenda (endereço secreto iCal do Google Agenda; várias separadas por vírgula) e e-mail por IMAP, só leitura.
AGENDA_ICS = [u.strip() for u in os.environ.get("NEXO_AGENDA_ICS", "").split(",") if u.strip()]
EMAIL_USUARIO = os.environ.get("NEXO_EMAIL_USUARIO", "").strip()
EMAIL_SENHA = os.environ.get("NEXO_EMAIL_SENHA_APP", "").replace(" ", "")   # o Google mostra a senha em blocos
EMAIL_IMAP = os.environ.get("NEXO_EMAIL_IMAP", "imap.gmail.com")
# Telegram: token do @BotFather e o único chat que o bot atende.
TELEGRAM_TOKEN = os.environ.get("NEXO_TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT = os.environ.get("NEXO_TELEGRAM_CHAT", "").strip()


def tem_claude() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def tem_gemini() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def tem_deepseek() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_KEY"))


def tem_nvidia() -> bool:
    return bool(os.environ.get("NVIDIA_API_KEY"))


def tem_ollama() -> bool:
    return OLLAMA_ATIVO
