// Regrava as falas do J.A.R.V.I.S. do Claude Code com a sua voz do ElevenLabs.
// As falas vêm de ~/.claude/jarvis/lines.mjs e cada uma vira clips/{categoria}-{n}.mp3.
// Os mp3 originais são guardados uma vez em clips-original/ antes de serem trocados.
//
// Uso (custa 1 crédito do ElevenLabs por caractere):
//   node regravar-falas.mjs                         -> só mostra quanto custaria, não grava nada
//   node regravar-falas.mjs --gravar                -> grava as categorias principais
//   node regravar-falas.mjs --gravar --categorias stop,notify
//   node regravar-falas.mjs --gravar --todas        -> todas as categorias (cerca de 17 mil créditos)
//   node regravar-falas.mjs --restaurar             -> volta os mp3 originais
//
// Precisa de ELEVENLABS_API_KEY e ELEVENLABS_VOICE_ID no ambiente (as mesmas do jarvis_voz.py).
// Falas já regravadas ficam anotadas em .regravadas.json e não são cobradas de novo.
import { existsSync, mkdirSync, readFileSync, writeFileSync, copyFileSync, readdirSync } from "fs";
import { join } from "path";
import { homedir } from "os";
import { pathToFileURL } from "url";

const JARVIS = process.env.JARVIS_CC_DIR || join(homedir(), ".claude", "jarvis");
const CLIPS = join(JARVIS, "clips");
const ORIGINAIS = join(JARVIS, "clips-original");
const FEITAS = join(JARVIS, ".regravadas.json");
const PRINCIPAIS = ["sessionstart", "prompt", "stop", "notify", "subagent", "fanout"];

const args = process.argv.slice(2);
const gravar = args.includes("--gravar");
const iCat = args.indexOf("--categorias");
const say = (m) => console.log(`[regravar] ${m}`);

if (args.includes("--restaurar")) {
  if (!existsSync(ORIGINAIS)) { say("não há originais guardados; nada a restaurar."); process.exit(0); }
  for (const f of readdirSync(ORIGINAIS)) copyFileSync(join(ORIGINAIS, f), join(CLIPS, f));
  writeFileSync(FEITAS, "{}");
  say("mp3 originais restaurados.");
  process.exit(0);
}

const { LINES } = await import(pathToFileURL(join(JARVIS, "lines.mjs")).href);
const categorias = args.includes("--todas") ? Object.keys(LINES)
  : iCat > -1 ? args[iCat + 1].split(",").map((s) => s.trim())
  : PRINCIPAIS;
for (const c of categorias) if (!LINES[c]) { say(`categoria desconhecida: ${c}`); process.exit(1); }

let feitas = {};
try { feitas = JSON.parse(readFileSync(FEITAS, "utf8")); } catch { /* primeira vez */ }

const pendentes = [];
for (const c of categorias) LINES[c].forEach((texto, i) => {
  const arquivo = `${c}-${i + 1}.mp3`;
  if (feitas[arquivo] !== texto) pendentes.push({ arquivo, texto });
});
const creditos = pendentes.reduce((s, p) => s + p.texto.length, 0);
say(`${pendentes.length} falas em ${categorias.length} categorias, cerca de ${creditos} créditos.`);

if (!gravar) { say("nada foi gravado. Rode com --gravar quando tiver créditos."); process.exit(0); }

const chave = process.env.ELEVENLABS_API_KEY, voz = process.env.ELEVENLABS_VOICE_ID;
if (!chave || !voz) { say("defina ELEVENLABS_API_KEY e ELEVENLABS_VOICE_ID antes de gravar."); process.exit(1); }

mkdirSync(ORIGINAIS, { recursive: true });
let ok = 0;
for (const { arquivo, texto } of pendentes) {
  const res = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${voz}`, {
    method: "POST",
    headers: { "xi-api-key": chave, "Content-Type": "application/json", Accept: "audio/mpeg" },
    // Mesmos ajustes do jarvis_voz.py: estável e contido, tom de mordomo.
    body: JSON.stringify({
      text: texto,
      model_id: "eleven_multilingual_v2",
      voice_settings: { stability: 0.5, similarity_boost: 0.85, style: 0.2, use_speaker_boost: true, speed: 0.92 },
    }),
  });
  if (!res.ok) {
    say(`parei em ${arquivo}: HTTP ${res.status} ${(await res.text()).slice(0, 200)}`);
    say("o que já foi gravado está salvo; rode de novo depois para continuar de onde parou.");
    break;
  }
  const destino = join(CLIPS, arquivo);
  if (existsSync(destino) && !existsSync(join(ORIGINAIS, arquivo))) copyFileSync(destino, join(ORIGINAIS, arquivo));
  writeFileSync(destino, Buffer.from(await res.arrayBuffer()));
  feitas[arquivo] = texto;
  writeFileSync(FEITAS, JSON.stringify(feitas, null, 1));
  ok++;
  say(`${ok}/${pendentes.length} ${arquivo}`);
}
say(`pronto: ${ok} falas regravadas.`);
