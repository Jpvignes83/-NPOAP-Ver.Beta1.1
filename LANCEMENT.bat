@echo off
setlocal EnableExtensions
chcp 65001 >nul
REM ============================================================
REM Lancement NPOAP - environnement conda astroenv (Python 3.11+)
REM Installation type: installation.bat
REM Sans activate.bat ^(souvent casse dans cmd sans conda init^) : python.exe direct ou conda run.
REM ============================================================

title NPOAP - Lancement

cd /d "%~dp0"

set "CONDA_CMD="
if exist "%ProgramData%\Miniconda3\Scripts\conda.exe" set "CONDA_CMD=%ProgramData%\Miniconda3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%USERPROFILE%\Miniconda3\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\Miniconda3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\miniconda3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%LOCALAPPDATA%\miniconda3\Scripts\conda.exe" set "CONDA_CMD=%LOCALAPPDATA%\miniconda3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%LOCALAPPDATA%\Miniconda3\Scripts\conda.exe" set "CONDA_CMD=%LOCALAPPDATA%\Miniconda3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%LOCALAPPDATA%\anaconda3\Scripts\conda.exe" set "CONDA_CMD=%LOCALAPPDATA%\anaconda3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%LOCALAPPDATA%\Anaconda3\Scripts\conda.exe" set "CONDA_CMD=%LOCALAPPDATA%\Anaconda3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%ProgramData%\Anaconda3\Scripts\conda.exe" set "CONDA_CMD=%ProgramData%\Anaconda3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%USERPROFILE%\Anaconda3\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\Anaconda3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\anaconda3\Scripts\conda.exe"

if not defined CONDA_CMD (
    where conda >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%C in ('where conda 2^>nul') do (
            echo %%C | findstr /i /e "conda.exe" >nul
            if not errorlevel 1 (
                set "CONDA_CMD=%%C"
                goto :conda_cmd_done
            )
        )
        for /f "delims=" %%C in ('where conda 2^>nul') do (
            set "CONDA_CMD=%%C"
            goto :conda_cmd_done
        )
    )
)
:conda_cmd_done

if not defined CONDA_CMD (
    echo ERREUR: conda.exe introuvable. Installez Miniconda et l'environnement astroenv ^(installation.bat^).
    pause
    exit /b 1
)

set "CONDA_ROOT="
for /f "delims=" %%i in ('"%CONDA_CMD%" info --base 2^>nul') do (
    set "CONDA_ROOT=%%i"
    goto :conda_root_done
)
:conda_root_done

if not defined CONDA_ROOT (
    for %%I in ("%CONDA_CMD%\..") do set "CONDA_ROOT=%%~fI"
)

if not defined CONDA_ROOT (
    echo ERREUR: impossible de determiner la racine conda.
    pause
    exit /b 1
)

set "PYTHONNOUSERSITE=1"
set "PIP_USER="
if /i "%NPOAP_ALLOW_USERSITE%"=="1" (
    set "PYTHONNOUSERSITE="
)

set "PY_ASTRO=%CONDA_ROOT%\envs\astroenv\python.exe"
set "CONDA_EXE=%CONDA_ROOT%\Scripts\conda.exe"

if not exist "main.py" (
    echo Erreur: main.py non trouve dans %CD%
    pause
    exit /b 1
)

if not exist "logs" mkdir logs

if exist "%PY_ASTRO%" goto :run_py_direct
if exist "%CONDA_EXE%" goto :run_py_conda_run

echo ERREUR: environnement astroenv introuvable : %PY_ASTRO%
echo conda create -n astroenv python=3.11 -y
pause
exit /b 1

:run_py_direct
"%PY_ASTRO%" main.py
set "EXITCODE=%ERRORLEVEL%"
goto :after_py

:run_py_conda_run
echo Avertissement: python direct introuvable - conda run...
"%CONDA_EXE%" run -n astroenv --no-capture-output python main.py
set "EXITCODE=%ERRORLEVEL%"
goto :after_py

:after_py
if "%EXITCODE%"=="0" exit /b 0
echo.
echo Erreur lors du lancement ^(code %EXITCODE%^).
echo Dependances : pip install -r requirements_install_core.txt dans astroenv
pause
exit /b %EXITCODE%
