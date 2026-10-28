@echo off
setlocal

echo =======================================
echo Testes da API local em 127.0.0.1:3000
echo =======================================
echo.

echo [1/3] GET /health
curl.exe -sS http://127.0.0.1:3000/health
echo.
echo.

echo [2/3] GET /api/models
curl.exe -sS http://127.0.0.1:3000/api/models
echo.
echo.

echo [3/3] POST /api/ia
curl.exe -sS -X POST http://127.0.0.1:3000/api/ia -H "Content-Type: application/json" -d "{\"message\":\"Ol\u00e1\"}"
echo.
echo.

echo =======================================
echo Testes finalizados.
echo Se alguma rota falhar, confira se:
echo - o server.js est\u00e1 rodando
echo - o Ollama est\u00e1 ativo em 127.0.0.1:11434
echo =======================================
echo.

endlocal
