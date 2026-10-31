"""Voz do assistente: falar (Fish Audio ou Edge TTS) e ouvir (microfone + Gemini).

- Fala: gera MP3 pela API do Fish Audio com a voz do Jarvis (FISH_API_KEY), senão pelo site do
  Fish Audio (depois de `python -m nexo fish login`) e, se nada disso responder, pelo Edge TTS; toca pelo próprio Windows (MCI), sem programa extra. Sem nenhum
  desses, não fala (a resposta fica escrita): a voz do Windows é outra pessoa. Frases curtas ficam guardadas em dados/falas.
- Escuta: mede o ruído da sala, grava enquanto há voz e para depois de um silêncio curto.
  A transcrição usa os modelos "lite" do Gemini, para não gastar a cota da conversa.
"""
import asyncio
import ctypes
import hashlib
import io
import json
import os
import re
import tempfile
import threading
import time
import wave
from urllib import request

from . import config

VOZ = os.environ.get("NEXO_VOZ", "pt-BR-AntonioNeural")
VELOCIDADE = os.environ.get("NEXO_VOZ_VELOCIDADE", "-5%")
# Modelo de voz do fish.audio (o modelId da página do modelo).
FISH_VOZ = os.environ.get("NEXO_FISH_VOZ", "fee533e18ed246f7bcbe4f2764fe900b")
FISH_MODELO = os.environ.get("NEXO_FISH_MODELO", "s2.1-pro-free")
# Vozes do seletor do painel: chave -> (nome, modelId do fish.audio). Sem modelId, é a voz do Edge TTS.
VOZES = {
    "jarvis": ("Jarvis", FISH_VOZ),
    "julius": ("Julius", "733261dd2c1944009ceb33bfadd3935b"),
    "narrador-chris": ("Narrador do Todo Mundo Odeia o Chris", "4b215a58407c4def88e0892def6421b2"),
    "capitao-nascimento": ("Capitão Nascimento", "102bccca7dc64b6b8f8494c199c5d153"),
    "antonio": ("Antônio (Edge TTS)", None),
}
VOZ_PADRAO = "jarvis"
VOZ_ESCOLHIDA = config.DADOS / "voz.json"   # lida a cada fala: a vigia roda em outro processo
FALAS =config.DADOS / "falas"   # cache das frases curtas ("Pois não, senhor?")
FALA_CURTA = 160                 # caracteres; respostas maiores quase nunca se repetem
TAXA = 16000           # amostras por segundo da gravação
BLOCO = 0.1            # segundos por bloco analisado
SILENCIO_FIM = 0.7     # segundos de silêncio que encerram a frase
MAXIMO_FALA = 25       # segundos no máximo por frase
MODELOS_TRANSCRICAO = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest", config.GEMINI_MODELO]


# ---------- escolher a voz ----------

def voz_atual() -> str:
    """Chave da voz escolhida no painel; arquivo ausente ou voz que saiu da lista volta para a padrão."""
    try:
        chave = json.loads(VOZ_ESCOLHIDA.read_text(encoding="utf-8")).get("voz")
    except (OSError, ValueError, AttributeError):
        return VOZ_PADRAO
    return chave if chave in VOZES else VOZ_PADRAO


def escolher_voz(chave: str) -> bool:
    """Guarda a voz escolhida. False se ela não está na lista."""
    if chave not in VOZES:
        return False
    VOZ_ESCOLHIDA.parent.mkdir(parents=True, exist_ok=True)
    VOZ_ESCOLHIDA.write_text(json.dumps({"voz": chave}), encoding="utf-8")
    return True


# ---------- falar ----------

def para_fala(texto: str) -> str:
    """Tira do texto o que não se fala: markdown, links do Obsidian, crases, URLs."""
    t = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), texto)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"https?://\S+", "o link", t)
    t = re.sub(r"[*_`#>|]+", "", t)
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)
    t = t.replace("—", ", ").replace("–", ", ")
    t = re.sub(r"(\d+(?:,\d+)?)\s?%", r"\1 por cento", t)
    return re.sub(r"\s+", " ", t).strip()


def _tocar_mp3(caminho: str) -> None:
    mci = ctypes.windll.winmm.mciSendStringW
    alias = f"nexo{int(time.time() * 1000)}"
    if mci(f'open "{caminho}" type mpegvideo alias {alias}', None, 0, None) != 0:
        raise RuntimeError("o Windows não conseguiu abrir o áudio")
    try:
        mci(f"play {alias} wait", None, 0, None)
    finally:
        mci(f"close {alias}", None, 0, None)


def _fish(texto: str, modelo: str) -> bytes:
    corpo = json.dumps({"text": texto, "reference_id": modelo, "format": "mp3",
                        "latency": "balanced"}, ensure_ascii=False).encode("utf-8")
    pedido = request.Request("https://api.fish.audio/v1/tts", data=corpo, method="POST", headers={
        "Authorization": f"Bearer {os.environ['FISH_API_KEY']}", "Content-Type": "application/json",
        "model": FISH_MODELO})
    with request.urlopen(pedido, timeout=30) as r:
        return r.read()


def _edge(texto: str) -> bytes:
    import edge_tts

    async def juntar() -> bytes:
        partes = []
        async for parte in edge_tts.Communicate(texto, VOZ, rate=VELOCIDADE).stream():
            if parte["type"] == "audio":
                partes.append(parte["data"])
        return b"".join(partes)
    return asyncio.run(juntar())


def _fish_site(texto: str, modelo: str) -> bytes:
    from . import fishsite
    return fishsite.gerar(texto, modelo)


def motores() -> list[tuple]:
    """(nome, voz, gerar) na ordem de preferência, para a voz escolhida agora."""
    from . import fishsite
    lista = []
    # A voz fica presa em cada motor: trocar no meio de uma geração não guarda áudio no cache da outra voz.
    modelo = VOZES[voz_atual()][1]
    if modelo:
        # A API vem antes do site: responde mais rápido e não depende do navegador.
        if os.environ.get("FISH_API_KEY"):
            lista.append(("fish", f"{modelo}|{FISH_MODELO}", lambda texto: _fish(texto, modelo)))
        if fishsite.disponivel():
            lista.append(("fish-site", modelo, lambda texto: _fish_site(texto, modelo)))
    return lista + [("edge", f"{VOZ}{VELOCIDADE}", _edge)]


def gerar_mp3(falado: str) -> str | None:
    """Caminho de um MP3 com o texto falado, ou None se nenhum motor respondeu."""
    curta = len(falado) <= FALA_CURTA
    for nome, voz, gerar in motores():
        guardada = FALAS / f"{hashlib.sha1(f'{nome}|{voz}|{falado}'.encode()).hexdigest()}.mp3"
        if curta and guardada.exists():
            return str(guardada)
        try:
            audio = gerar(falado)
        except Exception:
            continue
        if not audio:
            continue
        if curta:
            FALAS.mkdir(parents=True, exist_ok=True)
            destino = guardada
        else:
            # Um arquivo por trecho: o próximo é gravado enquanto o anterior ainda toca (e fica travado).
            destino = os.path.join(tempfile.gettempdir(), f"nexo_fala_{os.getpid()}_{time.monotonic_ns()}.mp3")
        with open(destino, "wb") as f:
            f.write(audio)
        return str(destino)
    return None


def trechos_de_fala(falado: str, primeiro: int = 60, resto: int = 220) -> list[str]:
    """Quebra a fala em frases agrupadas. O primeiro trecho é curto, para o som começar logo; os
    seguintes são maiores e ficam prontos enquanto o anterior toca."""
    trechos: list[str] = []
    for frase in (f for f in re.split(r"(?<=[.!?…])\s+", falado) if f):
        limite = primeiro if len(trechos) == 1 else resto
        cabe = len(trechos[-1]) + 1 + len(frase) <= limite if trechos else False
        if trechos and (len(trechos) > 1 or len(trechos[0]) < primeiro) and cabe:
            trechos[-1] += " " + frase
        else:
            trechos.append(frase)
    return trechos or [falado]


def falar(texto: str, ao_primeiro_som=None, esperar=None) -> None:
    """Fala o texto frase a frase: enquanto uma toca, a próxima já está sendo gerada.
    `ao_primeiro_som` é chamado no instante em que o primeiro trecho começa a tocar. `esperar` é uma
    thread (o reconhecimento falado): a geração já começa, mas o primeiro trecho só toca quando ela acaba."""
    falado = para_fala(texto)
    if not falado:
        return
    from concurrent.futures import ThreadPoolExecutor
    trechos = trechos_de_fala(falado)
    with ThreadPoolExecutor(1, thread_name_prefix="nexo-tts") as gerador:
        futuros = [gerador.submit(gerar_mp3, t) for t in trechos]
        for trecho, futuro in zip(trechos, futuros):
            try:
                arquivo = futuro.result()
            except Exception:
                arquivo = None
            if esperar is not None:
                esperar.join(timeout=15)
                esperar = None
            if ao_primeiro_som:
                ao_primeiro_som()
                ao_primeiro_som = None
            # Sem áudio da voz do Jarvis, o trecho fica só escrito na tela: nada de outra voz no lugar.
            if arquivo:
                try:
                    _tocar_mp3(arquivo)
                except Exception:
                    pass
                finally:
                    if not str(arquivo).startswith(str(FALAS)):
                        try:
                            os.remove(arquivo)
                        except OSError:
                            pass


def reconhecimentos() -> list[str]:
    """Frases curtas, sempre em cache, que tocam na hora enquanto a IA pensa."""
    t = config.TRATAMENTO
    return [f"Um momento, {t}.", f"Verificando, {t}.", f"Já vejo isso, {t}.", f"Só um instante, {t}."]


def frases_fixas() -> list[str]:
    t = config.TRATAMENTO
    return [f"Às suas ordens, {t}.", f"Pois não, {t}?", f"Não ouvi nada, {t}.", f"Até logo, {t}.",
            f"Desculpe, {t}, as inteligências artificiais não responderam."] + reconhecimentos() + demoras()


def demoras() -> list[str]:
    t = config.TRATAMENTO
    return [f"Só mais um instante, {t}.", f"Estou finalizando, {t}."]


def reconhecer(pronto: threading.Event | None = None, demora: float = 2.5) -> threading.Thread | None:
    """Toca um reconhecimento já guardado (sem gerar nada) e devolve a thread para esperar o fim.
    Se a resposta (`pronto`) ainda não chegou `demora` segundos depois, toca um segundo aviso.
    Frase que ainda não está em cache não toca: gerar levaria mais que a própria IA."""
    import random
    guardadas = [f for f in reconhecimentos() if _guardada(f)]
    if not guardadas:
        return None
    mais = [f for f in demoras() if _guardada(f)]

    def tocar():
        falar(random.choice(guardadas))
        if pronto is not None and mais and not pronto.wait(demora):
            falar(random.choice(mais))
    t = threading.Thread(target=tocar, daemon=True, name="nexo-reconhecer")
    t.start()
    return t


def _guardada(falado: str) -> bool:
    for nome, voz, _ in motores():
        if (FALAS / f"{hashlib.sha1(f'{nome}|{voz}|{falado}'.encode()).hexdigest()}.mp3").exists():
            return True
    return False


def preaquecer() -> None:
    """Em segundo plano: abre o navegador do Fish e guarda as frases fixas, para falarem na hora."""
    def trabalho():
        try:
            from . import fishsite
            modelo = VOZES[voz_atual()][1]
            if modelo:
                fishsite.aquecer(modelo)
        except Exception:
            pass
        for frase in frases_fixas():
            try:
                gerar_mp3(frase)
            except Exception:
                return
    threading.Thread(target=trabalho, daemon=True, name="nexo-tts-aquecer").start()


# ---------- ouvir ----------

def _nivel(bloco) -> float:
    import numpy as np
    return float(np.sqrt(np.mean(bloco.astype(np.float32) ** 2)))


def calibrar(segundos: float = 0.8) -> float:
    """Mede o ruído da sala e devolve o nível a partir do qual conta como voz."""
    import sounddevice as sd
    gravacao = sd.rec(int(segundos * TAXA), samplerate=TAXA, channels=1, dtype="int16")
    sd.wait()
    return max(_nivel(gravacao) * 1.8, 400.0)


def ouvir(limiar: float, espera_maxima: float = 8.0) -> bytes | None:
    """Grava uma frase. Devolve WAV, ou None se ninguém falou dentro da espera."""
    import numpy as np
    import sounddevice as sd

    tamanho = int(BLOCO * TAXA)
    antes: list = []      # um pouco de áudio antes da voz, para não cortar o começo
    falando: list = []
    silencio = inicio = 0.0
    comeco = time.time()
    with sd.InputStream(samplerate=TAXA, channels=1, dtype="int16", blocksize=tamanho) as fluxo:
        while True:
            bloco, _ = fluxo.read(tamanho)
            voz = _nivel(bloco) > limiar
            if not falando:
                antes = (antes + [bloco.copy()])[-3:]
                if voz:
                    falando, inicio = list(antes), time.time()
                elif time.time() - comeco > espera_maxima:
                    return None
                continue
            falando.append(bloco.copy())
            silencio = 0.0 if voz else silencio + BLOCO
            if silencio >= SILENCIO_FIM or time.time() - inicio > MAXIMO_FALA:
                break
    if len(falando) * BLOCO < 0.4:   # estalo ou ruído curto, não é fala
        return None
    saida = io.BytesIO()
    with wave.open(saida, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAXA)
        w.writeframes(np.concatenate(falando).tobytes())
    return saida.getvalue()


def transcrever(audio_wav: bytes) -> str:
    from google.genai import types
    from . import ia

    pedido = (f"Transcreva exatamente o que foi falado, em português do Brasil. A assistente se chama "
              f"{config.NOME} (escreva sempre {config.NOME} quando for chamada pelo nome). "
              "Responda só com a transcrição; se não houver fala, responda vazio.")
    r = ia.gerar_gemini([types.Part.from_bytes(data=audio_wav, mime_type="audio/wav"), pedido],
                        types.GenerateContentConfig(), modelos=MODELOS_TRANSCRICAO)
    texto = (r.text or "").strip().strip('"')
    return "" if texto.lower() in ("vazio", "(vazio)", "") else texto


# ---------- palavra de ativação local (Vosk) ----------

MODELO_VOSK = os.environ.get("NEXO_VOSK_MODELO", str(config.RAIZ / "modelos" / "vosk-model-small-pt-0.3"))


def _palavras(nome: str) -> list[str]:
    """ "Sexta-Feira" -> ["sexta", "feira"] (como o Vosk escreve)."""
    return [p for p in re.split(r"[\s\-]+", nome.lower()) if p]


PALAVRAS_NOME = _palavras(config.NOME)
# O modelo pequeno do Vosk não conhece "jarvis" e ignora palavras fora do vocabulário. Estas são
# as palavras dele em que "Jarvis" cai (medido com tests/audios); qualquer uma abre a chamada.
APELIDOS_VOSK = {"jarvis": ["árvores", "jarbas"]}
# Como a transcrição pode escrever o nome.
GRAFIAS = {"jarvis": ["jarvis", "járvis", "jarves", "jarbas", "javis"]}
# Palavras parecidas e os outros dias da semana entram como concorrentes; sem elas, tudo que
# soa parecido com o nome vira o nome. "Hoje é sexta-feira" não acorda: o nome precisa abrir a frase.
CONCORRENTES = ["festa", "cesta", "texto", "sesta", "quinta", "segunda", "terça", "quarta", "sábado",
                "domingo", "jardim", "jantar", "hoje", "na", "é", "ei", "ok", "[unk]"]


def _no_vosk(palavra: str) -> list[str]:
    return APELIDOS_VOSK.get(palavra, [palavra])


GRAMATICA = list(dict.fromkeys([v for p in PALAVRAS_NOME for v in _no_vosk(p)] + CONCORRENTES))
_modelo_vosk = None


def detector_disponivel() -> bool:
    try:
        import vosk  # noqa: F401
    except ImportError:
        return False
    return os.path.isdir(MODELO_VOSK)


def comeca_com_nome(texto_vosk: str) -> bool:
    """Resultado do Vosk -> a frase começa com o nome (aceita "ei sexta feira", "ok sexta feira")?"""
    palavras = [p for p in texto_vosk.split() if p != "[unk]"]
    if palavras[:1] in (["ei"], ["ok"]):
        palavras = palavras[1:]
    return len(palavras) >= len(PALAVRAS_NOME) and all(
        w in _no_vosk(p) for w, p in zip(palavras, PALAVRAS_NOME))


def esperar_chamada(parar=lambda: False) -> bytes | None:
    """Escuta o microfone localmente até alguém dizer uma frase que começa com o nome da assistente.

    Devolve o WAV daquela frase inteira (para transcrever o pedido) ou None se parar() virar True.
    Nada sai do computador enquanto ninguém a chama.
    """
    import json
    import numpy as np
    import sounddevice as sd
    import vosk

    global _modelo_vosk
    if _modelo_vosk is None:
        vosk.SetLogLevel(-1)
        _modelo_vosk = vosk.Model(MODELO_VOSK)
    rec = vosk.KaldiRecognizer(_modelo_vosk, TAXA, json.dumps(GRAMATICA, ensure_ascii=False))
    tamanho = int(BLOCO * TAXA)
    frase: list = []
    with sd.InputStream(samplerate=TAXA, channels=1, dtype="int16", blocksize=tamanho) as fluxo:
        while not parar():
            bloco, _ = fluxo.read(tamanho)
            frase.append(bloco.copy())
            if not rec.AcceptWaveform(bloco.tobytes()):
                frase = frase[-int(MAXIMO_FALA / BLOCO):]
                continue
            texto = json.loads(rec.Result()).get("text", "")
            if texto.strip():
                registrar_escuta(f"vosk: {texto}")
            if comeca_com_nome(texto):
                saida = io.BytesIO()
                with wave.open(saida, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(TAXA)
                    w.writeframes(np.concatenate(frase).tobytes())
                return saida.getvalue()
            frase = []
    return None


def proxima_chamada(escutar, parar=lambda: False) -> str | None:
    """Modo contínuo: espera alguém chamar a assistente pelo nome e devolve o pedido.

    "" = só chamou ("Jarvis!"); texto = pedido feito na mesma frase; None = nada (ou alarme falso).
    Com o modelo Vosk, a escuta é local e só a frase com o nome vai para a transcrição.
    Sem ele, cada frase ouvida é transcrita pela internet (gasta cota).
    """
    if detector_disponivel():
        audio = esperar_chamada(parar)
        if audio is None:
            return None
        try:
            frase = transcrever(audio)
        except Exception as e:
            registrar_escuta(f"transcrição falhou: {type(e).__name__}")
            return ""   # o Vosk ouviu o nome; sem transcrição, pergunta o que ele quer
        registrar_escuta(f"transcrição: {frase!r}")
        # O Vosk já ouviu o nome: aceita também "Ô Jarvis", "Fala, Jarvis" (nome entre as primeiras palavras).
        pedido = chamou(frase)
        if pedido is None:
            m = _CHAMADA_PERTO.match(frase)
            pedido = frase[m.end():].strip() if m else None
        return pedido
    frase = escutar(3600)
    return chamou(frase) if frase else None


_NOME_RE = r"[\s\-]*".join(
    "(?:" + "|".join(map(re.escape, GRAFIAS.get(p, [p]))) + ")" for p in PALAVRAS_NOME)
_CHAMADA = re.compile(r"^\W*(?:(?:ei|ok|olá),?\s+)?" + _NOME_RE + r"\b[\s,.!?:]*", re.I)
_CHAMADA_PERTO = re.compile(r"^\W*(?:\w+\W+){0,2}?" + _NOME_RE + r"\b[\s,.!?:]*", re.I)


def registrar_escuta(linha: str) -> None:
    """O que a escuta contínua ouviu, em dados/escuta.log: primeiro lugar para olhar quando ela "não ouve"."""
    try:
        with open(config.DADOS / "escuta.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%d/%m %H:%M:%S')} {linha}\n")
    except OSError:
        pass


def chamou(frase: str) -> str | None:
    """Devolve o pedido se a frase começa com o nome da assistente, senão None."""
    m = _CHAMADA.match(frase)
    return frase[m.end():].strip() if m else None


SIM = re.compile(r"\b(sim|pode|confirmo|claro|isso|positivo|manda)\b", re.I)
NAO = re.compile(r"\b(não|nao|negativo|cancela|espera|pare)\b", re.I)


def e_sim(frase: str) -> bool:
    return bool(SIM.search(frase)) and not NAO.search(frase)
