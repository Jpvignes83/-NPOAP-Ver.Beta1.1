@echo off
setlocal EnableExtensions
chcp 65001 >nul
REM ============================================================
REM Lancement NPOAP - environnement conda astroenv
REM - Detection conda alignee sur installation.bat (chemins usuels + where).
REM - Pas d'appel a activate.bat : sous cmd sans "conda init", activate
REM   echoue souvent alors que %CONDA_ROOT%\envs\astroenv\python.exe suffit.
REM - Secours : conda run -n astroenv python main.py
REM ============================================================

title NPOAP - Lancement (astroenv)

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
    echo ERREUR: conda.exe introuvable. Installez Miniconda puis creez astroenv ^(installation.bat^).
    echo Chemins testes : ProgramData et %%USERPROFILE%%\Miniconda3, %%LOCALAPPDATA%%\miniconda3, etc.
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
    echo ERREUR: impossible de determiner la racine conda ^(conda info --base^).
    pause
    exit /b 1
)

set "PY_ASTRO=%CONDA_ROOT%\envs\astroenv\python.exe"
set "CONDA_EXE=%CONDA_ROOT%\Scripts\conda.exe"

REM Par defaut : isolation conda — pas de site-packages utilisateur Windows
REM Pour autoriser ce site ^(cas rare^) : definir NPOAP_ALLOW_USERSITE=1 avant ce script.
set "PYTHONNOUSERSITE=1"
set "PIP_USER="
if /i "%NPOAP_ALLOW_USERSITE%"=="1" (
    set "PYTHONNOUSERSITE="
)

REM Backend Prospector: WSL par defaut (FSPS Linux), surchargeable via variable d'environnement.
if not defined NPOAP_PROSPECTOR_BACKEND set "NPOAP_PROSPECTOR_BACKEND=wsl"

REM CUDA_PATH pour CuPy / acceleration GPU (si toolkit NVIDIA installe)
if not defined CUDA_PATH (
    if exist "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.4\bin" set "CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.4"
)
if not defined CUDA_PATH (
    if exist "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.1\bin" set "CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.1"
)
if not defined CUDA_PATH (
    if exist "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\bin" set "CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6"
)
if not defined CUDA_PATH (
    if exist "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.5\bin" set "CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.5"
)
if not defined CUDA_PATH (
    if exist "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.2\bin" set "CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.2"
)
if not defined CUDA_PATH (
    if exist "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\bin" set "CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8"
)

if not exist "main.py" (
    echo Erreur: main.py non trouve dans %CD%
    pause
    exit /b 1
)

if not exist "logs" mkdir logs

REM Methode 1 : interprete de l'environnement ^(sans activate.bat^)
REM Pas de bloc parenthese autour de python : sinon %%ERRORLEVEL%% est fige au parse.
if exist "%PY_ASTRO%" goto :run_py_direct

REM Methode 2 : conda run ^(meme si envs\astroenv est absent ou deplace^)
if exist "%CONDA_EXE%" goto :run_py_conda_run

echo ERREUR: environnement astroenv introuvable.
echo Attendu : "%PY_ASTRO%"
echo Creez-le avec : conda create -n astroenv python=3.11 -y
echo puis : pip install -r requirements_install_core.txt ^(voir README installation^).
pause
exit /b 1

:run_py_direct
"%PY_ASTRO%" main.py
set "EXITCODE=%ERRORLEVEL%"
goto :after_py

:run_py_conda_run
echo Avertissement: "%PY_ASTRO%" introuvable - tentative avec conda run...
"%CONDA_EXE%" run -n astroenv --no-capture-output python main.py
set "EXITCODE=%ERRORLEVEL%"
goto :after_py

:after_py
if "%EXITCODE%"=="0" exit /b 0
echo.
echo ERREUR lors du lancement de NPOAP ^(code %EXITCODE%^).
pause
exit /b %EXITCODE%
