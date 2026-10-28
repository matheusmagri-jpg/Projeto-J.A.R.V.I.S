# JARVIS

Pasta com dois projetos do mesmo assistente, servida pelo XAMPP em `http://localhost:8080/jarvis/`.

- **Raiz (este repositório):** briefing diário do JARVIS. Painel estilo Stark, voz e rotina que junta receita, ads e e-mails.
- **`nexo/`:** o Jarvis (antes Sexta-Feira), assistente pessoal em Python com segundo cérebro no Obsidian. É um **repositório Git separado**, ignorado aqui. Para trabalhar nela, leia `nexo/CLAUDE.md`.

## Arquivos da raiz
- `dashboard.html` + `jarvis.js`: painel. Lê `data.json`, `claude-code.php` (sessões do Claude Code, só responde para 127.0.0.1) e `/CBTECH/admin/jarvis-dados.php` (dados ao vivo do site CBTECH, mesmo XAMPP).
- `gerar_briefing.py`: gera `data.json`, `briefing.txt` e `jarvis.mp3` (RevenueCat, Meta Ads). Os três arquivos ficam fora do Git.
- `jarvis_voz.py`: fala um texto com ElevenLabs ou Fish Audio.
- `regravar-falas.mjs`: regrava com ElevenLabs as falas do J.A.R.V.I.S. do Claude Code (`~/.claude/jarvis/`). Cada execução custa créditos; sem `--gravar` só mostra o custo.
- `server.js`: proxy HTTP em 127.0.0.1:3000 para o Ollama (`/health`, `/api/models`, `/api/ia`). Lê o `.env` ao lado dele. `test-api.cmd` testa as três rotas.
- `persona.md`, `voice-design.md`, `rotina.md`, `faq-suporte.md`: textos de apoio (personalidade, voz, rotina, FAQ de suporte).

## Comandos
- `node server.js`: sobe o proxy do Ollama.
- `python gerar_briefing.py`: gera o briefing do dia.
- `python jarvis_voz.py "texto"` / `--motor fish` / `--arquivo briefing.txt`: fala um texto.
- Painel: `http://localhost:8080/jarvis/dashboard.html` (o Apache do XAMPP está na porta 8080; a porta 80 é do IIS).

## Segurança
- Segredos só no `.env` (modelo em `.env.example`). Nunca leia nem imprima o `.env`.
- O Apache escuta em 0.0.0.0:8080, então tudo o que ele serve fica visível na rede. O `.htaccess` devolve 404 para arquivos que começam com ponto, para `nexo/` inteiro e para `.py .mjs .cmd .md .txt .log`. Arquivo novo que não deve ir para a rede precisa de uma regra lá.
- `jarvis_voz.py`, `gerar_briefing.py` e `regravar-falas.mjs` ainda leem as chaves das variáveis de ambiente, não do `.env`.

## Convenções
- Textos, comentários e mensagens em português do Brasil. O JARVIS chama o usuário de "senhor".
