@echo off
setlocal EnableDelayedExpansion
REM ============================================================
REM Construit la distribution NPOAP AUTONOME (coeur + optionnels)
REM Sortie: build\distributions\autonome\  + ZIP
REM ============================================================
title Construction Distribution NPOAP AUTONOME
cd /d "%~dp0"

if not exist "main.py" (
  echo ERREUR: main.py introuvable. Placez ce script a la racine NPOAP.
  pause
  exit /b 1
)

if not exist "build\build_autonome.py" (
  echo ERREUR: build\build_autonome.py introuvable.
  pause
  exit /b 1
)

if not exist "requirements_install_autonome.txt" (
  echo ERREUR: requirements_install_autonome.txt introuvable.
  pause
  exit /b 1
)

set "PYTHON_CMD="
where py >nul 2>&1 && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD if exist "%ProgramData%\Miniconda3\python.exe" set "PYTHON_CMD=%ProgramData%\Miniconda3\python.exe"
if not defined PYTHON_CMD if exist "%USERPROFILE%\miniconda3\python.exe" set "PYTHON_CMD=%USERPROFILE%\miniconda3\python.exe"
if not defined PYTHON_CMD if exist "%USERPROFILE%\miniconda3\envs\astroenv\python.exe" set "PYTHON_CMD=%USERPROFILE%\miniconda3\envs\astroenv\python.exe"
if not defined PYTHON_CMD if exist "%LOCALAPPDATA%\miniconda3\python.exe" set "PYTHON_CMD=%LOCALAPPDATA%\miniconda3\python.exe"
if not defined PYTHON_CMD where python >nul 2>&1 && set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
  echo ERREUR: Python introuvable ^(py / Miniconda / PATH^).
  pause
  exit /b 1
)
echo Python: !PYTHON_CMD!

echo.
echo ============================================================
echo   Construction distribution AUTONOME Lite
echo   external_apps\lite\{core, optionnels, accessories}
echo ============================================================
echo.

echo [1/2] Assemblage external_apps\lite ...
%PYTHON_CMD% "build\assemble_external_apps_lite.py" --clean
if errorlevel 1 (
  echo Echec assemblage Lite.
  pause
  exit /b 1
)

echo [2/2] Build distribution ...
%PYTHON_CMD% "build\build_autonome.py" --skip-assemble-lite %*

set "RC=!errorlevel!"
echo.
if not "!RC!"=="0" (
  echo Echec build ^(code !RC!^).
  pause
  exit /b !RC!
)

echo Dossier: build\distributions\autonome\
echo ZIP    : build\distributions\NPOAP_AUTONOME_*.zip
echo Doc    : docs\DISTRIBUTION_AUTONOME.md
echo.
pause
exit /b 0
