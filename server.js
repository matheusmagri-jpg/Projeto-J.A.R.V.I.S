/*
  Salve este arquivo como server.js na pasta do seu projeto.
  Abra o Prompt de Comando nessa pasta e execute: node server.js

  Testes em outro Prompt de Comando:
  curl.exe http://127.0.0.1:3000/health
  curl.exe http://127.0.0.1:3000/api/models
  curl.exe -X POST http://127.0.0.1:3000/api/ia -H "Content-Type: application/json" -d "{\"message\":\"Olá\"}"

  O servidor escuta apenas em 127.0.0.1, para não expor a API na rede.
  Requer Node.js 18 ou superior; não precisa instalar Express nem outros pacotes.
*/

const http = require("node:http");
const path = require("node:path");

// Segredos ficam no .env ao lado deste arquivo (OLLAMA_API_KEY, OLLAMA_URL...).
try {
  process.loadEnvFile(path.join(__dirname, ".env"));
} catch {}

const port = Number(process.env.PORT || 3000);
const ollamaUrl = (process.env.OLLAMA_URL || "http://127.0.0.1:11434")
  .replace(/\/+$/, "");
const model = process.env.OLLAMA_MODEL || "qwen2.5:3b";
const maxBodyBytes = 20 * 1024;
let systemEnabled = true;
// A chave só é usada pelo Ollama na nuvem (OLLAMA_URL=https://ollama.com); o local ignora.
const ollamaHeaders = process.env.OLLAMA_API_KEY
  ? { Authorization: `Bearer ${process.env.OLLAMA_API_KEY}` }
  : {};

function sendJson(res, status, data) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type"
  });
  res.end(JSON.stringify(data));
}

async function readJson(req) {
  let body = "";
  let bytes = 0;

  for await (const chunk of req) {
    bytes += chunk.length;
    if (bytes > maxBodyBytes) {
      const error = new Error("O corpo da requisição excede 20 KB.");
      error.status = 413;
      throw error;
    }
    body += chunk.toString("utf8");
  }

  try {
    return JSON.parse(body || "{}");
  } catch {
    const error = new Error("O corpo da requisição precisa ser um JSON válido.");
    error.status = 400;
    throw error;
  }
}

const server = http.createServer(async (req, res) => {
  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type"
    });
    return res.end();
  }

  const url = new URL(req.url, `http://${req.headers.host || "127.0.0.1"}`);

  if (req.method === "GET" && url.pathname === "/health") {
    return sendJson(res, 200, { status: "ok", enabled: systemEnabled });
  }

  if (req.method === "GET" && url.pathname === "/api/system") {
    return sendJson(res, 200, { enabled: systemEnabled, status: systemEnabled ? "ligado" : "desligado" });
  }

  if ((req.method === "POST" || req.method === "PUT") && url.pathname === "/api/system") {
    try {
      const body = await readJson(req);
      if (typeof body.enabled !== "boolean") {
        return sendJson(res, 400, { error: "Envie 'enabled' em booleano." });
      }
      systemEnabled = body.enabled;
      return sendJson(res, 200, { enabled: systemEnabled, status: systemEnabled ? "ligado" : "desligado" });
    } catch (error) {
      if (error.status) return sendJson(res, error.status, { error: error.message });
      return sendJson(res, 500, { error: "Falha ao atualizar o estado do sistema." });
    }
  }

  if (req.method === "GET" && url.pathname === "/api/models") {
    try {
      const response = await fetch(`${ollamaUrl}/api/tags`, {
        headers: ollamaHeaders,
        signal: AbortSignal.timeout(10_000)
      });

      if (!response.ok) {
        return sendJson(res, 502, {
          error: "O Ollama retornou um erro ao listar os modelos."
        });
      }

      return sendJson(res, 200, await response.json());
    } catch {
      return sendJson(res, 503, {
        error: "Não foi possível conectar ao Ollama em 127.0.0.1:11434."
      });
    }
  }

  if (req.method === "POST" && url.pathname === "/api/ia") {
    if (!systemEnabled) {
      return sendJson(res, 503, {
        error: "Sistema desligado pelo interruptor mestre. Ligue o JARVIS para continuar."
      });
    }

    try {
      const body = await readJson(req);
      const message = body.message;

      if (typeof message !== "string" || !message.trim()) {
        return sendJson(res, 400, {
          error: "Envie uma mensagem de texto no campo 'message'."
        });
      }

      if (message.length > 4000) {
        return sendJson(res, 413, {
          error: "A mensagem deve ter no máximo 4.000 caracteres."
        });
      }

      const response = await fetch(`${ollamaUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...ollamaHeaders },
        body: JSON.stringify({
          model,
          stream: false,
          messages: [
            {
              role: "system",
              content: "Responda com clareza, precisão e em português do Brasil."
            },
            { role: "user", content: message.trim() }
          ]
        }),
        signal: AbortSignal.timeout(120_000)
      });

      if (!response.ok) {
        return sendJson(res, 502, {
          error: "O Ollama retornou um erro ao gerar a resposta.",
          detail: await response.text()
        });
      }

      const data = await response.json();
      return sendJson(res, 200, {
        reply: data.message?.content || "",
        model
      });
    } catch (error) {
      if (error.status) {
        return sendJson(res, error.status, { error: error.message });
      }

      const timedOut = error.name === "TimeoutError";
      return sendJson(res, timedOut ? 504 : 503, {
        error: timedOut
          ? "A IA demorou demais para responder."
          : "Não foi possível conectar ao Ollama. Verifique se ele está em execução."
      });
    }
  }

  return sendJson(res, 404, { error: "Rota não encontrada." });
});

server.listen(port, "127.0.0.1", () => {
  console.log(`API disponível em http://127.0.0.1:${port}`);
  console.log(`Modelo configurado: ${model}`);
});
