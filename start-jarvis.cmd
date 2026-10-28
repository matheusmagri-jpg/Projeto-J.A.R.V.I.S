@echo off
setlocal
set "URL=http://localhost:8080/jarvis/dashboard.html"
set "ROOT=C:\xampp\htdocs\jarvis"

where curl >nul 2>nul
if not errorlevel 1 (
    curl -I "%URL%" >nul 2>nul
    if not errorlevel 1 (
        echo JARVIS ja esta respondendo em %URL%
        start "" "%URL%"
        exit /b 0
    )
)

rem Verifica se o Apache do XAMPP esta rodando.
tasklist /FI "IMAGENAME eq httpd.exe" 2>nul | find /I "httpd.exe" >nul
if errorlevel 1 (
    echo Iniciando XAMPP Apache...
    if exist "C:\xampp\xampp_start.exe" (
        start "" "C:\xampp\xampp_start.exe"
    ) else if exist "C:\xampp\apache\bin\httpd.exe" (
        start "" /b "C:\xampp\apache\bin\httpd.exe"
    )
    timeout /t 6 /nobreak >nul
)

start "" "%URL%"
echo JARVIS aberto em %URL%
exit /b 0
