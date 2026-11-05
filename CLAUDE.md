# JARVIS

Pasta com dois projetos do mesmo assistente, servida pelo XAMPP em `http://localhost:8080/jarvis/`.

- **Raiz (este repositório):** briefing diário do JARVIS. Painel estilo Stark, voz e rotina que junta receita, ads e e-mails.
- **`nexo/`:** o Jarvis (antes Sexta-Feira), assistente pessoal em Python com segundo cérebro no Obsidian. É um **repositório Git separado**, ignorado aqui; este repositório guarda só uma cópia do código dele, sem `cerebro/`, `dados/`, `.env` e `tests/audios/`. Para trabalhar nela, leia `nexo/CLAUDE.md`.
- **`habblaud/`:** cópia sem alterações do [Habblaud](https://github.com/marmottajr/habblaud) 1.0.3 (MIT, Márcio Junior), o escritório em pixel art dos agentes do Claude Code. Roda no Docker em 127.0.0.1:4747 (`npm run docker:up` dentro da pasta); o painel do `nexo` mostra uma miniatura dele por um proxy somente leitura (`nexo/nexo/interface/habblaud.py`). Para mexer no código dele, leia `habblaud/CLAUDE.md`.

## Arquivos da raiz
- `dashboard.html` + `jarvis.js`: painel. Lê `data.json`, `claude-code.php` (sessões do Claude Code, só responde para 127.0.0.1) e `/CBTECH/admin/jarvis-dados.php` (dados ao vivo do site CBTECH, mesmo XAMPP).
- `intro.js` + `media/intro.mp4`: intro em vídeo que cobre o painel sempre que ele abre e some no fim (botão "Pular intro", Esc ou Enter). `media/` fica fora do Git (o vídeo passa de 100 MB).
- `gerar_briefing.py`: gera `data.json`, `briefing.txt` e `jarvis.mp3` (RevenueCat, Meta Ads). Os três arquivos ficam fora do Git.
- `jarvis_voz.py`: fala um texto com ElevenLabs ou Fish Audio.
- `regravar-falas.mjs`: regrava com ElevenLabs as falas do J.A.R.V.I.S. do Claude Code (`~/.claude/jarvis/`). Cada execução custa créditos; sem `--gravar` só mostra o custo.
- `server.js`: proxy HTTP em 127.0.0.1:3000 para o Ollama (`/health`, `/api/models`, `/api/ia`). Lê o `.env` ao lado dele. `test-api.cmd` testa as três rotas.
- `persona.md`, `voice-design.md`, `rotina.md`, `faq-suporte.md`: textos de apoio (personalidade, voz, rotina, FAQ de suporte).
- `start-jarvis.cmd`: sobe o Apache do XAMPP se preciso e abre o painel. `test_gerar_briefing.py`: teste do briefing.
- `backup_jarvis_hj/` e `_antes_da_restauracao/`: cópias antigas do painel. Não edite; o `.htaccess` não as serve.

## Comandos
- `node server.js`: sobe o proxy do Ollama.
- `python gerar_briefing.py`: gera o briefing do dia.
- `python -m unittest test_gerar_briefing`: testa o briefing sem chamar APIs.
- `python jarvis_voz.py "texto"` / `--motor fish` / `--arquivo briefing.txt`: fala um texto.
- Painel: `http://localhost:8080/jarvis/dashboard.html` (o Apache do XAMPP está na porta 8080; a porta 80 é do IIS).

## Segurança
- Segredos só no `.env` (modelo em `.env.example`). Nunca leia nem imprima o `.env`.
- O Apache escuta em 0.0.0.0:8080, então tudo o que ele serve fica visível na rede. O `.htaccess` devolve 404 para arquivos que começam com ponto, para qualquer pasta `nexo/` (em qualquer nível), para `habblaud/`, para as pastas de backup e para `.py .mjs .cmd .md .txt .log .ipynb .zip`. Arquivo novo que não deve ir para a rede precisa de uma regra lá.
- `jarvis_voz.py`, `gerar_briefing.py` e `regravar-falas.mjs` ainda leem as chaves das variáveis de ambiente, não do `.env`.

## Skills e plugins
Instalados para o usuário (`~/.claude/skills` e plugins); valem aqui também.
- **Planejar:** `/grilling` (ou `/grill-me`) antes de mudanças grandes no painel, no briefing ou no `nexo`. Só comece a editar depois que o plano for aprovado.
- **Testes:** `tdd` para código novo; `/handoff` para passar o trabalho a outra sessão.
- **Código enxuto:** `karpathy-guidelines`: mudanças pequenas, só no que o pedido pede.
- **Documentação de bibliotecas:** Context7 antes de usar uma API que você não conferiu na versão em uso.
- **Visual do painel:** `frontend-design` ou `design-taste-frontend` para criar; `web-design-guidelines` e AccessLint (`accessibility-scan`) para revisar. O painel é JS puro, sem React: as skills `vercel-react-*` não se aplicam.
- **Navegador:** para ver o painel, use o navegador embutido do app ou o `agent-browser`. Nunca envie formulários, faça compras ou ações irreversíveis sem autorização.
- **Vídeo:** HyperFrames (`/hyperframes`) ou Remotion para animações e vídeos, como a intro. Gere uma prévia antes de renderizar.
- **Segurança:** o plugin `security-guidance` revisa edições e commits. As skills da Trail of Bits (`insecure-defaults`, `supply-chain-risk-auditor`, `static-analysis`) servem para auditar `server.js`, os `.php` e as dependências.
- **Skill nova:** procure com `find-skills`, rode `skillspector scan <pasta-ou-url> --no-llm` e peça autorização antes de instalar.

## Convenções
- Textos, comentários e mensagens em português do Brasil. O JARVIS chama o usuário de "senhor".
