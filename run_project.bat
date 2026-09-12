@echo off
REM ============================================================================
REM  Support Agent (متجر النخبة) - single-click launcher for Windows
REM
REM  Starts the whole system: Flask/LangGraph backend + React frontend.
REM  All paths are resolved relative to this file, so it works from anywhere.
REM
REM  Usage:
REM    run_project.bat              launch everything
REM    run_project.bat /dryrun      run every check and print what WOULD happen,
REM                                 without creating windows or opening a browser
REM ============================================================================

setlocal EnableDelayedExpansion

set "ROOT=%~dp0"
set "ROOT_NS=%ROOT:~0,-1%"
if "%ROOT_NS:~-1%"==":" set "ROOT_NS=%ROOT_NS%\"

set "BACKEND=%ROOT_NS%\backend"
set "FRONTEND=%ROOT_NS%\frontend"
set "ENV_FILE=%ROOT_NS%\.env"
set "ENV_EXAMPLE=%ROOT_NS%\.env.example"
set "BACKEND_ENV=%BACKEND%\.env"
set "DB_FILE=%BACKEND%\database\support.db"
set "REQUIREMENTS=%BACKEND%\requirements.txt"
set "BACKEND_URL=http://localhost:5000"
set "FRONTEND_URL=http://localhost:3000"
set "VENV="
set "DRYRUN=0"

if /i "%~1"=="/dryrun" set "DRYRUN=1"
if /i "%~1"=="--dry-run" set "DRYRUN=1"
if /i "%~1"=="/check" set "DRYRUN=1"

title Support Agent - Launcher

echo ============================================================================
echo   Support Agent - launcher
echo   project root : %ROOT_NS%
if "%DRYRUN%"=="1" echo   MODE         : DRY RUN (nothing will be launched)
echo ============================================================================
echo.

if not exist "%BACKEND%\app.py" (
    echo [ERROR] backend\app.py not found under "%ROOT_NS%".
    echo         Put this script in the project root and try again.
    goto :fail
)
if not exist "%FRONTEND%\package.json" (
    echo [ERROR] frontend\package.json not found under "%ROOT_NS%".
    echo         Put this script in the project root and try again.
    goto :fail
)

REM ---------------------------------------------------------------------------
REM 1. Toolchain checks
REM ---------------------------------------------------------------------------
echo [1/6] Checking required tools...
where python >nul 2>&1
if errorlevel 1 (
    echo       [ERROR] "python" was not found in PATH.
    echo               Install Python 3.12 and make sure it is added to PATH.
    goto :fail
)
where node >nul 2>&1
if errorlevel 1 (
    echo       [ERROR] "node" was not found in PATH.
    echo               Install Node.js 18+ and make sure it is added to PATH.
    goto :fail
)
where npm >nul 2>&1
if errorlevel 1 (
    echo       [ERROR] "npm" was not found in PATH.
    goto :fail
)
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYVER=%%V"
for /f "delims=" %%V in ('node --version 2^>^&1') do set "NODEVER=%%V"
echo       [OK] %PYVER% / node %NODEVER% / npm available

REM ---------------------------------------------------------------------------
REM 2. Environment file (.env) - created only when missing, never overwritten
REM ---------------------------------------------------------------------------
echo.
echo [2/6] Checking environment file...
if exist "%ENV_FILE%" (
    echo       [OK] %ENV_FILE%
) else (
    if exist "%BACKEND_ENV%" (
        copy /y "%BACKEND_ENV%" "%ENV_FILE%" >nul
        echo       [WARN] .env was missing at the project root; copied it from backend\.env
        echo              ^(config.py loads .env from the project root^).
    ) else if exist "%ENV_EXAMPLE%" (
        copy /y "%ENV_EXAMPLE%" "%ENV_FILE%" >nul
        echo       [WARN] .env was missing - created it from .env.example
        echo              Open "%ENV_FILE%" and set COMMANDCODE_API_KEY=... before use.
    ) else (
        echo       [ERROR] no .env and no .env.example found in "%ROOT_NS%".
        goto :fail
    )
)

set "APIKEY="
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"COMMANDCODE_API_KEY=" "%ENV_FILE%" 2^>nul`) do set "APIKEY=%%B"
set "APIKEY=!APIKEY: =!"
if "!APIKEY!"=="" (
    echo.
    echo       [WARNING] COMMANDCODE_API_KEY is empty in .env
    echo                 The backend will refuse to answer ^(by design - no silent fallback^).
    echo                 Edit:  %ENV_FILE%
    echo.
    if "%DRYRUN%"=="0" (
        choice /c YN /n /m "      Continue anyway? [Y/N] "
        if errorlevel 2 goto :cancelled
    )
) else (
    echo       [OK] COMMANDCODE_API_KEY is set
)

REM ---------------------------------------------------------------------------
REM 3. Virtual environment + Python dependencies
REM ---------------------------------------------------------------------------
echo.
echo [3/6] Checking Python virtual environment...
if exist "%ROOT_NS%\.venv\Scripts\python.exe" set "VENV=%ROOT_NS%\.venv"
if not defined VENV if exist "%ROOT_NS%\venv\Scripts\python.exe" set "VENV=%ROOT_NS%\venv"

if defined VENV (
    echo       [OK] found %VENV%
) else (
    echo       [INFO] no virtual environment found - creating .venv ...
    if "%DRYRUN%"=="1" (
        echo              would run: py -3.12 -m venv "%ROOT_NS%\.venv" ^(or python -m venv^)
        set "VENV=%ROOT_NS%\.venv"
    ) else (
        where py >nul 2>&1
        if errorlevel 1 (
            python -m venv "%ROOT_NS%\.venv"
        ) else (
            py -3.12 -m venv "%ROOT_NS%\.venv" 2>nul
            if errorlevel 1 py -3 -m venv "%ROOT_NS%\.venv"
            if errorlevel 1 python -m venv "%ROOT_NS%\.venv"
        )
        if not exist "%ROOT_NS%\.venv\Scripts\python.exe" (
            echo       [ERROR] failed to create the virtual environment.
            echo               TensorFlow has no wheels for Python 3.14; install Python 3.12.
            goto :fail
        )
        set "VENV=%ROOT_NS%\.venv"
        echo       [OK] created %VENV%
    )
)

echo.
echo       Checking backend dependencies...
"%VENV%\Scripts\python.exe" -c "import flask, langgraph, tensorflow" >nul 2>&1
if errorlevel 1 (
    echo       [INFO] some backend requirements are missing.
    if "%DRYRUN%"=="1" (
        echo              would run: "%VENV%\Scripts\python.exe" -m pip install -r "%REQUIREMENTS%"
    ) else (
        choice /c YN /n /m "      Install backend requirements now (may take several minutes)? [Y/N] "
        if errorlevel 2 (
            echo       [WARN] skipped install - the backend may fail to start.
        ) else (
            "%VENV%\Scripts\python.exe" -m pip install -r "%REQUIREMENTS%"
            if errorlevel 1 (
                echo       [ERROR] pip install failed - see the output above.
                goto :fail
            )
            echo       [OK] backend requirements installed
        )
    )
) else (
    echo       [OK] backend dependencies present
)

REM ---------------------------------------------------------------------------
REM 4. Frontend dependencies
REM ---------------------------------------------------------------------------
echo.
echo [4/6] Checking frontend dependencies...
if exist "%FRONTEND%\node_modules" (
    echo       [OK] frontend\node_modules present
) else (
    echo       [INFO] frontend\node_modules is missing.
    if "%DRYRUN%"=="1" (
        echo              would run: cd /d "%FRONTEND%" && npm install
    ) else (
        pushd "%FRONTEND%"
        call npm install
        set "NPM_RC=!errorlevel!"
        popd
        if not "!NPM_RC!"=="0" (
            echo       [ERROR] npm install failed with code !NPM_RC!.
            goto :fail
        )
        echo       [OK] frontend dependencies installed
    )
)

REM ---------------------------------------------------------------------------
REM 5. Database
REM ---------------------------------------------------------------------------
echo.
echo [5/6] Checking database...
if exist "%DB_FILE%" (
    echo       [OK] %DB_FILE%
) else (
    echo       [INFO] database missing - seeding fresh data ...
    if "%DRYRUN%"=="1" (
        echo              would run: "%VENV%\Scripts\python.exe" "%BACKEND%\database\seed_data.py"
    ) else (
        pushd "%BACKEND%"
        "%VENV%\Scripts\python.exe" "%BACKEND%\database\seed_data.py"
        set "SEED_RC=!errorlevel!"
        popd
        if not "!SEED_RC!"=="0" (
            echo       [ERROR] seeding failed with code !SEED_RC!.
            goto :fail
        )
        echo       [OK] database seeded
    )
)

REM ---------------------------------------------------------------------------
REM 6. Launch both services
REM ---------------------------------------------------------------------------
echo.
echo [6/6] Starting services...
netstat -ano | findstr /r /c:":5000 .*LISTENING" >nul 2>&1
if not errorlevel 1 echo       [WARN] port 5000 is already in use - the backend may fail to bind.
netstat -ano | findstr /r /c:":3000 .*LISTENING" >nul 2>&1
if not errorlevel 1 echo       [WARN] port 3000 is already in use - the frontend may pick another port.

if "%DRYRUN%"=="1" (
    echo.
    echo       would start: start "Support Agent - Backend (Flask/LangGraph)" cmd /k ""%VENV%\Scripts\python.exe" "%BACKEND%\app.py""
    echo       would start: start "Support Agent - Frontend (React)" cmd /k "cd /d "%FRONTEND%" && set BROWSER=none && npm start"
    echo       would open : %FRONTEND_URL%
    echo.
    echo Dry run finished - nothing was launched.
    goto :done
)

start "Support Agent - Backend (Flask/LangGraph)" cmd /k ""%VENV%\Scripts\python.exe" "%BACKEND%\app.py""
echo       [OK] backend window launched

start "Support Agent - Frontend (React)" cmd /k "cd /d "%FRONTEND%" && set BROWSER=none && npm start"
echo       [OK] frontend window launched

echo       waiting a few seconds for the services to come up ...
ping -n 5 127.0.0.1 >nul

start "" "%FRONTEND_URL%"

echo.
echo ============================================================================
echo   Support Agent is starting up
echo ============================================================================
echo   Frontend (React)              : %FRONTEND_URL%
echo   Backend  (Flask/LangGraph)    : %BACKEND_URL%
echo   Health check                  : %BACKEND_URL%/health
echo   Chat API                      : POST %BACKEND_URL%/api/chat
echo   History API                   : GET  %BACKEND_URL%/api/history/^<session_id^>
echo.
echo   Two separate windows were opened:
echo     - "Support Agent - Backend (Flask/LangGraph)"  (port 5000)
echo     - "Support Agent - Frontend (React)"           (port 3000)
echo.
echo   To stop the system safely: close those two windows, or press Ctrl+C
echo   inside each of them. Closing them releases ports 5000 and 3000.
echo.
echo   The React dev server needs a few more seconds before it answers.
echo   This launcher window can be closed now.
echo ============================================================================
goto :done

:cancelled
echo.
echo Cancelled by user - nothing was launched.
goto :done

:fail
echo.
echo Launcher stopped because of the error above.
endlocal
pause
exit /b 1

:done
endlocal
