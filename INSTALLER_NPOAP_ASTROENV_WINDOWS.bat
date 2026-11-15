@echo off
setlocal EnableDelayedExpansion
REM ===================================================================
REM NPOAP -- Installation dans l'environnement Conda "astroenv"
REM ===================================================================
REM A placer a la racine de la distribution (main.py, requirements.txt).
REM Tous les profils (full, reduction, exoplanets, photometrie_exoplanetes,
REM ...) utilisent le meme environnement conda "astroenv" (Python 3.11)
REM et le requirements.txt fourni avec cette distribution.
REM
REM Important : ce fichier doit rester en ASCII pur (pas de caracteres
REM accentues ni de guillemets typographiques). cmd.exe lit les .bat avec
REM la codepage systeme et casse sur les sequences UTF-8 multi-octets.
REM
REM Prerequis : Miniconda ou Anaconda ;
REM   https://docs.conda.io/en/latest/miniconda.html
REM Optionnel MSVC Build Tools pour PHOEBE -- voir docs\MANUEL_INSTALLATION.md
REM Paquets Git (ex. ezpadova) : Git dans le PATH
REM ===================================================================

title NPOAP -- Installation conda astroenv

cd /d "%~dp0"

echo.
echo ============================================================
echo   NPOAP -- Installation environnement conda "astroenv"
echo ============================================================
echo.
echo Dossier : %CD%
echo.

if not exist "requirements.txt" (
    echo ERREUR: requirements.txt introuvable.
    pause
    exit /b 1
)

REM --- Localiser conda (exe de preference pour "info --base") ---
REM AllUsers Miniconda : souvent absent du PATH dans une cmd "neuve" (comme double-clic .bat).
set "CONDA_EXE="
if exist "%ProgramData%\Miniconda3\Scripts\conda.exe" set "CONDA_EXE=%ProgramData%\Miniconda3\Scripts\conda.exe"
if not defined CONDA_EXE if exist "%ProgramData%\Anaconda3\Scripts\conda.exe" set "CONDA_EXE=%ProgramData%\Anaconda3\Scripts\conda.exe"
if not defined CONDA_EXE if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" set "CONDA_EXE=%USERPROFILE%\miniconda3\Scripts\conda.exe"
if not defined CONDA_EXE if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" set "CONDA_EXE=%USERPROFILE%\anaconda3\Scripts\conda.exe"
if not defined CONDA_EXE if exist "%LocalAppData%\miniconda3\Scripts\conda.exe" set "CONDA_EXE=%LocalAppData%\miniconda3\Scripts\conda.exe"
if not defined CONDA_EXE (
    where conda >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "delims=" %%C in ('where conda 2^>nul') do (
            set "CAND=%%C"
            if /i "!CAND:~-9!"=="\conda.bat" (
                for %%P in ("!CAND!\..\Scripts\conda.exe") do if exist "%%~fP" set "CONDA_EXE=%%~fP"
            )
            if /i "!CAND:~-10!"=="\conda.exe" set "CONDA_EXE=!CAND!"
            if defined CONDA_EXE goto :found_conda
        )
    )
)
:found_conda
if not defined CONDA_EXE (
    echo ERREUR: conda introuvable.
    echo Installez Miniconda ^(Windows, Python 3.11^) :
    echo   https://docs.conda.io/en/latest/miniconda.html
    echo Puis rouvrez ce script ^(PATH ou relance du terminal^).
    pause
    exit /b 1
)

for /f "delims=" %%B in ('"!CONDA_EXE!" info --base 2^>nul') do set "CONDA_ROOT=%%B"
if not defined CONDA_ROOT (
    echo ERREUR: impossible de determiner le repertoire de base conda.
    pause
    exit /b 1
)

echo Conda : !CONDA_EXE!
echo Base  : !CONDA_ROOT!
"!CONDA_EXE!" --version
echo.

set "ASTRO_PY=!CONDA_ROOT!\envs\astroenv\python.exe"
if not exist "!ASTRO_PY!" (
    echo Creation de l'environnement "astroenv" ^(python=3.11^)...
    "!CONDA_EXE!" create -n astroenv python=3.11 -y
    if errorlevel 1 (
        echo ERREUR: conda create -n astroenv a echoue.
        pause
        exit /b 1
    )
) else (
    echo Environnement "astroenv" deja present.
)

REM Pip en session utilisateur : Miniconda sous ProgramData refuse souvent
REM les ecritures dans site-packages sans ACE Utilisateurs.
set "ASTRO_ENV_ROOT=!CONDA_ROOT!\envs\astroenv"
if exist "!ASTRO_ENV_ROOT!" (
    echo Ajustement des droits ecriture ^(groupe Utilisateurs / pip^) sur l'environnement...
    icacls "!ASTRO_ENV_ROOT!" /grant "*S-1-5-32-545:(OI)(CI)M" /T >nul 2>&1
    if !errorLevel! neq 0 (
        echo ATTENTION : icacls a echoue. En cas d'"Acces refuse" au pip :
        echo   - executer ce script en administrateur, ou
        echo   - icacls "!ASTRO_ENV_ROOT!" /grant "*S-1-5-32-545:(OI)(CI)M" /T
    )
)

if not exist "!CONDA_ROOT!\Scripts\activate.bat" (
    echo ERREUR: activate.bat introuvable.
    pause
    exit /b 1
)

call "!CONDA_ROOT!\Scripts\activate.bat" astroenv
if errorlevel 1 (
    echo ERREUR: impossible d'activer astroenv.
    pause
    exit /b 1
)

set "PYTHONNOUSERSITE=1"
set "PIP_USER="

"!ASTRO_PY!" -c "import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)" 2>nul
if errorlevel 1 (
    echo.
    echo ATTENTION: le Python d'astroenv est ^< 3.11. Commandes conseillees :
    echo   conda activate astroenv
    echo   conda install "python>=3.11" -y
    echo.
    set /p CONTINUE="Continuer quand meme pip install -r requirements.txt ? (O/N): "
    if /i not "!CONTINUE!"=="O" exit /b 1
)

echo.
echo Mise a jour de pip...
"!ASTRO_PY!" -m pip install --upgrade pip
if errorlevel 1 (
    echo ERREUR: mise a jour pip.
    pause
    exit /b 1
)

echo.
echo Installation des paquets depuis requirements.txt...
echo ^(selon le profil de cette distribution -- peut prendre plusieurs minutes^)
echo.
"!ASTRO_PY!" -m pip install -r "requirements.txt"
set "PIP_RC=!errorlevel!"

echo.
echo ============================================================
if !PIP_RC! neq 0 (
    echo   Installation pip terminee avec erreurs -- voir messages ci-dessus.
    echo   PHOEBE : souvent Microsoft C++ Build Tools requis.
) else (
    echo   Installation pip reussie dans "astroenv".
)
echo ============================================================
echo.
echo Lancement : double-cliquez sur LANCEMENT.bat
echo.
pause
exit /b !PIP_RC!
