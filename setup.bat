@echo off
REM One-time setup for Nexa on Windows: Python venv + dependencies + frontend build.
setlocal
cd /d "%~dp0"

if not exist .venv (
    python -m venv .venv || goto :fail
)
call .venv\Scripts\activate.bat || goto :fail
python -m pip install --upgrade pip || goto :fail
pip install -r requirements.txt || goto :fail

if not exist .env (
    copy .env.example .env >nul
    echo Created .env - open it and add your GEMINI_API_KEY and/or GROQ_API_KEY.
)

pushd frontend
call npm install || (popd & goto :fail)
call npm run build || (popd & goto :fail)
popd

echo.
echo Setup complete. Edit .env, then double-click run.bat
exit /b 0

:fail
echo.
echo Setup failed - see the messages above.
exit /b 1
