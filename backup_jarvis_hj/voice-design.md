# Voz do JARVIS: ElevenLabs Voice Design

Onde: elevenlabs.io → Voices → Add a new voice → **Voice Design**.

## 1. Descrição da voz (cole no campo "Prompt")

> Brazilian Portuguese male voice, around 45 years old, native São Paulo accent with very clean, precise diction. Deep, warm baritone with a smooth, slightly velvety texture. Speaks in a calm, composed, formal tone, like a refined British butler dubbed into Portuguese: polite, confident, quietly intelligent, with a subtle dry wit. Measured pace, a little slower than conversational, with short deliberate pauses between sentences. Very steady intonation, never excited or theatrical, gentle downward ending on sentences. Studio-quality recording, close microphone, no background noise, slight soft resonance as if heard through a high-end speaker system.

Dica: o Voice Design entende melhor as descrições em inglês, mas a voz gerada fala em português.

## 2. Texto de prévia (cole no campo "Text to preview")

> Bom dia, senhor. Seu resumo está pronto. A receita dos últimos sete dias subiu doze por cento, e tomei a liberdade de responder os e-mails de rotina. Receio que a campanha B não esteja indo bem. Devo pausá-la?

## 3. Configuração

- Loudness: médio. Guidance scale: alto (entre 60 e 80%), para seguir melhor a descrição.
- Gere de 3 a 5 vezes e salve a melhor como **"JARVIS pt-BR"**. Depois copie o Voice ID.

## 4. Ajustes ao usar (já estão no dashboard e no jarvis_voz.py)

- Modelo: `eleven_multilingual_v2`
- stability 0.6 (aumente para 0.7 se a voz oscilar demais)
- similarity_boost 0.8
- style 0.15 (até 0.3 para ter um pouco mais de ironia)
- Se quiser a voz mais lenta, use o parâmetro `speed` em 0.92.

## Variações para testar

- **Mais grave:** troque "warm baritone" por "deep bass-baritone".
- **Mais "IA":** acrescente "faint, subtle digital sheen, very light".
- **Mais formal:** acrescente "impeccable, almost aristocratic courtesy".
