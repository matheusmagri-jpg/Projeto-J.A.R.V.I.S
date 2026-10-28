// ---------- DADOS ----------
// Troque este objeto pelo data.json gerado pela rotina diária (RevenueCat, Meta Ads, Gmail).
const DEMO = {
  demo: true,
  receita: 18420, receitaLabel: "Receita · 7 dias", receitaVar: 12.4,
  assinantes: 1286, assinantesVar: 3.1,
  ads: 4210, adsVar: -6.0,
  roas: 3.4, roasVar: 0.4,
  receitaDiaria: [2210, 2480, 2390, 2760, 2650, 2940, 2990],
  prioridades: [
    ["Responder 2 e-mails escalados (reembolso e bug no login)", "bad"],
    ["Campanha 'Black Friday – teste B' com ROAS 1,1: avaliar pausa", "warn"],
    ["Agendar os 3 vídeos curtos de hoje", "ok"],
  ],
  emails: [
    ["Ana P. — Não consigo restaurar minha assinatura", "Respondido (FAQ #3)", "ok"],
    ["Carlos M. — Como cancelo?", "Respondido (FAQ #1)", "ok"],
    ["Juliana R. — Cobrança em dobro", "Precisa de você", "bad"],
    ["Diego S. — Erro ao entrar com Google", "Precisa de você", "bad"],
  ],
};
let data = DEMO;
// data.json vem da rotina diária; o bloco CBTECH vem ao vivo do painel admin do site
// (precisa estar logado como admin em /CBTECH no mesmo navegador).
const CBTECH_URL = "/CBTECH/admin/jarvis-dados.php";
Promise.all([
  fetch("data.json").then(r => r.ok ? r.json() : null).catch(() => null),
  fetch(CBTECH_URL, {credentials: "same-origin", cache: "no-store"}).then(r => r.ok ? r.json() : {semLogin: r.status === 401}).catch(() => null),
]).then(([j, cb]) => {
  if (j) data = j;
  if (cb && cb.cbtech) {
    // Receita do site entra no lugar da do RevenueCat quando ele não estiver configurado.
    if (typeof data.receita !== "number") Object.assign(data, {receita: cb.receita, receitaLabel: cb.receitaLabel, receitaVar: cb.receitaVar, receitaDiaria: cb.receitaDiaria});
    data = {...data, demo: false, cbtech: cb.cbtech, prioridades: [...cb.prioridades.filter(p => p[1] !== "ok"), ...(data.prioridades || [])]};
    data.briefing = cb.briefing; // ao vivo, sempre mais novo que o da rotina
  } else if (cb && cb.semLogin) {
    data.cbtechSemLogin = true;
  }
  render();
});

const brl = n => n.toLocaleString("pt-BR", {style: "currency", currency: "BRL", maximumFractionDigits: 0});
const pct = n => (n >= 0 ? "▲ " : "▼ ") + Math.abs(n).toLocaleString("pt-BR", {maximumFractionDigits: 1}) + "% vs. semana anterior";
const dias = () => [...Array(7)].map((_, i) => { const d = new Date(); d.setDate(d.getDate() - 6 + i); return d.toLocaleDateString("pt-BR", {weekday: "short"}); });
const store = {
  get: k => { try { return localStorage.getItem(k) || ""; } catch { return ""; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch {} },
};
let systemEnabled = true;
let claudeTimer = null;
let tickTimer = null;

function setPowerState(enabled, options = {}) {
  const { persist = true, announce = false } = options;
  systemEnabled = Boolean(enabled);
  const powerButton = document.getElementById("powerToggle");
  const speakButton = document.getElementById("speak");
  const cfgButton = document.getElementById("cfg");
  const testVoiceButton = document.getElementById("testarVoz");
  if (powerButton) {
    powerButton.textContent = systemEnabled ? "🟢 Sistema ligado" : "🔴 Sistema desligado";
    powerButton.classList.toggle("is-off", !systemEnabled);
    powerButton.setAttribute("aria-pressed", String(systemEnabled));
  }
  if (speakButton) speakButton.disabled = !systemEnabled;
  if (cfgButton) cfgButton.disabled = !systemEnabled;
  if (testVoiceButton) testVoiceButton.disabled = !systemEnabled;
  document.body.classList.toggle("system-off", !systemEnabled);
  if (persist) store.set("jarvisPowerState", String(systemEnabled));
  if (!systemEnabled) {
    clearInterval(claudeTimer);
    claudeTimer = null;
    clearInterval(tickTimer);
    tickTimer = null;
    speechSynthesis.cancel();
    const briefing = document.getElementById("briefing");
    if (briefing) briefing.textContent = "Sistema desligado pelo interruptor mestre. O JARVIS está em modo de segurança e não executa rotinas, monitoramento nem voz até que seja religado.";
    if (announce) console.info("JARVIS desligado");
    return;
  }
  if (announce) console.info("JARVIS ligado");
  if (!claudeTimer) claudeTimer = setInterval(carregarClaude, 15000);
  if (!tickTimer) tickTimer = setInterval(tick, 30000);
  tick();
  if (typeof carregarClaude === "function") carregarClaude();
}

async function syncPowerState(enabled) {
  setPowerState(enabled, { persist: true, announce: false });
  try {
    const res = await fetch("http://127.0.0.1:3000/api/system", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled })
    });
    if (!res.ok) throw new Error("server");
    const data = await res.json();
    setPowerState(Boolean(data.enabled), { persist: true, announce: false });
  } catch {
    // Fallback local quando o backend não está disponível.
  }
}

async function carregarEstadoSistema() {
  try {
    const res = await fetch("http://127.0.0.1:3000/api/system", { cache: "no-store" });
    if (!res.ok) throw new Error("server");
    const data = await res.json();
    setPowerState(Boolean(data.enabled), { persist: false, announce: false });
    return;
  } catch {
    const saved = store.get("jarvisPowerState");
    const enabled = saved !== "false";
    setPowerState(enabled, { persist: false, announce: false });
  }
}

function saudacao() {
  const h = new Date().getHours();
  return h < 12 ? "Bom dia, senhor." : h < 18 ? "Boa tarde, senhor." : "Boa noite, senhor.";
}

function textoBriefing(d) {
  if (d.briefing) return d.briefing;
  const pend = d.emails.filter(e => e[2] === "bad").length;
  const resp = d.emails.length - pend;
  return `${saudacao()} Seu resumo está pronto.

A receita do período foi de ${brl(d.receita)}, ${d.receitaVar >= 0 ? "uma alta" : "uma queda"} de ${Math.abs(d.receitaVar).toLocaleString("pt-BR")} por cento. Temos ${d.assinantes.toLocaleString("pt-BR")} assinantes ativos.

Em anúncios, foram investidos ${brl(d.ads)}, com ROAS de ${d.roas.toLocaleString("pt-BR")}.

Respondi ${resp} e-mails de suporte. ${pend ? `${pend} ${pend > 1 ? "casos exigem" : "caso exige"} sua atenção.` : "Nenhum caso pendente."}

${d.prioridades.length ? `Prioridade número um: ${d.prioridades[0][0]}.` : ""}

Isso é tudo por enquanto, senhor. Estarei à disposição.`;
}

function desenharGrafico(v) {
  const W = 700, H = 220, px = 50, py = 20, lab = dias();
  const min = Math.min(...v) * 0.85, max = Math.max(Math.max(...v) * 1.1, min + 1);
  const x = i => px + i * (W - px - 20) / (v.length - 1);
  const y = n => H - 30 - (n - min) / (max - min) * (H - 30 - py);
  const pts = v.map((n, i) => `${x(i)},${y(n)}`).join(" ");
  const grade = [0, 1, 2, 3].map(k => { const n = min + (max - min) * k / 3; return `<line x1="${px}" x2="${W - 20}" y1="${y(n)}" y2="${y(n)}" stroke="#12263a"/><text x="${px - 8}" y="${y(n) + 4}" fill="#7c98a8" font-size="11" text-anchor="end">${Math.round(n / 100) / 10}k</text>`; }).join("");
  document.getElementById("chart").innerHTML = grade +
    `<polygon points="${x(0)},${H - 30} ${pts} ${x(v.length - 1)},${H - 30}" fill="#3fd5ff1f"/>` +
    `<polyline points="${pts}" fill="none" stroke="#3fd5ff" stroke-width="2.5" stroke-linejoin="round"/>` +
    v.map((n, i) => `<circle cx="${x(i)}" cy="${y(n)}" r="4" fill="#05090f" stroke="#3fd5ff" stroke-width="2"><title>${brl(n)}</title></circle><text x="${x(i)}" y="${H - 8}" fill="#7c98a8" font-size="11" text-anchor="middle">${lab[i]}</text>`).join("");
}

function render() {
  const d = data;
  const set = (id, v) => document.getElementById(id).textContent = v;
  const delta = (id, v) => { const el = document.getElementById(id); el.textContent = pct(v); el.className = "delta " + (v >= 0 ? "up" : "down"); };
  const tem = v => typeof v === "number";
  ["d-rev", "d-subs", "d-ads"].forEach(id => document.getElementById(id).className = "delta");
  set("l-rev", d.receitaLabel || "Receita");
  set("k-rev", tem(d.receita) ? brl(d.receita) : "—"); tem(d.receitaVar) ? delta("d-rev", d.receitaVar) : set("d-rev", tem(d.mrr) ? "MRR " + brl(d.mrr) : "");
  set("k-subs", tem(d.assinantes) ? d.assinantes.toLocaleString("pt-BR") : "—"); tem(d.assinantesVar) ? delta("d-subs", d.assinantesVar) : set("d-subs", tem(d.trials) ? d.trials + " em trial" : "");
  set("k-ads", tem(d.ads) ? brl(d.ads) : "—"); tem(d.adsVar) ? delta("d-ads", d.adsVar) : set("d-ads", "");
  set("k-roas", tem(d.roas) ? d.roas.toLocaleString("pt-BR") + "×" : "—");
  const r = document.getElementById("d-roas"); r.textContent = tem(d.roasVar) ? (d.roasVar >= 0 ? "▲ " : "▼ ") + Math.abs(d.roasVar).toLocaleString("pt-BR") + " pts" : ""; r.className = "delta " + (d.roasVar >= 0 ? "up" : "down");
  d.emails = d.emails || []; d.prioridades = d.prioridades || [];
  const cb = d.cbtech;
  document.getElementById("cbtech").style.display = cb || d.cbtechSemLogin ? "" : "none";
  set("cb-aviso", d.cbtechSemLogin ? "Entre no admin da CBTECH (/CBTECH/auth/login.php) neste navegador para ver os dados do site." : "");
  if (cb) {
    set("cb-mat", cb.matriculas7d); set("cb-orc", cb.orcamentos7d); set("cb-atr", cb.orcamentosAtrasados);
    set("cb-msg", cb.mensagensNovas); set("cb-chat", cb.chatAguardando); set("cb-cli", cb.novosClientes7d);
  }
  const yt = d.youtube;
  document.getElementById("social").style.display = yt ? "" : "none";
  if (yt) {
    const n = v => (v ?? 0).toLocaleString("pt-BR");
    set("yt-subs", n(yt.inscritos)); set("yt-views", n(yt.views7d));
    set("yt-ganhos", (yt.ganhos7d - (yt.perdidos7d || 0) >= 0 ? "+" : "") + n(yt.ganhos7d - (yt.perdidos7d || 0)));
    set("yt-videos", n(yt.videos7d)); set("yt-agendados", n(yt.agendadosHoje));
  }
  document.getElementById("prio").innerHTML = d.prioridades.map(([t, s]) => `<li><span class="tag t-${s}">${{bad: "urgente", warn: "atenção", ok: "rotina"}[s]}</span>${t}</li>`).join("");
  document.getElementById("mail").innerHTML = d.emails.map(([t, st, s]) => `<li><span class="tag t-${s}">${st}</span>${t}</li>`).join("") || '<li class="sub">Nenhum e-mail de cliente pendente.</li>';
  document.getElementById("briefing").textContent = textoBriefing(d);
  set("demo", d.demo ? "· dados de exemplo" : "");
  const g = document.getElementById("chart").closest(".card");
  g.style.display = d.receitaDiaria ? "" : "none";
  document.querySelector("main").classList.toggle("sem-grafico", !d.receitaDiaria);
  if (d.receitaDiaria) desenharGrafico(d.receitaDiaria);
}

// Sessões do Claude Code, lidas do estado local do J.A.R.V.I.S. do Claude Code (só nesta máquina).
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
function carregarClaude() {
  fetch("claude-code.php", {cache: "no-store"}).then(r => r.ok ? r.json() : null).catch(() => null).then(cc => {
    const card = document.getElementById("claude");
    card.style.display = cc && cc.instalado ? "" : "none";
    if (!cc || !cc.instalado) return;
    const set = (id, v) => document.getElementById(id).textContent = v;
    set("cc-ativas", cc.ativas); set("cc-sessoes", cc.sessoes24h); set("cc-acoes", cc.acoesHoje.toLocaleString("pt-BR"));
    set("cc-voz", cc.mudo ? "mudo" : "ligada");
    const tag = {trabalhando: ["ok", "trabalhando"], parada: ["warn", "parada"], encerrada: ["bad", "encerrada"]};
    const hora = ts => new Date(ts * 1000).toLocaleTimeString("pt-BR", {hour: "2-digit", minute: "2-digit"});
    document.getElementById("cc-lista").innerHTML = cc.sessoes.map(s => {
      const [cls, rot] = tag[s.status];
      const ult = s.recentes.find(e => e.tipo !== "JVS");
      return `<li><span class="tag t-${cls}">${rot}</span>${esc(s.titulo)} <span class="sub">· ${esc(s.modelo)} · ${s.acoes} ações · ${hora(s.ultimaAtividade)}${ult ? " · " + esc(ult.texto) : ""}</span></li>`;
    }).join("") || '<li class="sub">Nenhuma sessão nas últimas 24 horas.</li>';
  });
}
function tick() {
  document.getElementById("clock").textContent = new Date().toLocaleString("pt-BR", {weekday: "long", day: "2-digit", month: "long", hour: "2-digit", minute: "2-digit"});
}

document.getElementById("powerToggle").onclick = async () => {
  await syncPowerState(!systemEnabled);
};

carregarEstadoSistema().finally(() => {
  render();
});

// ---------- VOZ ----------
const core = document.getElementById("core");

// Texto escrito para ler vira texto para ouvir: "R$ 18.420" soa como "18.420 reais",
// símbolos somem e cada frase vira um trecho com pausa (o ritmo de mordomo).
function paraFala(texto) {
  return texto
    .replace(/R\$\s?([\d.]+)(,\d+)?/g, (_, n, c) => `${n}${c && c !== ",00" ? c : ""} reais`)
    .replace(/(\d+(?:,\d+)?)\s?%/g, "$1 por cento")
    .replace(/(\d+(?:,\d+)?)×/g, "$1 vezes")
    .replace(/\bROAS\b/g, "Roás")
    .replace(/\(ex\.:\s*/g, ", por exemplo, ").replace(/[()]/g, "")
    .replace(/[—–]/g, ",").replace(/\b1 reais/g, "1 real")
    .replace(/\s+/g, " ").replace(/\s+([,.])/g, "$1").replace(/,\s*,/g, ",").trim();
}

// Vozes "Natural"/"Online" (Edge) e as do Google soam muito melhor que as
// antigas do Windows (Daniel, Maria). Ordem de preferência para um JARVIS.
const PREFERENCIA_VOZ = [/antonio.*(natural|online)/i, /(natural|online).*antonio/i, /(natural|online)/i, /google/i, /antonio|daniel|ricardo|felipe/i];
function vozesPtBR() {
  return speechSynthesis.getVoices().filter(v => v.lang.replace("_", "-").toLowerCase().startsWith("pt-br"));
}
function escolherVoz() {
  const vozes = vozesPtBR(), salva = store.get("browserVoice");
  if (salva) { const v = vozes.find(v => v.name === salva); if (v) return v; }
  for (const re of PREFERENCIA_VOZ) { const v = vozes.find(v => re.test(v.name)); if (v) return v; }
  return vozes[0] || null;
}

function falarNavegador(texto) {
  const voz = escolherVoz();
  const natural = voz && /natural|online|google/i.test(voz.name);
  const frases = paraFala(texto).match(/[^.!?]+[.!?]*/g) || [];
  speechSynthesis.cancel();
  frases.forEach((f, i) => {
    const u = new SpeechSynthesisUtterance(f.trim());
    u.lang = "pt-BR"; u.voice = voz;
    // Vozes naturais já têm boa entonação: só desacelerar um pouco.
    // As antigas ficam menos robóticas um pouco mais graves e lentas.
    u.rate = natural ? 0.92 : 0.88; u.pitch = natural ? 0.9 : 0.8;
    if (i === 0) u.onstart = () => core.classList.add("speaking");
    if (i === frases.length - 1) u.onend = () => core.classList.remove("speaking");
    speechSynthesis.speak(u);
  });
}

async function falarElevenLabs(texto) {
  const key = store.get("elKey"), voice = store.get("elVoice");
  const r = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${voice}`, {
    method: "POST",
    headers: {"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
    body: JSON.stringify({
      text: paraFala(texto), model_id: "eleven_multilingual_v2",
      voice_settings: {stability: 0.5, similarity_boost: 0.85, style: 0.2, use_speaker_boost: true, speed: 0.92},
    }),
  });
  if (!r.ok) throw new Error("ElevenLabs " + r.status);
  const audio = new Audio(URL.createObjectURL(await r.blob()));
  audio.onplay = () => core.classList.add("speaking");
  audio.onended = () => core.classList.remove("speaking");
  audio.play();
}

document.getElementById("speak").onclick = async () => {
  if (!systemEnabled) return;
  const texto = textoBriefing(data);
  if (store.get("engine") === "elevenlabs" && store.get("elKey") && store.get("elVoice")) {
    try { await falarElevenLabs(texto); return; } catch (e) { console.warn(e); }
  }
  falarNavegador(texto);
};

const dlg = document.getElementById("dlg");
document.getElementById("cfg").onclick = () => {
  engine.value = store.get("engine") || "browser"; elKey.value = store.get("elKey"); elVoice.value = store.get("elVoice");
  const atual = escolherVoz();
  browserVoice.innerHTML = vozesPtBR().map(v => `<option${atual && v.name === atual.name ? " selected" : ""}>${v.name}</option>`).join("") || "<option value=''>Nenhuma voz pt-BR instalada</option>";
  dlg.showModal();
};
dlg.addEventListener("close", () => {
  if (dlg.returnValue !== "save") return;
  store.set("engine", engine.value); store.set("elKey", elKey.value.trim()); store.set("elVoice", elVoice.value.trim()); store.set("browserVoice", browserVoice.value);
});
speechSynthesis.getVoices();
document.getElementById("testarVoz").onclick = () => {
  if (!systemEnabled) return;
  store.set("browserVoice", browserVoice.value); falarNavegador("Bom dia, senhor. Seu resumo está pronto. Às suas ordens.");
};
