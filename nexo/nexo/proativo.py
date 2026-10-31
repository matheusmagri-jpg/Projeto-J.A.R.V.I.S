"""Proatividade: notificações, lembretes, hábitos, bom dia, batimento e reflexão diária.

Ideias do second-brain-starter (batimento, reflexão, hábitos) e do jarvis-opensource (bom dia).
Regra de ouro: o Python junta os dados; a IA só escreve o texto (ou escolhe o que vale lembrar).
Estado em dados/proativo.json (o que já foi feito hoje, lembretes, avisos já dados).
"""
import datetime as dt
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from . import cerebro, config, ia

CIDADE = os.environ.get("NEXO_CIDADE", "Brasília")
HORA_BOM_DIA = os.environ.get("NEXO_BOM_DIA", "07:45")
HORARIO_ATIVO = (8, 22)          # batimento só entre 8h e 22h
INTERVALO_BATIMENTO = 30 * 60    # segundos
HORA_COBRAR_HABITOS = 18
BRIEFING_JARVIS = config.RAIZ.parent / "data.json"   # gerado pela rotina do JARVIS (projeto irmão)

_trava = threading.Lock()


# ---------- estado ----------

def _arquivo_estado() -> Path:
    return config.DADOS / "proativo.json"


def _ler_estado() -> dict:
    try:
        return json.loads(_arquivo_estado().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _salvar_estado(estado: dict) -> None:
    config.DADOS.mkdir(parents=True, exist_ok=True)
    tmp = _arquivo_estado().with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, _arquivo_estado())


def _hoje() -> str:
    return f"{cerebro.agora():%Y-%m-%d}"


# ---------- avisos ----------

# Quem quer saber dos avisos (o painel se registra aqui para mostrar e falar).
OUVINTES: list[Callable[[str, str], None]] = []

_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$t = [System.Security.SecurityElement]::Escape($env:NEXO_AVISO_TITULO)
$c = [System.Security.SecurityElement]::Escape($env:NEXO_AVISO_TEXTO)
$x = New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$c</text></binding></visual></toast>")
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))
"""


def notificar(titulo: str, texto: str) -> bool:
    """Notificação do Windows. O texto vai por variável de ambiente, nunca dentro do comando."""
    if os.name != "nt":
        return False
    ambiente = dict(os.environ, NEXO_AVISO_TITULO=titulo[:100], NEXO_AVISO_TEXTO=texto[:300])
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _TOAST],
                           env=ambiente, capture_output=True, timeout=20, **config.SEM_JANELA)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def avisar(texto: str, titulo: str | None = None) -> None:
    """Avisa o usuário: notificação do Windows + quem estiver ouvindo (painel, voz)."""
    titulo = titulo or config.NOME
    notificar(titulo, texto)
    for ouvinte in list(OUVINTES):
        try:
            ouvinte(titulo, texto)
        except Exception:
            pass


# ---------- lembretes ----------

def _quando(minutos: int = 0, horario: str = "") -> dt.datetime:
    agora = cerebro.agora()
    if horario:
        m = re.fullmatch(r"\s*(\d{1,2})(?::|h)?(\d{2})?\s*", horario)
        if not m:
            raise ValueError("Horário deve ser como 14:30 ou 9h.")
        alvo = agora.replace(hour=int(m.group(1)), minute=int(m.group(2) or 0), second=0, microsecond=0)
        return alvo if alvo > agora else alvo + dt.timedelta(days=1)
    if minutos <= 0:
        raise ValueError("Diga daqui a quantos minutos ou a que horas.")
    return agora + dt.timedelta(minutes=int(minutos))


def lembrar(texto: str, minutos: int = 0, horario: str = "") -> str:
    quando = _quando(minutos, horario)
    with _trava:
        estado = _ler_estado()
        estado.setdefault("lembretes", []).append({"texto": texto, "quando": quando.isoformat(timespec="minutes")})
        _salvar_estado(estado)
    dia = "hoje" if quando.date() == cerebro.agora().date() else "amanhã"
    return f"Combinado: vou lembrar {dia} às {quando:%H:%M}: {texto}"


def lembretes_pendentes() -> list[dict]:
    return sorted(_ler_estado().get("lembretes", []), key=lambda l: l["quando"])


def listar_lembretes() -> str:
    itens = lembretes_pendentes()
    if not itens:
        return "Nenhum lembrete agendado."
    return "\n".join(f"{dt.datetime.fromisoformat(l['quando']):%d/%m %H:%M}: {l['texto']}" for l in itens)


def lembretes_vencidos() -> list[dict]:
    """Tira da lista e devolve os lembretes cuja hora chegou."""
    agora = cerebro.agora()
    with _trava:
        estado = _ler_estado()
        todos = estado.get("lembretes", [])
        vencidos = [l for l in todos if dt.datetime.fromisoformat(l["quando"]) <= agora]
        if vencidos:
            estado["lembretes"] = [l for l in todos if l not in vencidos]
            _salvar_estado(estado)
    return vencidos


# ---------- hábitos ----------

_HOJE = re.compile(r"(## Hoje\n)(.*?)(?=\n## |\nVolta para|\Z)", re.S)


def _habitos() -> tuple[cerebro.Nota, list[str], list[tuple[bool, str]]]:
    nota = cerebro.ler("HABITOS.md")
    pilares = re.findall(r"^- (.+)$", nota.corpo.split("## Pilares", 1)[1].split("##", 1)[0], re.M) \
        if "## Pilares" in nota.corpo else []
    m = _HOJE.search(nota.corpo)
    hoje = [(x.lower() == "x", t.strip()) for x, t in re.findall(r"^- \[( |x|X)\] (.+)$", m.group(2), re.M)] if m else []
    return nota, pilares, hoje


def habitos_hoje() -> list[dict]:
    return [{"pilar": t, "feito": feito} for feito, t in _habitos()[2]]


def habitos_pendentes() -> list[str]:
    return [t for feito, t in _habitos()[2] if not feito]


def marcar_habito(pilar: str) -> str:
    nota, _, hoje = _habitos()
    alvo = next((t for _, t in hoje if pilar.lower() in t.lower() or t.lower() in pilar.lower()), None)
    if not alvo:
        return f"Não achei o pilar '{pilar}'. Pilares de hoje: {', '.join(t for _, t in hoje)}."
    texto = nota.caminho.read_text(encoding="utf-8").replace(f"- [ ] {alvo}", f"- [x] {alvo}", 1)
    cerebro.escrever(nota.caminho, texto, hash_esperado=nota.hash)
    restantes = [t for feito, t in hoje if not feito and t != alvo]
    return f"Marquei '{alvo}' como feito hoje." + (f" Faltam: {', '.join(restantes)}." if restantes else f" Todos os pilares do dia estão completos, {config.TRATAMENTO}.")


def virar_dia_habitos(dia_anterior: str) -> bool:
    """Arquiva a lista de ontem em ## Histórico e começa uma nova com os pilares."""
    nota, pilares, hoje = _habitos()
    # Só vira se a lista é de um dia anterior (não mexida hoje); evita arquivar a lista de hoje.
    if not pilares or dt.date.fromtimestamp(nota.caminho.stat().st_mtime) >= cerebro.agora().date():
        return False
    texto = nota.caminho.read_text(encoding="utf-8")
    nova = "".join(f"- [ ] {p}\n" for p in pilares)
    feitos = sum(1 for f, _ in hoje if f)
    resumo = f"- {dia_anterior}: {feitos}/{len(hoje)} — " + ", ".join(("✔ " if f else "✘ ") + t for f, t in hoje) + "\n"
    texto = _HOJE.sub(lambda m: m.group(1) + nova, texto, count=1)
    if "## Histórico" in texto:
        texto = texto.replace("## Histórico\n", "## Histórico\n" + resumo, 1)
    else:
        texto = texto.replace("\nVolta para o [[00-mapa]].", f"\n## Histórico\n{resumo}\nVolta para o [[00-mapa]].", 1)
    cerebro.escrever(nota.caminho, texto, hash_esperado=nota.hash)
    return True


# ---------- contexto do dia ----------

def _prioridades_jarvis() -> list[str]:
    """Prioridades do briefing do JARVIS, só se o arquivo for de hoje."""
    try:
        if dt.date.fromtimestamp(BRIEFING_JARVIS.stat().st_mtime) != cerebro.agora().date():
            return []
        dados = json.loads(BRIEFING_JARVIS.read_text(encoding="utf-8"))
        return [p[0] for p in dados.get("prioridades", []) if p]
    except (OSError, ValueError, IndexError, TypeError):
        return []


def _pendencias_de_ontem() -> list[str]:
    ontem = cerebro.agora().date() - dt.timedelta(days=1)
    caminho = cerebro.raiz() / "diario" / f"{ontem:%Y-%m-%d}.md"
    if not caminho.exists():
        return []
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    return [re.sub(r"^\W+", "", l).strip() for l in linhas if re.search(r"pend[eê]ncia|falta|lembrar", l, re.I)][:6]


def contexto_do_dia() -> dict:
    from .ferramentas.computador import hora_data
    from .ferramentas.internet import clima
    try:
        tempo = clima(CIDADE)
    except Exception:
        tempo = ""
    hoje = cerebro.agora().date()
    return {
        "data": hora_data(),
        "clima": tempo,
        "lembretes_hoje": [l["texto"] + f" às {dt.datetime.fromisoformat(l['quando']):%H:%M}"
                           for l in lembretes_pendentes() if dt.datetime.fromisoformat(l["quando"]).date() == hoje],
        "habitos": habitos_pendentes(),
        "caixa_de_entrada": len(cerebro.pendentes()),
        "pendencias_de_ontem": _pendencias_de_ontem(),
        "prioridades_jarvis": _prioridades_jarvis(),
    }


# ---------- bom dia ----------

def bom_dia() -> str:
    """Briefing da manhã: clima, lembretes, hábitos, pendências e prioridades."""
    ctx = contexto_do_dia()
    prompt = (
        "Escreva o bom dia falado para o usuário, em no máximo 120 palavras, seguindo a ALMA. Use só os dados "
        "abaixo, sem inventar nada; pule o que estiver vazio. Ordem: saudação, clima, compromissos e lembretes, "
        "pendências, hábitos do dia e uma recomendação concreta para começar. Sem listas nem markdown: é texto "
        f"para ouvir.\n\n<dados>\n{json.dumps(ctx, ensure_ascii=False, indent=1)}\n</dados>"
    )
    try:
        from .agente import _sistema
        texto = ia.perguntar(prompt, _sistema(), "rapido").texto
    except ia.SemIA:
        partes = [f"Bom dia, {config.TRATAMENTO}. Hoje é {ctx['data']}"]
        if ctx["clima"]:
            partes.append(ctx["clima"])
        if ctx["lembretes_hoje"]:
            partes.append("Lembretes: " + "; ".join(ctx["lembretes_hoje"]))
        if ctx["caixa_de_entrada"]:
            partes.append(f"Há {ctx['caixa_de_entrada']} itens na caixa de entrada.")
        texto = " ".join(partes)
    cerebro.registrar_diario(f"Bom dia: {texto}", origem="proativo")
    return texto


# ---------- batimento ----------

def batimento() -> list[str]:
    """Olha o estado e devolve só os avisos novos (cada aviso sai uma vez por dia)."""
    agora = cerebro.agora()
    hoje = _hoje()
    with _trava:
        estado = _ler_estado()
        dados = estado.setdefault("batimento", {})
        if dados.get("dia") != hoje:
            dados.clear()
            dados.update({"dia": hoje, "avisados": [], "entrada": dados.get("entrada", 0)})
        avisos = []

        entrada = len(cerebro.pendentes())
        if entrada > dados.get("entrada", 0):
            avisos.append(f"Há {entrada} itens esperando na caixa de entrada. Posso organizá-los quando quiser.")
        dados["entrada"] = entrada

        if agora.hour >= HORA_COBRAR_HABITOS and "habitos" not in dados["avisados"]:
            faltam = habitos_pendentes()
            if faltam:
                avisos.append(f"Ainda dá tempo, {config.TRATAMENTO}: faltam hoje " + ", ".join(faltam) + ".")
            dados["avisados"].append("habitos")

        _salvar_estado(estado)
    return avisos


# ---------- reflexão diária ----------

ESQUEMA_REFLEXAO = {
    "type": "object",
    "properties": {
        "decisoes": {"type": "array", "items": {"type": "string"}},
        "licoes": {"type": "array", "items": {"type": "string"}},
        "fatos": {"type": "array", "items": {"type": "string"}},
        "sugestoes_alma": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decisoes", "licoes", "fatos", "sugestoes_alma"],
    "additionalProperties": False,
}
SECOES = {"decisoes": "## Decisões", "licoes": "## Lições", "fatos": "## Fatos importantes"}


def refletir(dia: str | None = None) -> str:
    """Revê o diário de um dia (padrão: ontem) e promove o que importa para a MEMORIA.

    A ALMA nunca é alterada: sugestões de mudança de personalidade vão para o diário.
    """
    dia = dia or f"{cerebro.agora().date() - dt.timedelta(days=1):%Y-%m-%d}"
    caminho = cerebro.raiz() / "diario" / f"{dia}.md"
    if not caminho.exists():
        return f"Não há diário de {dia} para revisar."
    memoria = cerebro.ler("MEMORIA.md")
    prompt = (
        f"<diario dia=\"{dia}\">\n{cerebro.ler(caminho).corpo}\n</diario>\n\n"
        f"<memoria_atual>\n{memoria.corpo}\n</memoria_atual>\n\n"
        "Você está fazendo a revisão noturna, como o sono faz com a memória. Do diário, extraia só o que "
        "vale para sempre e ainda NÃO está na memória atual: decisões, lições aprendidas e fatos importantes "
        "sobre o usuário ou os projetos. Uma frase curta cada, citando notas como [[Título]]. Seja exigente: "
        "conversa casual, clima e hora não entram. Em sugestoes_alma, só se houver pedido explícito de "
        "mudança de jeito ou tom. Listas vazias são uma resposta válida."
    )
    r = ia.perguntar(prompt, modo="profundo", esquema=ESQUEMA_REFLEXAO)
    dados = r.dados or {}
    texto = memoria.caminho.read_text(encoding="utf-8")
    novos = 0
    for chave, secao in SECOES.items():
        itens = [i.strip() for i in dados.get(chave, []) if i.strip() and i.strip() not in texto]
        if not itens:
            continue
        bloco = "".join(f"- {dia}: {i}\n" for i in itens)
        if secao in texto:
            texto = texto.replace(f"{secao}\n", f"{secao}\n{bloco}", 1)
        else:
            texto = texto.replace("\nVolta para o [[00-mapa]].", f"\n{secao}\n{bloco}\nVolta para o [[00-mapa]].", 1)
        novos += len(itens)
    if novos:
        cerebro.escrever(memoria.caminho, texto, hash_esperado=memoria.hash)
    sugestoes = dados.get("sugestoes_alma", [])
    resumo = f"Reflexão de {dia}: {novos} item(ns) novo(s) na [[MEMORIA]]."
    if sugestoes:
        resumo += "\nSugestões para a [[ALMA]] (só você altera): " + "; ".join(sugestoes)
    cerebro.registrar_diario(resumo, origem=f"reflexao/{r.provedor}")
    return resumo


# ---------- agendador ----------

_reserva = None


def reservar_vigia() -> bool:
    """Garante uma vigia só no PC (a de inicialização e a do painel não podem rodar juntas).

    A trava é um arquivo bloqueado enquanto o processo vive; se o processo morrer, o sistema solta.
    """
    global _reserva
    if _reserva is not None:
        return True
    config.DADOS.mkdir(parents=True, exist_ok=True)
    arquivo = open(config.DADOS / "vigia.trava", "a+")
    try:
        if os.name == "nt":
            import msvcrt
            arquivo.seek(0)
            msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        arquivo.close()
        return False
    _reserva = arquivo
    (config.DADOS / "vigia.pid").write_text(str(os.getpid()), encoding="utf-8")
    return True


def parar_vigia() -> str:
    """Encerra a vigia que está rodando em segundo plano (a da inicialização ou a do painel)."""
    if reservar_vigia():
        return "Nenhuma vigia estava rodando."   # conseguiu a trava: não havia outra
    try:
        pid = int((config.DADOS / "vigia.pid").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "Há uma vigia rodando, mas não sei qual processo é. Feche o pythonw.exe no Gerenciador de Tarefas."
    try:
        import signal
        os.kill(pid, signal.SIGTERM)   # no Windows, SIGTERM encerra o processo (TerminateProcess)
    except OSError as e:
        return f"Não consegui encerrar a vigia (processo {pid}): {e}"
    return f"Vigia encerrada (processo {pid})."


class Vigia:
    """Roda em segundo plano: lembretes, bom dia, virada do dia (hábitos + reflexão) e batimento."""

    def __init__(self, ao_avisar: Callable[[str], None] | None = None):
        self.ao_avisar = ao_avisar or (lambda texto: avisar(texto))
        self.ativo = True
        self._ultimo_batimento = 0.0

    def _uma_vez_por_dia(self, chave: str) -> bool:
        with _trava:
            estado = _ler_estado()
            feitos = estado.setdefault("feito", {})
            if feitos.get(chave) == _hoje():
                return False
            feitos[chave] = _hoje()
            _salvar_estado(estado)
        return True

    def passo(self) -> None:
        agora = cerebro.agora()
        for lembrete in lembretes_vencidos():
            self.ao_avisar(f"Lembrete, {config.TRATAMENTO}: {lembrete['texto']}")

        if agora.hour >= 4 and self._uma_vez_por_dia("virada"):
            ontem = f"{agora.date() - dt.timedelta(days=1):%Y-%m-%d}"
            try:
                virar_dia_habitos(ontem)
                if ia.disponiveis():
                    refletir(ontem)
            except Exception as e:
                cerebro.registrar_diario(f"A virada do dia falhou: {type(e).__name__}: {e}", origem="proativo")

        h, m = (int(x) for x in HORA_BOM_DIA.split(":"))
        if (agora.hour, agora.minute) >= (h, m) and agora.hour < 12 and self._uma_vez_por_dia("bom_dia"):
            self.ao_avisar(bom_dia())

        if HORARIO_ATIVO[0] <= agora.hour < HORARIO_ATIVO[1] and \
                time.monotonic() - self._ultimo_batimento >= INTERVALO_BATIMENTO:
            self._ultimo_batimento = time.monotonic()
            for aviso in batimento():
                self.ao_avisar(aviso)

    def rodar(self, intervalo: float = 30) -> None:
        while self.ativo:
            try:
                self.passo()
            except Exception as e:
                print(f"[vigia] {type(e).__name__}: {e}")
            time.sleep(intervalo)
