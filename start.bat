@echo off
title Bot Benzina
echo ============================
echo   BOT BENZINA - Deploy
echo ============================

if not exist .env (
    echo.
    echo [ERRORE] File .env non trovato!
    echo Copia .env.example in .env e compila i valori.
    pause
    exit /b 1
)

where docker >nul 2>nul
if %errorlevel% neq 0 (
    echo Docker non trovato. Installa Docker Desktop.
    pause
    exit /b 1
)

echo Avvio container...
docker compose up -d --build

echo.
echo ============================
echo   BOT IN ESECUZIONE
echo   Logs: docker compose logs -f
echo   Stop: docker compose down
echo ============================
pause
