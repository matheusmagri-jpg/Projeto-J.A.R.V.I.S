# JARVIS pt-BR

Assistente com briefing diário (receita, ads, e-mails, prioridades) falado com uma voz no estilo do JARVIS dublado.

## Arquivos

- `dashboard.html` — painel dark estilo Stark. Abra no navegador. Mostra dados de exemplo até existir um `data.json` na mesma pasta. O botão **Ouvir briefing** lê o resumo em voz alta.
- `jarvis_voz.py` — gera e toca o áudio do briefing com ElevenLabs ou Fish Audio.
- `persona.md` — personalidade e frases do JARVIS, para o Claude escrever o briefing no tom certo.
- `faq-suporte.md` — modelo de FAQ para o Claude responder e-mails de clientes.

## Voz do JARVIS em português

A voz do JARVIS dublado é de um dublador real, então clonar a voz dele sem autorização pode dar problema de direito de imagem/voz (e os termos do ElevenLabs e Fish Audio proíbem). O caminho seguro é escolher uma voz parecida: masculina, grave, calma, dicção limpa, tom de mordomo.

**ElevenLabs (recomendado para pt-BR):**
1. Crie conta em elevenlabs.io e copie a API key em *Profile → API Keys*.
2. Em *Voice Library*, filtre por **Portuguese / Brazilian**, gênero masculino, e busque termos como "narrador", "butler", "calm", "deep". Teste algumas com a frase "Bom dia, senhor. Seu resumo está pronto."
3. Adicione a voz a *My Voices* e copie o **Voice ID**.
4. Alternativa: *Voice Design* — descreva "homem brasileiro de 45 anos, voz grave e calma, tom formal de mordomo britânico, dicção perfeita" e gere uma voz própria.
5. O modelo `eleven_multilingual_v2` fala pt-BR com boa naturalidade.

**Fish Audio:** em fish.audio, procure modelos de voz em português ("Jarvis", "mordomo", "narrador"), copie o ID do modelo (`reference_id`). Prefira modelos de voz original, não clones de pessoas reais.

**Grátis:** sem chave, o dashboard usa a voz pt-BR do sistema (no Windows "Daniel"/"Antonio", no Mac "Felipe"/"Luciana"). Funciona, mas soa robótico.

## Testar a voz

```bash
pip install requests
export ELEVENLABS_API_KEY=sk_...
export ELEVENLABS_VOICE_ID=...
python jarvis_voz.py "Bom dia, senhor. Seu resumo está pronto."
```

No dashboard: clique em **⚙ Voz**, escolha ElevenLabs, cole a chave e o Voice ID.

## data.json (formato que a rotina vai gerar)

```json
{
  "demo": false,
  "receita": 18420, "receitaLabel": "Receita · 28 dias", "mrr": 6100,
  "briefing": "texto opcional; se existir, é o que o JARVIS fala",
  "assinantes": 1286, "assinantesVar": 3.1,
  "ads": 4210, "adsVar": -6.0,
  "roas": 3.4, "roasVar": 0.4,
  "receitaDiaria": [2210, 2480, 2390, 2760, 2650, 2940, 2990],
  "prioridades": [["texto", "bad|warn|ok"]],
  "emails": [["Remetente — assunto", "status", "bad|warn|ok"]]
}
```

Obs.: o navegador só lê `data.json` quando o painel é servido por um servidor local (`python -m http.server` na pasta) em vez de aberto direto do disco.

## Próximos passos (ordem do guia)

1. ✅ Dashboard
2. ✅ Voz
3. Receita: conectar RevenueCat MCP
4. E-mail: conectar Gmail e preencher `faq-suporte.md`
5. Rotina diária: agendar o briefing (gera `data.json` + texto + áudio no horário escolhido)
