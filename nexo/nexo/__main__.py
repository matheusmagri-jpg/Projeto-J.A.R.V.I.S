"""Linha de comando do NEXO.  Uso: python -m nexo <comando> [...]

  conversar [--modo rapido|profundo] [--privado]     conversa com ferramentas
  voz [--continuo] [--modo ...] [--privado]          conversa por voz (Enter para falar)
  falar "texto"                                      fala um texto com a voz da assistente
  painel [--mudo] [--porta 8765]                     interface com anel, conversa e grafo ao vivo
  vigia [--falar]                                    proatividade em segundo plano (o painel já inclui)
  inicializacao ativar|desativar|status|icone [--admin]  vigia ao entrar no Windows; icone = JARVIS na Área de Trabalho
  bom-dia [--falar] / refletir [--dia] / batimento   rodam uma parte da proatividade agora
  lembrar "texto" --minutos N | --horario HH:MM      agenda um lembrete; lembretes lista
  perguntar "texto" [--modo rapido|profundo|dupla]   responde usando o cérebro
  guardar "texto"                                    joga na caixa de entrada
  organizar                                          transforma a entrada em notas ligadas
  buscar "termos"                                    procura no cérebro
  diario "texto"                                     escreve no diário de hoje
  nota <pessoa|projeto|ideia|decisao> "título" "conteúdo"
  aprender <link do GitHub | pasta>                  aprende um repositório ou pasta (base de conhecimento)
  conhecimento ["pergunta"]                          lista as fontes aprendidas ou busca nelas
  fish login | status | testar "texto"  voz do Jarvis pelo site do Fish Audio (conta do Matheus)
  myhub login | status | perguntar "..." [--modelo]  consulta as IAs da assinatura MyHub.IA
  checar                                             links quebrados e notas soltas
  ia                                                 mostra quais IAs estão configuradas
  contexto                                           (hook) imprime a memória para o Claude Code
  sessao-fim                                         (hook) resume a sessão do Claude Code no diário
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

from . import agente, busca, cerebro, config, ia


def _utf8() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except AttributeError:
            pass


def cmd_perguntar(a):
    ia.preaquecer_async()
    r = agente.responder(a.texto, a.modo)
    print(r.texto)
    print(f"\n[{r.provedor}]", file=sys.stderr)


def cmd_guardar(a):
    p = cerebro.guardar(a.texto, origem=a.origem)
    print(f"Guardado em {p.relative_to(config.CEREBRO).as_posix()}")


def cmd_organizar(a):
    feitos = agente.organizar_entrada(a.modo)
    print("\n".join(f"Organizado: {t}" for t in feitos) or "A caixa de entrada está vazia.")


def cmd_buscar(a):
    resultados = busca.buscar(a.texto, a.limite)
    if not resultados:
        print("Nada encontrado.")
    for r in resultados:
        print(f"[[{r.titulo}]]  ({r.rel})\n    {r.trecho}")


def cmd_diario(a):
    cerebro.registrar_diario(a.texto, origem=a.origem)
    print("Anotado no diário de hoje.")


def cmd_nota(a):
    p = cerebro.criar_nota(a.tipo, a.titulo, a.conteudo)
    print(f"Nota em {p.relative_to(config.CEREBRO).as_posix()}")


def cmd_checar(a):
    problemas = cerebro.checar()
    total = 0
    for nome, itens in problemas.items():
        print(f"{nome.replace('_', ' ')}: {len(itens)}")
        for i in itens:
            print(f"  - {i}")
        total += len(itens)
    sys.exit(1 if total else 0)


def cmd_ia(a):
    ativos = ia.disponiveis()
    print(f"Claude ({config.CLAUDE_MODELO}): {'configurado' if 'claude' in ativos else 'sem chave'}")
    print(f"Gemini ({config.GEMINI_MODELO}): {'configurado' if 'gemini' in ativos else 'sem chave'}")
    if a.testar:
        for nome in ativos:
            try:
                r = ia.perguntar("Responda só: pronto.", modo="rapido" if nome == "gemini" else "profundo")
                print(f"  teste: respondeu via {r.provedor}: {r.texto[:60]}")
            except ia.SemIA as e:
                print(f"  teste falhou: {e}")


def cmd_contexto(a):
    print(f"# Cérebro da {config.NOME} (carregado automaticamente)\n")
    print(f"Vault: {config.CEREBRO}\n")
    print(cerebro.contexto_nucleo())
    print("\nPara consultar o cérebro: `python -m nexo buscar \"termos\"`. "
          "Para guardar algo: `python -m nexo guardar \"texto\"`. Veja CLAUDE.md.")


def cmd_sessao_fim(a):
    """Hook SessionEnd: dispara o resumo em segundo plano para não atrasar o Claude Code."""
    try:
        dados = json.load(sys.stdin)
    except ValueError:
        return
    transcript = dados.get("transcript_path")
    if not transcript:
        return
    opcoes = {}
    if os.name == "nt":
        opcoes["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        opcoes["start_new_session"] = True
    subprocess.Popen([sys.executable, "-m", "nexo", "resumir-sessao", transcript,
                      dados.get("session_id", "")], cwd=config.RAIZ,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **opcoes)


AJUDA_CONVERSA = """Comandos: /modo rapido|profundo  /privado  /ferramentas  /sair
Tudo o mais é conversa com a assistente."""


def _confirmar_no_terminal(pergunta: str) -> bool:
    try:
        return input(f"  {config.NOME} pede confirmação: {pergunta} (s/n) ").strip().lower() in ("s", "sim")
    except EOFError:
        return False


def cmd_conversar(a):
    from .conversa import Conversa
    ia.preaquecer_async()
    c = Conversa(modo=a.modo, privado=a.privado, confirmar=_confirmar_no_terminal)
    ativos = ia.disponiveis()
    if not ativos:
        raise ia.SemIA("Nenhuma chave de IA configurada. Preencha o .env.")
    print(f"{config.NOME} pronta (IAs: {', '.join(ativos)}; modo {c.modo}"
          f"{'; privado' if c.privado else ''}). /ajuda para comandos.")
    try:
        while True:
            try:
                texto = input("\nVocê: ").strip()
            except EOFError:
                break
            if not texto:
                continue
            if texto in ("/sair", "/s", "sair"):
                break
            if texto == "/ajuda":
                print(AJUDA_CONVERSA)
            elif texto.startswith("/modo"):
                novo = texto.split()[-1]
                if novo in ia.ORDEM:
                    c.modo = novo
                print(f"Modo: {c.modo}")
            elif texto == "/privado":
                c.privado = not c.privado
                print("Modo privado " + ("ligado: nada desta conversa vai para o diário." if c.privado else "desligado."))
            elif texto == "/ferramentas":
                for f in c.ferramentas.values():
                    print(f"  {f.nome}{' (pede confirmação)' if f.confirmar else ''}: {f.descricao}")
            else:
                try:
                    t = c.enviar(texto)
                except ia.SemIA as e:
                    print(f"{config.NOME}: {e}")
                    continue
                for acao in t.acoes:
                    print(f"  · {acao}")
                print(f"{config.NOME}: {t.texto}\n  [{t.provedor}]")
    except KeyboardInterrupt:
        pass
    finally:
        c.encerrar()
        print(f"\nAté logo, {config.TRATAMENTO}.")


def cmd_voz(a):
    """Conversa por voz. Padrão: Enter para falar. --continuo: escuta sempre e atende quando chamam pelo nome."""
    from . import voz
    from .conversa import Conversa
    ia.preaquecer_async()

    if not ia.disponiveis():
        raise ia.SemIA("Nenhuma chave de IA configurada. Preencha o .env.")
    print("Medindo o ruído da sala, um instante em silêncio...")
    limiar = voz.calibrar()

    def escutar(espera: float = 8.0) -> str:
        audio = voz.ouvir(limiar, espera)
        if not audio:
            return ""
        try:
            return voz.transcrever(audio)
        except Exception as e:
            print(f"  (não consegui transcrever: {type(e).__name__})")
            return ""

    def confirmar_por_voz(pergunta: str) -> bool:
        voz.falar(f"{pergunta} Diga sim ou não.")
        print(f"  {config.NOME} pede confirmação: {pergunta}")
        resposta = escutar(6.0)
        print(f"  Você: {resposta or '(silêncio)'}")
        return voz.e_sim(resposta)

    c = Conversa(modo=a.modo, privado=a.privado, confirmar=confirmar_por_voz)
    if a.continuo:
        local = "detector local (Vosk), sem gastar cota" if voz.detector_disponivel() else \
            "sem o modelo Vosk: cada frase é transcrita pela internet"
        print(f'Modo contínuo: comece a frase com "{config.NOME}" ({local}). Ctrl+C para sair.')
    else:
        print("Aperte Enter e fale (ou digite e Enter). Escreva /sair para encerrar.")
    voz.falar(f"Às suas ordens, {config.TRATAMENTO}.")
    try:
        while True:
            if a.continuo:
                pedido = voz.proxima_chamada(escutar)
                if pedido is None:
                    continue
                if not pedido:
                    voz.falar(f"Pois não, {config.TRATAMENTO}?")
                    pedido = escutar()
            else:
                digitado = input("\n[Enter para falar] ").strip()
                if digitado in ("/sair", "sair"):
                    break
                if digitado:
                    pedido = digitado
                else:
                    print("  ouvindo...")
                    pedido = escutar()
            if not pedido:
                print("  (não ouvi nada)")
                continue
            print(f"Você: {pedido}")
            if re.fullmatch(r"\W*(tchau|pode desligar a voz|encerrar|sair)\W*", pedido, re.I):
                break
            try:
                t = c.enviar(pedido)
            except ia.SemIA as e:
                print(f"{config.NOME}: {e}")
                voz.falar(f"Desculpe, {config.TRATAMENTO}, as inteligências artificiais não responderam.")
                continue
            for acao in t.acoes:
                print(f"  · {acao}")
            print(f"{config.NOME}: {t.texto}\n  [{t.provedor}]")
            voz.falar(t.texto)
    except KeyboardInterrupt:
        pass
    finally:
        c.encerrar()
        voz.falar(f"Até logo, {config.TRATAMENTO}.")


def cmd_painel(a):
    if a.parar:
        import psutil
        meus = [p for p in psutil.process_iter(["pid", "cmdline"])
                if p.info["pid"] != os.getpid() and "nexo" in (p.info["cmdline"] or []) and "painel" in (p.info["cmdline"] or [])]
        for p in meus:
            p.kill()
        print(f"Painel encerrado ({len(meus)} processo(s))." if meus else "O painel não estava rodando.")
        return
    if sys.stdout is None:
        # Aberto pelo ícone (pythonw, sem console): o que der errado fica em dados/painel.log.
        import faulthandler
        config.DADOS.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(config.DADOS / "painel.log", "a", encoding="utf-8", buffering=1)
        faulthandler.enable(sys.stderr)
        import ctypes
        admin = bool(ctypes.windll.shell32.IsUserAnAdmin()) if os.name == "nt" else False
        print(f"[{cerebro.agora():%Y-%m-%d %H:%M:%S}] painel iniciando (pid {os.getpid()}, "
              f"administrador: {'sim' if admin else 'não'}, pasta {os.getcwd()})")
    from .interface import servidor
    ia.preaquecer_async()
    servidor.iniciar(porta=a.porta, modo=a.modo, privado=a.privado, falar=not a.mudo, abrir=not a.sem_janela)


def _media(ns):
    return sum(ns) / len(ns) if ns else 0.0


def cmd_benchmark(a):
    """Mede latência fria/quente para IA, cache semântico e busca local."""
    from . import agente as _agente
    from . import busca as _busca

    ia.preaquecer_async(forcar=True)
    time.sleep(0.15)

    saida = {"modo": a.modo, "rodadas": a.rodadas}

    t0 = time.perf_counter()
    frio = ia.perguntar("Responda só com: pronto.", modo=a.modo)
    t1 = time.perf_counter()
    tempos_quentes = []
    for _ in range(a.rodadas):
        i = time.perf_counter()
        ia.perguntar("Responda só com: pronto.", modo=a.modo)
        tempos_quentes.append(time.perf_counter() - i)
    saida["ia"] = {
        "provedor_frio": frio.provedor,
        "frio_ms": round((t1 - t0) * 1000, 1),
        "quente_medio_ms": round(_media(tempos_quentes) * 1000, 1),
        "ganho_pct": round((1 - (_media(tempos_quentes) / max(t1 - t0, 1e-9))) * 100, 1),
    }

    _agente._cache_semantico.clear()
    pergunta_a = "quem edita meus videos do canal"
    pergunta_b = "quem edita meus vídeos no canal"
    i = time.perf_counter()
    r1 = _agente.responder(pergunta_a, modo=a.modo, registrar=False)
    t_a = time.perf_counter() - i
    i = time.perf_counter()
    r2 = _agente.responder(pergunta_b, modo=a.modo, registrar=False)
    t_b = time.perf_counter() - i
    saida["cache_semantico"] = {
        "primeira_ms": round(t_a * 1000, 1),
        "segunda_ms": round(t_b * 1000, 1),
        "ganho_pct": round((1 - (t_b / max(t_a, 1e-9))) * 100, 1),
        "provedores": [r1.provedor, r2.provedor],
    }

    t = []
    i = time.perf_counter()
    _busca.buscar("sexta feira memoria", limite=5)
    t.append(time.perf_counter() - i)
    quentes = []
    for _ in range(a.rodadas):
        i = time.perf_counter()
        _busca.buscar("sexta feira memoria", limite=5)
        quentes.append(time.perf_counter() - i)
    saida["busca"] = {
        "frio_ms": round(t[0] * 1000, 1),
        "quente_medio_ms": round(_media(quentes) * 1000, 1),
        "ganho_pct": round((1 - (_media(quentes) / max(t[0], 1e-9))) * 100, 1),
    }

    print(json.dumps(saida, ensure_ascii=False, indent=2))


def cmd_bom_dia(a):
    from . import proativo
    texto = proativo.bom_dia()
    print(texto)
    if a.falar:
        from . import voz
        voz.falar(texto)


def cmd_refletir(a):
    from . import proativo
    print(proativo.refletir(a.dia))


def cmd_batimento(a):
    from . import proativo
    avisos = proativo.batimento()
    print("\n".join(avisos) or "Nada novo para avisar.")


def cmd_lembrar(a):
    from . import proativo
    print(proativo.lembrar(a.texto, a.minutos, a.horario))


def cmd_lembretes(a):
    from . import proativo
    print(proativo.listar_lembretes())


def cmd_vigia(a):
    """Fica rodando: lembretes, bom dia, virada do dia e batimento. Avisa por notificação (e voz)."""
    from . import proativo

    def ao_avisar(texto: str) -> None:
        print(f"[{cerebro.agora():%Y-%m-%d %H:%M}] {texto}")
        proativo.avisar(texto)
        if a.falar:
            from . import voz
            voz.falar(texto)

    if a.parar:
        print(proativo.parar_vigia())
        return
    sem_janela = sys.stdout is None
    if sem_janela:
        # Iniciada sem janela (pythonw, na inicialização do Windows): registra num arquivo.
        config.DADOS.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(config.DADOS / "vigia.log", "a", encoding="utf-8", buffering=1)
    if not proativo.reservar_vigia():
        print(f"[{cerebro.agora():%Y-%m-%d %H:%M}] Já existe uma vigia rodando; esta não foi iniciada.")
        return
    print(f"[{cerebro.agora():%Y-%m-%d %H:%M}] {config.NOME} vigiando "
          f"(bom dia às {proativo.HORA_BOM_DIA}"
          f"{'; para encerrar: python -m nexo vigia --parar' if sem_janela else '; Ctrl+C para sair'}).")
    try:
        proativo.Vigia(ao_avisar).rodar()
    except KeyboardInterrupt:
        pass


def cmd_inicializacao(a):
    from . import inicializacao
    acao = {"ativar": inicializacao.ativar, "desativar": inicializacao.desativar, "status": inicializacao.estado,
            "icone": lambda: inicializacao.criar_icone_painel(admin=a.admin)}
    print(acao[a.acao]())


def cmd_aprender(a):
    from . import conhecimento
    try:
        print(conhecimento.aprender(a.origem))
    except conhecimento.ErroConhecimento as e:
        print(e, file=sys.stderr)
        sys.exit(1)


def cmd_conhecimento(a):
    from . import conhecimento
    if a.pergunta:
        print(conhecimento.contexto(a.pergunta))
    else:
        print(conhecimento.listar())


def cmd_fish(a):
    from . import fishsite
    if a.acao == "login":
        print(fishsite.login())
    elif a.acao == "status":
        print(fishsite.estado())
    else:
        from . import voz
        texto = a.texto or f"Pois não, {config.TRATAMENTO}?"
        arquivo = voz.gerar_mp3(voz.para_fala(texto))
        print(f"Áudio: {arquivo}  (motores na ordem: {[m[0] for m in voz.motores()]})")
        if arquivo:
            voz._tocar_mp3(arquivo)


def cmd_myhub(a):
    from . import myhub
    if a.acao == "login":
        print(f"Abrindo o Chrome do {config.NOME} no MyHub (perfil só dele). Entre com a sua conta.")
        print(myhub.login())
    elif a.acao == "status":
        print(myhub.estado())
    else:
        if not a.texto:
            sys.exit('Use: python -m nexo myhub perguntar "sua pergunta" [--modelo "GPT-6 Luna"]')
        try:
            r = myhub.perguntar(a.texto, a.modelo)
        except myhub.ErroMyHub as e:
            sys.exit(str(e))
        print(f"[{r['modelo']}]\n{r['texto']}")


def cmd_falar(a):
    from . import voz
    voz.falar(a.texto)


def cmd_resumir_sessao(a):
    from . import sessao
    sessao.resumir(a.transcript, a.sessao)


def main(argv=None):
    _utf8()
    p = argparse.ArgumentParser(prog="nexo", description=f"{config.NOME}: assistente com segundo cérebro (NEXO).")
    sub = p.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("perguntar"); s.add_argument("texto")
    s.add_argument("--modo", default="rapido", choices=["rapido", "profundo", "dupla"])
    s.set_defaults(f=cmd_perguntar)

    s = sub.add_parser("conversar")
    s.add_argument("--modo", default="rapido", choices=["rapido", "profundo"])
    s.add_argument("--privado", action="store_true")
    s.set_defaults(f=cmd_conversar)

    s = sub.add_parser("voz")
    s.add_argument("--modo", default="rapido", choices=["rapido", "profundo"])
    s.add_argument("--privado", action="store_true")
    s.add_argument("--continuo", action="store_true", help="escuta sempre e atende frases que começam com o nome da assistente")
    s.set_defaults(f=cmd_voz)

    s = sub.add_parser("falar"); s.add_argument("texto"); s.set_defaults(f=cmd_falar)

    s = sub.add_parser("aprender"); s.add_argument("origem", help="link do GitHub ou pasta local")
    s.set_defaults(f=cmd_aprender)
    s = sub.add_parser("conhecimento"); s.add_argument("pergunta", nargs="?", default="")
    s.set_defaults(f=cmd_conhecimento)

    s = sub.add_parser("fish"); s.add_argument("acao", choices=["login", "status", "testar"])
    s.add_argument("texto", nargs="?", default=""); s.set_defaults(f=cmd_fish)
    s = sub.add_parser("myhub"); s.add_argument("acao", choices=["login", "perguntar", "status"])
    s.add_argument("texto", nargs="?", default=""); s.add_argument("--modelo", default="")
    s.set_defaults(f=cmd_myhub)

    s = sub.add_parser("bom-dia"); s.add_argument("--falar", action="store_true"); s.set_defaults(f=cmd_bom_dia)
    s = sub.add_parser("refletir"); s.add_argument("--dia", help="AAAA-MM-DD (padrão: ontem)")
    s.set_defaults(f=cmd_refletir)
    sub.add_parser("batimento").set_defaults(f=cmd_batimento)
    s = sub.add_parser("lembrar"); s.add_argument("texto")
    s.add_argument("--minutos", type=int, default=0); s.add_argument("--horario", default="")
    s.set_defaults(f=cmd_lembrar)
    sub.add_parser("lembretes").set_defaults(f=cmd_lembretes)
    s = sub.add_parser("vigia"); s.add_argument("--falar", action="store_true")
    s.add_argument("--parar", action="store_true", help="encerra a vigia que está rodando")
    s.set_defaults(f=cmd_vigia)
    s = sub.add_parser("inicializacao"); s.add_argument("acao", choices=["ativar", "desativar", "status", "icone"])
    s.add_argument("--admin", action="store_true", help="icone: o painel abre como administrador (pede UAC)")
    s.set_defaults(f=cmd_inicializacao)

    s = sub.add_parser("painel")
    s.add_argument("--porta", type=int, default=8765)
    s.add_argument("--modo", default="rapido", choices=["rapido", "profundo"])
    s.add_argument("--privado", action="store_true")
    s.add_argument("--mudo", action="store_true", help="não fala as respostas")
    s.add_argument("--sem-janela", action="store_true", help="não abre o navegador")
    s.add_argument("--parar", action="store_true", help="encerra o painel que está rodando em segundo plano")
    s.set_defaults(f=cmd_painel)

    s = sub.add_parser("guardar"); s.add_argument("texto"); s.add_argument("--origem", default="nexo")
    s.set_defaults(f=cmd_guardar)

    s = sub.add_parser("organizar")
    s.add_argument("--modo", default="profundo", choices=["rapido", "profundo", "dupla"])
    s.set_defaults(f=cmd_organizar)

    s = sub.add_parser("buscar"); s.add_argument("texto"); s.add_argument("--limite", type=int, default=5)
    s.set_defaults(f=cmd_buscar)

    s = sub.add_parser("diario"); s.add_argument("texto"); s.add_argument("--origem", default="nexo")
    s.set_defaults(f=cmd_diario)

    s = sub.add_parser("nota"); s.add_argument("tipo", choices=list(cerebro.TIPOS))
    s.add_argument("titulo"); s.add_argument("conteudo"); s.set_defaults(f=cmd_nota)

    sub.add_parser("checar").set_defaults(f=cmd_checar)

    s = sub.add_parser("ia"); s.add_argument("--testar", action="store_true"); s.set_defaults(f=cmd_ia)

    s = sub.add_parser("benchmark")
    s.add_argument("--modo", default="rapido", choices=["rapido", "profundo"])
    s.add_argument("--rodadas", type=int, default=4)
    s.set_defaults(f=cmd_benchmark)

    sub.add_parser("contexto").set_defaults(f=cmd_contexto)
    sub.add_parser("sessao-fim").set_defaults(f=cmd_sessao_fim)

    s = sub.add_parser("resumir-sessao"); s.add_argument("transcript"); s.add_argument("sessao", nargs="?", default="")
    s.set_defaults(f=cmd_resumir_sessao)

    a = p.parse_args(argv)
    try:
        a.f(a)
    except ia.SemIA as e:
        print(f"{config.NOME}: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
