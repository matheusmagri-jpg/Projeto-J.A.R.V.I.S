"""Voz do Jarvis gerada pelo site do Fish Audio (fish.audio), na conta do Matheus.

Por que o site e não a API: o modelo "Fish Audio Drama 3" com a voz "Jarvis" que ele escolheu
soa como o Jarvis no site; a API é outro caminho (outra chave, outro modelo).

Como funciona:
- Usa um perfil do Chrome SÓ do Jarvis (dados/chrome-fish), separado do perfil principal. O
  Matheus entra uma vez: `python -m nexo fish login`.
- Um navegador fica aberto em segundo plano numa thread própria (o Playwright exige uma thread
  só) e é reaproveitado entre as falas; fecha sozinho depois de IDLE segundos sem uso.
- Cada fala: escreve o texto no editor, clica em "Gerar fala" e lê na resposta de
  api.fish.audio/task/<id>/public o endereço do MP3 pronto. O site gera duas amostras; vale a primeira.
- Plano grátis: 500 caracteres por geração. Textos maiores são divididos em frases, no máximo
  MAX_TRECHOS; acima disso (ou em qualquer falha) a voz cai para o Edge TTS.
- Limite diário (NEXO_FISH_LIMITE_DIA, padrão 150 gerações) para não gastar a cota da conta.

O site não é uma API: se ele mudar o visual, os seletores abaixo podem precisar de ajuste.
"""
import atexit
import datetime as dt
import json
import os
import queue
import re
import threading
import time
from concurrent.futures import Future

from . import config

MODELO_ID = os.environ.get("NEXO_FISH_VOZ", "fee533e18ed246f7bcbe4f2764fe900b")
URL = f"https://fish.audio/pt/app/text-to-speech/?modelId={MODELO_ID}"
URL_DA_VOZ = "https://fish.audio/pt/app/text-to-speech/?modelId={}"
LIMITE_DIA = int(os.environ.get("NEXO_FISH_LIMITE_DIA", "150"))
TAMANHO_TRECHO = 480      # o plano grátis aceita 500 caracteres
MAX_TRECHOS = 3
TEMPO_GERACAO = 60        # segundos esperando o site gerar
IDLE = 300                # segundos sem uso até fechar o navegador

EDITOR = "div.tiptap.ProseMirror[contenteditable=true]"
GERAR = 'button:has-text("Gerar fala")'
# Quando a geração termina, a página consulta api.fish.audio/task/<id>/public, que traz "result": URL do MP3.
TAREFA = re.compile(r"api\.fish\.audio/task/[0-9a-f]{32}/public$")


class ErroFish(Exception):
    pass


class PrecisaLogin(ErroFish):
    pass


def perfil() -> str:
    pasta = config.DADOS / "chrome-fish"
    pasta.mkdir(parents=True, exist_ok=True)
    return str(pasta)


# ---------- estado e limite diário ----------

def _arquivo():
    return config.DADOS / "fish.json"


def _ler() -> dict:
    try:
        return json.loads(_arquivo().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _salvar(**campos) -> None:
    config.DADOS.mkdir(parents=True, exist_ok=True)
    _arquivo().write_text(json.dumps({**_ler(), **campos}, ensure_ascii=False), encoding="utf-8")


def _hoje() -> str:
    return f"{dt.date.today():%Y-%m-%d}"


def uso_hoje() -> int:
    d = _ler()
    return d.get("geracoes", 0) if d.get("dia") == _hoje() else 0


def logado() -> bool:
    return bool(_ler().get("logado"))


def disponivel() -> bool:
    """O site só é usado depois do login e enquanto houver cota diária."""
    if os.environ.get("NEXO_FISH_SITE", "1").strip().lower() in {"0", "false", "nao", "não", "off"}:
        return False
    return logado() and uso_hoje() < LIMITE_DIA


def estado() -> str:
    return (f"Fish Audio (site): {'login feito' if logado() else 'sem login (rode: python -m nexo fish login)'}; "
            f"{uso_hoje()}/{LIMITE_DIA} gerações hoje.")


# ---------- texto ----------

def dividir(texto: str, tamanho: int = TAMANHO_TRECHO) -> list[str]:
    """Quebra em trechos de até `tamanho` caracteres, preferindo o fim de uma frase."""
    trechos, atual = [], ""
    for frase in re.split(r"(?<=[.!?…])\s+", texto.strip()):
        while len(frase) > tamanho:   # frase sem pontuação: corta na última vírgula ou espaço
            corte = max(frase.rfind(",", 0, tamanho), frase.rfind(" ", 0, tamanho))
            corte = corte if corte > 0 else tamanho
            if atual:
                trechos.append(atual)
                atual = ""
            trechos.append(frase[:corte].strip())
            frase = frase[corte:].lstrip(" ,")
        if atual and len(atual) + 1 + len(frase) > tamanho:
            trechos.append(atual)
            atual = ""
        atual = f"{atual} {frase}".strip()
    if atual:
        trechos.append(atual)
    return [t for t in trechos if t]


# ---------- navegador ----------

def _abrir(p, visivel: bool):
    return p.chromium.launch_persistent_context(
        perfil(), channel="chrome", headless=not visivel, viewport={"width": 1280, "height": 900},
        locale="pt-BR")


def _fechar_chrome_do_perfil() -> None:
    """Fecha só o Chrome deste perfil (ele pode continuar rodando escondido mesmo sem janela)."""
    import psutil
    alvo = os.path.normcase(perfil())
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if (proc.info["name"] or "").lower().startswith("chrome") and \
                    any(alvo in os.path.normcase(a) for a in proc.info["cmdline"] or []):
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    time.sleep(1)


def _fechar_orfaos_do_perfil() -> None:
    """Fecha só o Chrome do perfil cujo processo-pai já morreu. Matar um Chrome em uso corrompe os
    cookies e desfaz o login, então uma sessão viva (de outro processo) nunca é tocada."""
    import psutil
    alvo = os.path.normcase(perfil())
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if (proc.info["name"] or "").lower().startswith("chrome") and                     any(alvo in os.path.normcase(a) for a in proc.info["cmdline"] or []) and                     "--type=" not in " ".join(proc.info["cmdline"] or []) and proc.parent() is None:
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def _logada(pagina) -> bool:
    """Está logado se o editor aparece e o site não pede entrada."""
    try:
        pagina.locator(EDITOR).first.wait_for(timeout=20000)
        # O editor abre até sem conta; quem não entrou vê o botão "Iniciar sessão / Inscrever-se"
        # (e usaria a cota de visitante, não a da conta do Matheus).
        pagina.wait_for_timeout(2500)
    except Exception:
        return False
    if re.search(r"/(login|sign-?in|auth)", pagina.url):
        return False
    return pagina.get_by_role("button", name=re.compile(r"Iniciar sess|Sign in|Log in", re.I)).count() == 0


class _Sessao:
    """Um navegador aberto numa thread própria; as gerações entram por uma fila."""

    def __init__(self):
        self.fila: queue.Queue = queue.Queue()
        self.thread = threading.Thread(target=self._rodar, daemon=True, name="nexo-fish")
        self.thread.start()

    def gerar(self, texto: str | None, modelo: str = MODELO_ID) -> bytes | None:
        futuro: Future = Future()
        self.fila.put((texto, modelo, futuro))
        return futuro.result(timeout=TEMPO_GERACAO + 60)

    def encerrar(self) -> None:
        self.fila.put(None)

    def _rodar(self) -> None:
        global _sessao
        from playwright.sync_api import sync_playwright
        ctx = pagina = aberto = None   # `aberto` é o modelo de voz carregado na página
        vistos: set[str] = set()
        try:
            with sync_playwright() as p:
                while True:
                    try:
                        item = self.fila.get(timeout=IDLE)
                    except queue.Empty:
                        break
                    if item is None:
                        break
                    texto, modelo, futuro = item
                    try:
                        if ctx is None:
                            _fechar_orfaos_do_perfil()   # sobra de uma sessão que morreu travaria o perfil
                            ctx = _abrir(p, visivel=False)
                            pagina = ctx.pages[0] if ctx.pages else ctx.new_page()
                            aberto = None
                        if modelo != aberto:
                            aberto = None
                            pagina.goto(URL_DA_VOZ.format(modelo), wait_until="domcontentloaded")
                            if _logada(pagina):
                                aberto = modelo
                            else:
                                _salvar(logado=False)
                                raise PrecisaLogin(f"{config.NOME} ainda não entrou no Fish Audio. "
                                                   "Rode: python -m nexo fish login")
                        futuro.set_result(None if texto is None else self._uma(ctx, pagina, texto, vistos))
                    except Exception as e:
                        futuro.set_exception(e)
                        if isinstance(e, PrecisaLogin) or pagina is None or pagina.is_closed():
                            try:
                                ctx and ctx.close()
                            except Exception:
                                pass
                            ctx = pagina = None
        finally:
            try:
                ctx and ctx.close()
            except Exception:
                pass
            _sessao = None

    def _uma(self, ctx, pagina, texto: str, vistos: set) -> bytes:
        novos: list[str] = []

        def ao_responder(r):
            if not TAREFA.search(r.url) or r.url in vistos:
                return
            try:
                dados = r.json()
            except Exception:
                return
            if dados.get("state") == "finished" and str(dados.get("result", "")).endswith(".mp3"):
                vistos.add(r.url)
                novos.append(dados["result"])
            elif dados.get("state") in ("failed", "error"):
                vistos.add(r.url)

        pagina.on("response", ao_responder)
        try:
            editor = pagina.locator(EDITOR).first
            editor.click()
            pagina.keyboard.press("Control+A")
            pagina.keyboard.insert_text(texto)
            pagina.locator(GERAR).last.click()
            fim = time.time() + TEMPO_GERACAO
            while not novos and time.time() < fim:
                pagina.wait_for_timeout(200)
            if not novos:
                raise ErroFish("O Fish Audio não gerou o áudio a tempo.")
            # Baixa o arquivo inteiro (a página pode ter pedido só um pedaço dele).
            resposta = ctx.request.get(novos[0], timeout=30000)
            audio = resposta.body() if resposta.ok else b""
            if len(audio) < 1000:
                raise ErroFish(f"O Fish Audio devolveu um áudio inválido (HTTP {resposta.status}).")
            return audio
        finally:
            pagina.remove_listener("response", ao_responder)


_sessao: _Sessao | None = None
_trava = threading.Lock()


def _obter() -> _Sessao:
    global _sessao
    with _trava:
        if _sessao is None or not _sessao.thread.is_alive():
            _sessao = _Sessao()
        return _sessao


def aquecer(modelo: str = MODELO_ID) -> None:
    """Abre o navegador e a página agora, sem gerar nada, para a primeira fala não esperar por isso."""
    if disponivel():
        _obter().gerar(None, modelo)


def gerar(texto: str, modelo: str = MODELO_ID) -> bytes:
    """MP3 da fala pelo site. Levanta ErroFish (ou PrecisaLogin) se não der."""
    trechos = dividir(texto)
    if not trechos:
        raise ErroFish("texto vazio")
    if len(trechos) > MAX_TRECHOS:
        raise ErroFish(f"texto longo demais para o site ({len(trechos)} trechos)")
    if uso_hoje() + len(trechos) > LIMITE_DIA:
        raise ErroFish(f"limite de {LIMITE_DIA} gerações por dia atingido")
    partes = []
    for t in trechos:
        partes.append(_obter().gerar(t, modelo))
        _salvar(dia=_hoje(), geracoes=uso_hoje() + 1)
    return b"".join(partes)


@atexit.register
def _fechar() -> None:
    if _sessao is not None:
        _sessao.encerrar()


# ---------- login ----------

def login(espera: int = 600) -> str:
    """Abre um Chrome COMUM (sem automação) no perfil do Jarvis para o Matheus entrar no Fish Audio.

    Sem automação porque o Google bloqueia login em navegador automatizado. Depois do Enter, o
    Chrome do perfil é fechado, a sessão fica salva e a automação só a reaproveita.
    """
    import subprocess
    from . import myhub
    subprocess.Popen([myhub._chrome(), f"--user-data-dir={perfil()}", "--no-first-run",
                      "--no-default-browser-check", URL])
    try:
        input("Depois de entrar no Fish Audio nessa janela, volte aqui e aperte Enter... ")
    except EOFError:  # sem terminal interativo: dá um tempo para o login
        time.sleep(espera)
    time.sleep(3)          # o Chrome grava os cookies em disco a cada poucos segundos
    _fechar_chrome_do_perfil()
    return verificar()


def verificar() -> str:
    """Abre o perfil sem janela e confere se o editor carrega logado."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = _abrir(p, visivel=False)
        try:
            pagina = ctx.pages[0] if ctx.pages else ctx.new_page()
            pagina.goto(URL, wait_until="domcontentloaded")
            ok = _logada(pagina)
        finally:
            ctx.close()
    _salvar(logado=ok)
    if ok:
        return f"Login confirmado: {config.NOME} já pode falar pela voz do Fish Audio."
    return "Não encontrei o login salvo. Entre no Fish Audio nessa janela e só depois feche ela."
