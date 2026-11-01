@echo off
REM Builds dist\Nexa\Nexa.exe  (run setup.bat once before this).
setlocal
cd /d "%~dp0"

if not exist .venv (
    echo Run setup.bat first.
    exit /b 1
)
call .venv\Scripts\activate.bat || goto :fail

echo [1/4] Installing build tool...
pip install -r requirements-build.txt || goto :fail

echo [2/4] Building the React UI...
pushd frontend
call npm install || (popd & goto :fail)
call npm run build || (popd & goto :fail)
popd

echo [3/4] Packaging with PyInstaller (takes a few minutes)...
pyinstaller nexa.spec --noconfirm --clean || goto :fail

echo [4/4] Preparing the output folder...
copy /y .env.example dist\Nexa\.env.example >nul

echo.
echo ================================================================
echo  Done:  dist\Nexa\Nexa.exe
echo.
echo  To use it or share it:
echo    1. Copy the whole dist\Nexa folder (not just Nexa.exe).
echo    2. In that folder, rename .env.example to .env and add your API key.
echo    3. Double-click Nexa.exe.
echo.
echo  Your own .env is NOT packed into the build, so your keys are not shared.
echo ================================================================
exit /b 0

:fail
echo.
echo Build failed - see the messages above.
exit /b 1
