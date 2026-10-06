@echo off
echo ========================================
echo  Restarting Backend Server
echo ========================================
echo.

REM Find and kill any running Python processes in this directory
echo Stopping any running backend servers...
FOR /F "tokens=2" %%i IN ('tasklist /FI "IMAGENAME eq python.exe" /NH') DO (
    taskkill /PID %%i /F 2>nul
)

timeout /t 2 /nobreak >nul
echo.

echo Starting backend server...
echo Make sure PostgreSQL and Redis are running!
echo.
echo Server will be available at: http://localhost:8000
echo API docs at: http://localhost:8000/docs
echo.

cd /d "%~dp0"
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
