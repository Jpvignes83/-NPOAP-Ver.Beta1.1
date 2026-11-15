@echo off
setlocal EnableDelayedExpansion
REM NPOAP — Reinstalle ou met a jour uniquement SORA (sora-astro) dans « astroenv ».
REM Pip cible uniquement l'interprete conda de l'env ^(pas AppData\Roaming\Python311^).

chcp 65001 >nul
echo ========================================
echo Installation SORA (sora-astro) dans astroenv
echo ========================================
echo.

cd /d "%~dp0"

set "CONDA_ROOT="
where conda >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    for /f "delims=" %%i in ('conda info --base 2^>nul') do set "CONDA_ROOT=%%i"
)
if not defined CONDA_ROOT if exist "%ProgramData%\Miniconda3\Scripts\conda.exe" (
    for /f "delims=" %%i in ('"%ProgramData%\Miniconda3\Scripts\conda.exe" info --base 2^>nul') do set "CONDA_ROOT=%%i"
)
if not defined CONDA_ROOT if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" (
    for /f "delims=" %%i in ('"%USERPROFILE%\miniconda3\Scripts\conda.exe" info --base 2^>nul') do set "CONDA_ROOT=%%i"
)
if not defined CONDA_ROOT if exist "%LOCALAPPDATA%\miniconda3\Scripts\conda.exe" (
    for /f "delims=" %%i in ('"%LOCALAPPDATA%\miniconda3\Scripts\conda.exe" info --base 2^>nul') do set "CONDA_ROOT=%%i"
)
if not defined CONDA_ROOT if exist "%ProgramData%\Anaconda3\Scripts\conda.exe" (
    for /f "delims=" %%i in ('"%ProgramData%\Anaconda3\Scripts\conda.exe" info --base 2^>nul') do set "CONDA_ROOT=%%i"
)
if not defined CONDA_ROOT if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" (
    for /f "delims=" %%i in ('"%USERPROFILE%\anaconda3\Scripts\conda.exe" info --base 2^>nul') do set "CONDA_ROOT=%%i"
)

if not defined CONDA_ROOT (
    echo ERREUR: conda introuvable.
    pause
    exit /b 1
)

if not exist "%CONDA_ROOT%\Scripts\activate.bat" (
    echo ERREUR: activate.bat introuvable dans "%CONDA_ROOT%\Scripts"
    pause
    exit /b 1
)

echo Activation de l'environnement astroenv...
call "%CONDA_ROOT%\Scripts\activate.bat" astroenv
if errorlevel 1 (
    echo ERREUR: Impossible d'activer l'environnement astroenv.
    echo Creez-le par exemple avec : conda create -n astroenv python=3.11 -y
    pause
    exit /b 1
)

set "PYTHONNOUSERSITE=1"
set "PIP_USER="
set "PY_ASTRO=%CONDA_ROOT%\envs\astroenv\python.exe"
if not exist "!PY_ASTRO!" (
    echo ERREUR: python.exe astroenv introuvable : !PY_ASTRO!
    pause
    exit /b 1
)

echo.
echo Installation via pip ^(interprete : !PY_ASTRO!^)...
"!PY_ASTRO!" -m pip install --upgrade pip
"!PY_ASTRO!" -m pip install --upgrade "setuptools<81"
"!PY_ASTRO!" -m pip install "sora-astro"

if errorlevel 1 (
    echo.
    echo ERREUR lors de l'installation de sora-astro.
    echo En cas d'echec sur Cartopy / GEOS, consultez la doc SORA et les prerequis systeme.
    pause
    exit /b 1
)

echo.
echo ========================================
echo Installation terminee avec succes.
echo ========================================
echo.
echo sora-astro est a jour dans astroenv. Relancez NPOAP depuis cet environnement.
echo.
pause
exit /b 0
