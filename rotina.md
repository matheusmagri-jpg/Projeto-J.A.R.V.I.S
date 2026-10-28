# Rotina diária do JARVIS (o que roda todo dia às 7h44, horário de Brasília)

1. **E-mails (Gmail):** buscar e-mails de clientes das últimas 24 horas que ainda não foram respondidos.
   - Se a pergunta estiver coberta no `faq-suporte.md`, criar um **rascunho** de resposta no tom do FAQ.
   - Se não estiver coberta, ou estiver na lista "Sempre escalar", não responder e marcar como "Precisa de você".
   - Salvar o resultado em `emails.json` no formato `[["Remetente — assunto", "Rascunho pronto (FAQ #n)" | "Precisa de você", "ok" | "bad"]]`.
2. **Dados:** rodar `python gerar_briefing.py --sem-audio`, que puxa o RevenueCat e o Meta Ads e grava o `data.json`.
3. **YouTube (Metricool, brandId 7547810):** com `getAnalyticsDataByMetrics`, dos últimos 7 dias, pegar YTEV01 (inscritos), YTEV02 (visualizações), YTEV04 (vídeos), YTEV05 (ganhos) e YTEV06 (perdidos). Com `getScheduledPosts`, pegar os posts agendados para hoje. Gravar no campo `youtube` do `data.json`: `{"inscritos", "views7d", "videos7d", "ganhos7d", "perdidos7d", "agendadosHoje"}`. Se houver menos de 3 vídeos agendados, colocar isso nas prioridades.
4. **Prioridades:** escolher de 3 a 5 itens (e-mails escalados, campanhas com ROAS abaixo de 1,5, queda de receita acima de 10%, falta de posts) e salvar em `prioridades.json` no formato `[["texto", "bad" | "warn" | "ok"]]`. Depois rodar o `gerar_briefing.py --sem-audio` de novo.
5. **Texto:** escrever o briefing seguindo o `persona.md`, com no máximo 1 minuto e meio de fala. Salvar em `briefing.txt` e também no campo `briefing` do `data.json`.
6. **Voz:** rodar `python jarvis_voz.py --arquivo briefing.txt --saida jarvis.mp3 --nao-tocar` (só funciona se a chave de voz estiver configurada).
7. **PC do Matheus:** se o computador dele estiver acessível, copiar o `data.json`, o `briefing.txt` e o `jarvis.mp3` para `C:\xampp\htdocs\jarvis\` com `device_commit_files`. Assim o dashboard em http://localhost:8080/jarvis/dashboard.html fica atualizado.
8. **Entrega:** mandar o briefing na thread "Jarvis com voz em português", com o `jarvis.mp3` anexado.

**Regras de segurança:** e-mails ficam só como rascunho, nunca são enviados sozinhos. Nenhuma campanha é pausada ou criada sem o "sim" do Matheus. O JARVIS apenas recomenda.
