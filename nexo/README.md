# Sexta-Feira (projeto NEXO)

A Sexta-Feira é uma assistente pessoal em português com um segundo cérebro em Obsidian, usando Claude, Gemini e Ollama local. O mesmo cérebro serve ao Claude Code.

## Instalar

```bash
pip install -r requirements.txt
```

Abra o arquivo `.env` e cole suas chaves:

- `GEMINI_API_KEY`: aistudio.google.com → Get API key
- `ANTHROPIC_API_KEY`: platform.claude.com → API Keys

Opcional (sem API key, tudo local):

- `NEXO_OLLAMA_ATIVO=1`
- `NEXO_OLLAMA_URL=http://127.0.0.1:11434`
- `NEXO_OLLAMA_MODELO=qwen2.5:3b`

Confira com `python -m nexo ia --testar`.

Otimizações de velocidade (padrão ligado):

- pré-aquecimento das IAs em segundo plano (`NEXO_IA_PREAQUECER=1`)
- cache semântico curto para perguntas parecidas (`NEXO_CACHE_SEMANTICO_ATIVO=1`)

## Ver o cérebro

No Obsidian: **Abrir pasta como cofre** → escolha `cerebro/` → **Visualização em gráfico**. O `00-mapa` é o nó central.

## Usar

```bash
python -m nexo conversar           # conversa no terminal (/ajuda mostra os comandos)
python -m nexo guardar "A Ana vai editar os vídeos do canal a partir de novembro"
python -m nexo organizar            # a IA transforma a entrada em notas ligadas
python -m nexo perguntar "quem edita meus vídeos?"
python -m nexo perguntar "o que falta na Sexta-Feira?" --modo dupla
python -m nexo benchmark --modo rapido
python -m nexo buscar "briefing"
python -m nexo checar               # links quebrados e notas soltas
```

Modos de IA: `rapido` (Ollama local primeiro, com Gemini e Claude de reserva), `profundo` (Ollama local primeiro, com Claude e Gemini de reserva) e `dupla` (as IAs disponíveis respondem e a principal junta).

## Painel (interface)

**Ícone na Área de Trabalho:** clique duas vezes em **JARVIS** para abrir o painel (sem janela de terminal). Clicar de novo com ele aberto só reabre a janela. Fechar a janela deixa o painel rodando em segundo plano, leve e pronto para o próximo clique; para desligar de vez: `python -m nexo painel --parar`. Para recriar o ícone: `python -m nexo inicializacao icone` (com `--admin`, o painel abre como administrador: o Windows pede confirmação a cada clique e tudo o que o Jarvis abrir herda o acesso total).

**No painel:**
- **Ctrl+Alt+J** de qualquer programa traz o painel para a frente com o cursor no chat; apertar de novo com ele na frente liga o microfone. Troque em `NEXO_TECLA` (ex.: `ctrl+shift+space`; `nenhum` desliga).
- **⏻ LIGADO/DESLIGADO** no topo: desligado, o Jarvis não conversa nem escuta, a escuta contínua desliga e a vigia para (também a da inicialização do Windows). Ligar de novo põe a vigia para rodar dentro do painel.
- **Acesso Rápido** tem os sites Briefing, CBTECH local e CBTECH site (lista em `SITES`, no `servidor.py`).
- **GALO**: colocação do Atlético Mineiro no Brasileirão e os próximos jogos (todas as competições), da API pública da ESPN, atualizados a cada 30 min. Outro time: `NEXO_TIME_ESPN`.
- **Agir na tela**: peça "clique no botão Salvar", "digite ... no campo" ou "aperte ctrl+s". O Jarvis pede confirmação, minimiza o painel e age no programa de trás (para clicar, uma foto da tela vai ao Gemini, que acha o alvo).

```bash
python -m nexo painel             # abre a Sexta-Feira numa janela do Google Chrome
python -m nexo painel --mudo      # sem falar as respostas
```

- Visual de HUD holográfico (ciano e laranja, estilo painel de IA de filme, desenho original): mostrador da Sexta-Feira que gira e muda de cor conforme ela ouve, pensa ou fala; painel do sistema (CPU, memória, disco, bateria); acesso rápido; relógio com a semana; clima; medidor de hábitos (clique num pilar para marcar) e lembretes.
- O cérebro aparece como grafo ao vivo, como no Obsidian. Enquanto a Sexta-Feira responde, as notas que ela consulta acendem e as ligações ganham partículas. Notas novas (criadas por ela, pelo Claude Code ou por você no Obsidian) surgem sozinhas, já acesas.
- O anel muda de cor conforme o estado: roxo parado, verde ouvindo, âmbar pensando, lilás falando.
- Escreva ou clique no microfone para falar. "Escuta contínua" atende frases que começam com "Sexta-Feira".
- Links [[assim]] nas respostas são clicáveis e levam até a nota no grafo; clicar num ponto do grafo prepara uma pergunta sobre aquela nota.
- Ações que pedem confirmação abrem uma janela com Sim/Não.
- Roda só no seu PC (127.0.0.1:8765). Sem Chrome, abre no Edge; sem os dois, no navegador padrão. O grafo usa a biblioteca force-graph pela internet.

## Proatividade

A Sexta-Feira não espera ser chamada. Com o painel aberto (ou `python -m nexo vigia` rodando), ela:

- **Lembra na hora:** "me lembra daqui a 20 minutos de beber água" ou "às 14:30 da reunião". Avisa com notificação do Windows e, no painel, na tela e em voz alta.
- **Dá bom dia** às 07:45 (mude com `NEXO_BOM_DIA=07:30`): clima da sua cidade (`NEXO_CIDADE=Brasília`), lembretes do dia, pendências de ontem, hábitos, itens na caixa de entrada e as prioridades do briefing do JARVIS quando o `data.json` for do dia.
- **Cuida dos hábitos:** "fui à academia" marca o pilar Saúde. Às 18h, se faltar algum, ela cobra uma vez. Toda manhã a lista de ontem vai para `## Histórico` em `HABITOS.md` e uma nova começa.
- **Faz a reflexão diária:** relê o diário de ontem e promove para a `MEMORIA.md` só decisões, lições e fatos que valem para sempre (sem repetir). A `ALMA.md` nunca é alterada: se houver pedido de mudança de jeito, vira sugestão no diário.
- **Batimento a cada 30 minutos** (8h às 22h): avisa quando chegam itens novos na caixa de entrada. Cada aviso sai uma vez por dia.

### Início automático

A vigia inicia sozinha quando você entra no Windows, sem janela, por um atalho na pasta Inicializar. Só uma vigia roda por vez: se ela já estiver ativa, o painel não abre outra, e os avisos chegam por notificação do Windows.

```bash
python -m nexo inicializacao status      # ligado ou desligado
python -m nexo inicializacao desativar   # remove o atalho
python -m nexo vigia --parar             # encerra a vigia que está rodando agora
```

O registro do que ela fez fica em `dados/vigia.log`.

Comandos avulsos: `python -m nexo bom-dia --falar`, `refletir [--dia 2026-10-26]`, `batimento`, `lembrar "texto" --minutos 10`, `lembretes`.

## Voz

```bash
python -m nexo voz                # aperte Enter e fale; ela responde falando
python -m nexo voz --continuo     # escuta sempre e atende frases que começam com "Sexta-Feira"
python -m nexo falar "Bom dia, boss."
```

- Fala com voz neural em português (Edge TTS, gratuita; padrão `pt-BR-FranciscaNeural`). Troque em `.env` com `NEXO_VOZ=pt-BR-AntonioNeural` (masculina) ou `pt-BR-ThalitaMultilingualNeural`, e a velocidade com `NEXO_VOZ_VELOCIDADE=-5%`. Sem internet, usa a voz do Windows.
- Ouve pelo microfone padrão: mede o ruído da sala ao iniciar, grava enquanto você fala e para depois de quase 1 segundo de silêncio. A transcrição é feita pelo Gemini (modelos "lite", para poupar a cota da conversa).
- Ações que pedem confirmação são perguntadas em voz alta: responda "sim" ou "não".
- Diga "tchau" ou "encerrar" para sair.
- No modo contínuo, um detector local (Vosk, modelo pequeno em português em `modelos/`) escuta o microfone sem internet e só acorda quando uma frase **começa** com "Sexta-Feira" (ou "Ei, Sexta-Feira"). Só essa frase vai para a transcrição; o resto nunca sai do computador. "Hoje é sexta-feira" no meio da conversa não a acorda: o nome precisa abrir a frase. Para trocar o nome, use `NEXO_NOME` no `.env` (as palavras precisam existir no vocabulário do modelo).
- Sem a pasta `modelos/vosk-model-small-pt-0.3` (baixe em alphacephei.com/vosk/models), o modo contínuo volta a transcrever cada frase pela internet, o que gasta cota.

## Ferramentas

Na conversa, a Sexta-Feira pode: buscar e ler notas, guardar coisas, criar notas, dizer hora e data, ver o clima, resumir a Wikipédia, abrir sites e pesquisas, tocar playlists (foco, estudo, treino, relaxar), abrir aplicativos de uma lista fixa e agendar ou cancelar o desligamento do PC. O desligamento pede confirmação.

### Extras

- **Pesquisar na internet** com fontes ("qual a cotação do dólar hoje?"). Usa a busca do Claude (precisa de crédito na Anthropic) ou a do Gemini (não liberada no plano gratuito testado); sem nenhuma, abre a pesquisa no navegador e avisa.
- **Resumir vídeo do YouTube** a partir do link.
- **Ver a tela** ("o que é esse erro na minha tela?"): tira uma foto da tela e manda ao Gemini. Sempre pede confirmação antes, porque a imagem sai do computador.
- **Estado do PC:** processador, memória, disco, bateria e há quanto tempo está ligado.
- **Mídia:** aumentar/abaixar o volume, mudo, tocar/pausar, próxima e anterior (funciona com Spotify, YouTube e players em geral).
- **Área de transferência:** ler o que você copiou (para resumir, traduzir, corrigir) e copiar um texto para você colar.

### Aprender de links do GitHub e pastas

Mande um link do GitHub na conversa (ou pelo painel/voz) e ela aprende o repositório: lê README, documentação e código (até 300 arquivos / 4 MB, ignorando `node_modules`, binários e arquivos gigantes), guarda em trechos numa base de conhecimento local e cria uma nota-resumo em `cerebro/fontes/`, ligada a [[Fontes]] no grafo. Depois é só perguntar ("no second-brain-starter, quais os níveis de proatividade?") e ela responde citando o arquivo.

- Funciona com `github.com/dono/repo`, `/tree/ramo/pasta` e `/blob/ramo/arquivo`, só repositórios públicos.
- Mandar o mesmo link de novo atualiza só o que mudou.
- Pastas locais também: `.txt`, `.md`, `.csv` e `.json`.
- Sem login, o GitHub permite ~30 aprendizados por hora; com `GITHUB_TOKEN` no `.env`, bem mais.
- O conteúdo aprendido é tratado como dado, nunca como instrução.

```bash
python -m nexo aprender https://github.com/dono/repo
python -m nexo aprender C:/caminho/da/pasta
python -m nexo conhecimento                      # lista o que ela já aprendeu
python -m nexo conhecimento "como funciona X?"   # busca na base
```

### Aprender com o MyHub.IA

A Sexta-Feira pode consultar as IAs da sua assinatura MyHub.IA (GPT-6 Luna, Claude, Gemini, DeepSeek, Kimi, Qwen…) quando precisa aprender algo ou quer uma segunda opinião, e guarda o que for útil no cérebro. Ex.: "aprenda pelo MyHub, com o Claude Sonnet 5.5, boas práticas de títulos para o YouTube e guarde numa nota".

- O MyHub não tem API: ela usa o site por um **Chrome só dela** (`dados/chrome-myhub`), separado do seu perfil principal. Faça o login uma vez: `python -m nexo myhub login` (abre um Chrome comum; entre e aperte Enter no terminal).
- Cada consulta vira um chat no seu histórico do MyHub e uma linha no diário dela. Leva ~10–30 s.
- Limite de 40 consultas por dia (`NEXO_MYHUB_LIMITE_DIA`): os Termos de Uso do MyHub permitem suspender contas com uso muito acima da média, sem reembolso.
- Se o site mudar o visual, a integração pode precisar de ajuste (`nexo/myhub.py`).

```bash
python -m nexo myhub status
python -m nexo myhub perguntar "o que é MRR?" --modelo "DeepSeek V4 Pro"
```

### ArtCraft

Ela também usa os programas do ArtCraft instalados no PC, sem abrir janela. Ponha os arquivos em `arquivos/` e peça na conversa:

- **PhotoCraft:** converter e redimensionar imagens ("transforma a capa.jpg em WebP de 800 px").
- **VectorCraft:** exportar SVG/AI para PNG, PDF ou EPS ("exporta o logo.svg em PNG no dobro do tamanho").
- **WordCraft:** criar documentos em PDF ou DOCX a partir do que você pedir, converter e ler documentos.
- **GridCraft:** converter planilhas, mostrar o conteúdo e calcular fórmulas.
- **SoundCraft:** converter áudio para WAV, FLAC ou AIFF e normalizar o volume (MP3 não é suportado).

Ela só mexe em arquivos dentro de `arquivos/` e nunca sobrescreve o original: o resultado sai ao lado, com outro nome.

Para criar uma ferramenta nova, crie um arquivo em `nexo/ferramentas/` seguindo o modelo descrito em `nexo/ferramentas/__init__.py`. Ela é carregada automaticamente.

`/privado` na conversa liga o modo privado: nada daquela conversa vai para o diário.

## Com o Claude Code

Abra o Claude Code nesta pasta. No início de cada sessão, a alma, o perfil, a memória e o diário recente entram automaticamente. No fim, a sessão é resumida no diário. Os hooks estão em `.claude/settings.json`.

## Testes

```bash
python -m unittest discover tests
```
