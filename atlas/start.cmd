@echo off
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, multipart, PIL" >nul 2>nul
if errorlevel 1 ".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m atlas.seed
if errorlevel 1 exit /b 1
echo Open http://127.0.0.1:18182/
".venv\Scripts\python.exe" -m uvicorn atlas.server:app --host 127.0.0.1 --port 18182
pause
