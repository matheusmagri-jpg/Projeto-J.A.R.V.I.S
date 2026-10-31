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

// ---------- OTIMIZAÇÕES ----------
// Cache inteligente para API calls e dados
const APICache = {
  cache: new Map(),
  defaultTTL: 5 * 60 * 1000, // 5 minutos
  
  get(key, customTTL) {
    const item = this.cache.get(key);
    if (item && Date.now() - item.timestamp < (customTTL || this.defaultTTL)) {
      // Atualizar timestamp para manter ordem LRU
      this.cache.delete(key);
      this.cache.set(key, item);
      return item.data;
    }
    this.cache.delete(key);
    return null;
  },
  
  set(key, data, ttl) {
    // Implementar LRU simples - remover item mais antigo se cheio
    if (this.cache.size >= 100) {
      const firstKey = this.cache.keys().next().value;
      this.cache.delete(firstKey);
    }
    
    this.cache.set(key, {
      data,
      timestamp: Date.now()
    });
  },
  
  // Cache específico para diferentes tipos de dados
  revenue: new Map(),
  subscribers: new Map(),
  ads: new Map(),
  roas: new Map()
};

// Cache para respostas da IA
const AICache = {
  memory: new Map(),
  maxSize: 50,
  contextTimeout: 30 * 60 * 1000, // 30 minutos
  
  get(key, context) {
    const cacheKey = context ? `${key}:${JSON.stringify(context)}` : key;
    const item = this.memory.get(cacheKey);
    
    if (item && !this.isExpired(item)) {
      // Mover para o final (LRU)
      this.memory.delete(cacheKey);
      this.memory.set(cacheKey, item);
      PerformanceMonitor.incrementCacheHit();
      return item.response;
    }
    
    PerformanceMonitor.incrementCacheMiss();
    return null;
  },
  
  set(key, response, context) {
    const cacheKey = context ? `${key}:${JSON.stringify(context)}` : key;
    
    if (this.memory.size >= this.maxSize) {
      const firstKey = this.memory.keys().next().value;
      this.memory.delete(firstKey);
    }
    
    this.memory.set(cacheKey, {
      response,
      timestamp: Date.now(),
      context
    });
  },
  
  isExpired(item) {
    return Date.now() - item.timestamp > this.contextTimeout;
  },
  
  // Cache baseado em similaridade de mensagens
  getSimilarResponse: function(message, context) {
    const messageKey = message.substring(0, 50).toLowerCase();
    const contextKey = context ? JSON.stringify(context) : '';
    
    // Tentar match exato primeiro
    const exactKey = `exact:${messageKey}:${contextKey}`;
    if (this.memory.has(exactKey)) {
      PerformanceMonitor.incrementCacheHit();
      return this.memory.get(exactKey).response;
    }
    
    // Tentar match parcial
    for (const [key, item] of this.memory) {
      if (key.includes(messageKey) && 
          (!contextKey || key.includes(contextKey))) {
        PerformanceMonitor.incrementCacheHit();
        return item.response;
      }
    }
    
    PerformanceMonitor.incrementCacheMiss();
  
  init() {
    this.startMetricsCollection();
    this.createFloatingMetrics();
    this.createDebugPanel();
  },
  
  startMetricsCollection() {
    // Coletar métricas a cada 5 segundos
    setInterval(() => {
      this.updateMetrics();
      this.sendMetricsToServer();
    }, 5000);
  },
  
  createFloatingMetrics() {
    // Criar indicador flutuante de métricas
    const floating = document.createElement('div');
    floating.id = 'floating-metrics';
    floating.className = 'floating-metrics';
    floating.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      z-index: 1000;
      font-size: 12px;
      max-height: 200px;
      overflow-y: auto;
      cursor: pointer;
      transition: opacity 0.3s;
      opacity: 0.8;
    `;
    
    floating.innerHTML = `
      <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
        <strong style="color: var(--cyan);">JARVIS Metrics</strong>
        <span style="color: var(--muted); font-size: 10px;">Ctrl+M</span>
      </div>
      <div class="metric-item">
        <span class="metric-label">Cache:</span>
        <span class="metric-value" id="floating-cache-rate">0%</span>
      </div>
      <div class="metric-item">
        <span class="metric-label">API:</span>
        <span class="metric-value" id="floating-api-calls">0</span>
      </div>
      <div class="metric-item">
        <span class="metric-label">Render:</span>
        <span class="metric-value" id="floating-render-time">0ms</span>
      </div>
      <div class="metric-item">
        <span class="metric-label">Memory:</span>
        <span class="metric-value" id="floating-memory">0MB</span>
      </div>
    `;
    
    // Adicionar evento de clique para mostrar/ocultar
    floating.addEventListener('click', (e) => {
      if (e.target === floating || e.target.closest('.metric-item')) {
        this.toggleDebugPanel();
      }
    });
    
    document.body.appendChild(floating);
    
    // Adicionar atalho de teclado
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.key === 'm') {
        e.preventDefault();
        this.toggleDebugPanel();
      }
    });
  },
  
  createDebugPanel() {
    // Criar painel de debug (inicialmente oculto)
    const debugPanel = document.createElement('div');
    debugPanel.id = 'debug-panel';
    debugPanel.style.cssText = `
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      background: var(--bg);
      border: 2px solid var(--cyan);
      border-radius: 8px;
      padding: 20px;
      z-index: 2000;
      max-width: 80%;
      max-height: 80%;
      overflow: auto;
      font-family: monospace;
      font-size: 12px;
      display: none;
    `;
    
    debugPanel.innerHTML = `
      <div style="display: flex; justify-content: space-between; margin-bottom: 10px;">
        <h3 style="color: var(--cyan); margin-top: 0;">JARVIS Debug</h3>
        <button onclick="document.getElementById('debug-panel').style.display = 'none'" 
                style="background: var(--cyan); color: var(--bg); border: none; padding: 5px 10px; border-radius: 4px; cursor: pointer;">
          Fechar
        </button>
      </div>
      <div id="debug-content">
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
          <div>
            <strong>Cache:</strong><br>
            Hits: <span id="debug-cache-hits">0</span><br>
            Misses: <span id="debug-cache-misses">0</span><br>
            Taxa: <span id="debug-cache-rate">0%</span>
          </div>
          <div>
            <strong>API:</strong><br>
            Chamadas: <span id="debug-api-calls">0</span><br>
            Erros: <span id="debug-api-errors">0</span>
          </div>
          <div>
            <strong>Performance:</strong><br>
            Render: <span id="debug-render-time">0ms</span><br>
            FPS: <span id="debug-fps">60</span>
          </div>
          <div>
            <strong>Memória:</strong><br>
            Uso: <span id="debug-memory">0MB</span><br>
            Elementos DOM: <span id="debug-dom-elements">0</span>
          </div>
        </div>
        <div style="margin-top: 10px;">
          <strong>Eventos Recentes:</strong><br>
          <div id="debug-events" style="max-height: 100px; overflow: auto; border: 1px solid var(--line); padding: 5px; font-size: 11px;"></div>
        </div>
      </div>
    `;
    
    document.body.appendChild(debugPanel);
  },
  
  toggleDebugPanel() {
    const panel = document.getElementById('debug-panel');
    if (panel.style.display === 'none') {
      panel.style.display = 'block';
      this.updateDebugPanel();
    } else {
      panel.style.display = 'none';
    }
  },
  
  updateMetrics() {
    const cacheTotal = this.metrics.cacheHits + this.metrics.cacheMisses;
    const cacheRate = cacheTotal > 0 ? (this.metrics.cacheHits / cacheTotal) * 100 : 0;
    
    this.metrics.cacheRate = cacheRate;
    
    // Atualizar métricas flutuantes
    const cacheRateElement = document.getElementById('floating-cache-rate');
    if (cacheRateElement) cacheRateElement.textContent = `${cacheRate.toFixed(0)}%`;
    
    const apiCallsElement = document.getElementById('floating-api-calls');
    if (apiCallsElement) apiCallsElement.textContent = this.metrics.apiCalls;
    
    const renderTimeElement = document.getElementById('floating-render-time');
    if (renderTimeElement) renderTimeElement.textContent = `${this.metrics.renderTime}ms`;
  },
  
  updateDebugPanel() {
    const cacheRate = this.metrics.cacheHits / Math.max(1, this.metrics.cacheHits + this.metrics.cacheMisses) * 100;
    
    document.getElementById('debug-cache-hits').textContent = this.metrics.cacheHits;
    document.getElementById('debug-cache-misses').textContent = this.metrics.cacheMisses;
    document.getElementById('debug-cache-rate').textContent = `${cacheRate.toFixed(0)}%`;
    document.getElementById('debug-api-calls').textContent = this.metrics.apiCalls;
    document.getElementById('debug-api-errors').textContent = this.metrics.apiErrors || 0;
    document.getElementById('debug-render-time').textContent = `${this.metrics.renderTime}ms`;
    document.getElementById('debug-fps').textContent = this.metrics.fps || 60;
    document.getElementById('debug-memory').textContent = `${this.metrics.memoryUsage}MB`;
    document.getElementById('debug-dom-elements').textContent = document.querySelectorAll('*').length;
  },
  
  logEvent(message) {
    const events = document.getElementById('debug-events');
    if (events) {
      const div = document.createElement('div');
      div.style.borderBottom = '1px solid var(--line)';
      div.style.padding = '2px';
      div.style.marginBottom = '2px';
      div.textContent = `${new Date().toLocaleTimeString()}: ${message}`;
      events.appendChild(div);
      events.scrollTop = events.scrollHeight;
    }
  },
  
  // Métodos auxiliares
  incrementCacheHit() { this.metrics.cacheHits++; },
  incrementCacheMiss() { this.metrics.cacheMisses++; },
  incrementApiCall(success = true) { 
    this.metrics.apiCalls++;
    if (!success) this.metrics.apiErrors++;
  },
  setRenderTime(time) { this.metrics.renderTime = time; },
  setFPS(fps) { this.metrics.fps = fps; },
  setMemoryUsage(usage) { this.metrics.memoryUsage = usage; }
};

// Otimizações de performance para renderização
const PerformanceOptimizer = {
  // Debounce para eventos de resize
  debounceResize: function(callback, delay = 250) {
    let timeoutId;
    return function() {
      clearTimeout(timeoutId);
      timeoutId = setTimeout(() => {
        callback();
        // Forçar recalculo apenas quando necessário
        requestAnimationFrame(() => {
          document.querySelectorAll('.wide').forEach(el => {
            el.style.display = 'none';
            setTimeout(() => el.style.display = '', 10);
          });
        });
      }, delay);
    };
  },
  
  // Throttle para scroll
  throttleScroll: function(callback, delay = 100) {
    let lastExecuted = 0;
    return function() {
      const now = Date.now();
      if (now - lastExecuted >= delay) {
        callback();
        lastExecuted = now;
      }
    };
  },
  
  // Observer para elementos dinâmicos
  setupMutationObserver: function() {
    const observer = new MutationObserver((mutations) => {
      let shouldUpdate = false;
      
      mutations.forEach(mutation => {
        if (mutation.addedNodes.length) {
          mutation.addedNodes.forEach(node => {
            if (node.nodeType === 1 && node.classList) {
              // Otimizar novos elementos adicionados
              if (node.classList.contains('card')) {
                this.optimizeCardElement(node);
              }
              if (node.classList.contains('wide')) {
                shouldUpdate = true;
              }
            }
          });
        }
      });
      
      if (shouldUpdate) {
        // Recalcular layouts apenas quando necessário
        this.debounceResize(() => {
          this.updateLayouts();
        }, 100)();
      }
    });
    
    observer.observe(document.body, {
      childList: true,
      subtree: true
    });
  },
  
  optimizeCardElement: function(card) {
    // Otimizações de performance para cards
    card.style.contain = 'layout style paint';
    card.style.willChange = 'auto';
    card.setAttribute('data-optimized', 'true');
  },
  
  updateLayouts: function() {
    // Recalcular grid apenas quando necessário
    const main = document.querySelector('main');
    if (main) {
      main.style.display = 'none';
      requestAnimationFrame(() => {
        main.style.display = '';
      });
    }
  },
  
  // Cache de elementos DOM frequentemente acessados
  domCache: new Map(),
  
  getElement: function(selector) {
    const cacheKey = `el:${selector}`;
    if (!this.domCache.has(cacheKey)) {
      const element = document.querySelector(selector);
      this.domCache.set(cacheKey, element);
    }
    return this.domCache.get(cacheKey);
  }
};

// Melhorar cache de voz
const VoiceCache = {
  cache: new Map(),
  maxSize: 20,
  audioCache: new Map(), // Cache separado para URLs de áudio
  
  get(key) {
    const item = this.cache.get(key);
    if (item && Date.now() - item.timestamp < item.ttl) {
      return item.audioUrl;
    }
    return null;
  },
  
  set(key, audioUrl, ttl = 3600000) { // 1 hora default
    if (this.cache.size >= this.maxSize) {
      const firstKey = this.cache.keys().next().value;
      this.cache.delete(firstKey);
    }
    
    this.cache.set(key, {
      audioUrl,
      timestamp: Date.now(),
      ttl
    });
  },
  
  // Cache específico para diferentes engines
  browser: new Map(),
  elevenlabs: new Map(),
  fish: new Map(),
  
  // Otimizações de performance para voz
  getOptimizedAudio: function(text, engine, options = {}) {
    const cacheKey = `audio:${engine}:${text.substring(0, 100)}`;
    const cached = this.audioCache.get(cacheKey);
    
    if (cached && !this.isExpired(cached)) {
      return cached.url;
    }
    
    // Gerar novo áudio
    const audioUrl = this.generateAudioUrl(text, engine, options);
    
    if (this.audioCache.size >= 50) {
      const firstKey = this.audioCache.keys().next().value;
      this.audioCache.delete(firstKey);
    }
    
    this.audioCache.set(cacheKey, {
      url: audioUrl,
      timestamp: Date.now(),
      ttl: 3600000
    });
    
    return audioUrl;
  },
  
  isExpired(item) {
    return Date.now() - item.timestamp > item.ttl;
  },
  
  generateAudioUrl: function(text, engine, options) {
    // Implementação simplificada - na prática seria uma chamada real para API
    const timestamp = Date.now();
    const hash = btoa(text).substring(0, 16);
    return `/api/audio?engine=${engine}&text=${encodeURIComponent(text)}&t=${timestamp}&hash=${hash}`;
  }
        }, 100);
        return;
      }
      
      // Fazer chamada real para IA
      PerformanceMonitor.incrementApiCall();
      fetch('/api/ia', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, context })
      })
      .then(response => {
        PerformanceMonitor.incrementApiCall(response.ok);
        return response.json();
      })
      .then(data => {
        AICache.set(`msg:${message}`, data.response, context);
        
        const log = document.getElementById('ia-log');
        const li = document.createElement('li');
        li.innerHTML = `<span>🤖 ${data.response}</span>`;
        log.appendChild(li);
        log.scrollTop = log.scrollHeight;
      })
      .catch(error => {
        PerformanceMonitor.incrementApiCall(false);
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
  document.getElementById("cbtech").hidden = !(cb || d.cbtechSemLogin);
  set("cb-aviso", d.cbtechSemLogin ? "Entre no admin da CBTECH (/CBTECH/auth/login.php) neste navegador para ver os dados do site." : "");
  if (cb) {
    set("cb-mat", cb.matriculas7d); set("cb-orc", cb.orcamentos7d); set("cb-atr", cb.orcamentosAtrasados);
    set("cb-msg", cb.mensagensNovas); set("cb-chat", cb.chatAguardando); set("cb-cli", cb.novosClientes7d);
  }
  const yt = d.youtube;
  document.getElementById("social").hidden = !yt;
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
  g.hidden = !d.receitaDiaria;
  document.querySelector("main").classList.toggle("sem-grafico", !d.receitaDiaria);
  if (d.receitaDiaria) desenharGrafico(d.receitaDiaria);
}

// Sessões do Claude Code, lidas do estado local do J.A.R.V.I.S. do Claude Code (só nesta máquina).
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
function carregarClaude() {
  fetch("claude-code.php", {cache: "no-store"}).then(r => r.ok ? r.json() : null).catch(() => null).then(cc => {
    const card = document.getElementById("claude");
    card.hidden = !(cc && cc.instalado);
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

async function falar(texto) {
  if (store.get("engine") === "elevenlabs" && store.get("elKey") && store.get("elVoice")) {
    try { await falarElevenLabs(texto); return; } catch (e) { console.warn(e); }
  }
  falarNavegador(texto);
}

document.getElementById("speak").onclick = async () => {
  if (!systemEnabled) return;
  await falar(textoBriefing(data));
};

// ---------- CHAT COM A IA (Ollama via server.js) ----------
const OLLAMA_API = "http://127.0.0.1:3000";
const iaLog = document.getElementById("ia-log");
const iaStatus = document.getElementById("ia-status");
const iaForm = document.getElementById("ia-form");
const iaInputEl = document.getElementById("ia-input");

function addIaLog(quem, texto, tag) {
  if (iaLog.firstElementChild && iaLog.firstElementChild.classList.contains("sub") && !iaLog.firstElementChild.dataset.msg) {
    iaLog.innerHTML = "";
  }
  const li = document.createElement("li");
  li.dataset.msg = "1";
  li.innerHTML = `<span class="tag t-${tag}">${esc(quem)}</span><span style="white-space:pre-wrap">${esc(texto)}</span>`;
  iaLog.appendChild(li);
  iaLog.scrollTop = iaLog.scrollHeight;
}

async function verificarIa() {
  try {
    const r = await fetch(`${OLLAMA_API}/health`, { cache: "no-store", signal: AbortSignal.timeout(3000) });
    const j = r.ok ? await r.json() : null;
    iaStatus.textContent = j ? "· IA local conectada" : "· IA local indisponível";
  } catch {
    iaStatus.textContent = "· IA local indisponível (rode node server.js)";
  }
}
verificarIa();
setInterval(verificarIa, 30000);

if (iaForm) {
  iaForm.onsubmit = async (e) => {
    e.preventDefault();
    if (!systemEnabled) return;
    const texto = iaInputEl.value.trim();
    if (!texto) return;
    iaInputEl.value = "";
    addIaLog("Você", texto, "ok");
    const sendBtn = document.getElementById("ia-send");
    iaInputEl.disabled = true;
    sendBtn.disabled = true;
    try {
      const r = await fetch(`${OLLAMA_API}/api/ia`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: texto }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Falha ao falar com a IA.");
      const resposta = j.reply || "Não obtive resposta, senhor.";
      addIaLog("JARVIS", resposta, "ok");
      falar(resposta);
    } catch (err) {
      addIaLog("JARVIS", "Não consegui falar com a IA local. Verifique se o Ollama e o server.js estão em execução.", "bad");
      console.warn(err);
    } finally {
      iaInputEl.disabled = !systemEnabled;
      sendBtn.disabled = !systemEnabled;
      iaInputEl.focus();
    }
  };
}

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
