@echo off
setlocal EnableDelayedExpansion
REM ============================================================
REM Construit la distribution NPOAP AUTONOME Lite
REM Usage:
REM   construire_distribution_autonome.bat
REM   construire_distribution_autonome.bat full
REM   construire_distribution_autonome.bat exoplanetes
REM   construire_distribution_autonome.bat asteroides
REM   construire_distribution_autonome.bat binaires
REM   construire_distribution_autonome.bat list
REM Sortie: build\distributions\autonome[_profil]\  + ZIP
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

set "PYTHON_CMD="
where py >nul 2>&1 && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD if exist "%ProgramData%\Miniconda3\python.exe" set "PYTHON_CMD=%ProgramData%\Miniconda3\python.exe"
if not defined PYTHON_CMD if exist "%USERPROFILE%\miniconda3\python.exe" set "PYTHON_CMD=%USERPROFILE%\miniconda3\python.exe"
if not defined PYTHON_CMD if exist "%USERPROFILE%\miniconda3\envs\astroenv\python.exe" set "PYTHON_CMD=%USERPROFILE%\miniconda3\envs\astroenv\python.exe"
if not defined PYTHON_CMD if exist "%LOCALAPPDATA%\miniconda3\python.exe" set "PYTHON_CMD=%LOCALAPPDATA%\miniconda3\python.exe"
if not defined PYTHON_CMD if exist "C:\ProgramData\miniconda3\python.exe" set "PYTHON_CMD=C:\ProgramData\miniconda3\python.exe"
if not defined PYTHON_CMD where python >nul 2>&1 && set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
  echo ERREUR: Python introuvable ^(py / Miniconda / PATH^).
  pause
  exit /b 1
)
echo Python: !PYTHON_CMD!

set "PROFILE=full"
set "EXTRA_ARGS="

:parse_args
if "%~1"=="" goto :parse_done
if /i "%~1"=="list" (
  %PYTHON_CMD% "build\build_autonome.py" --list-profiles
  pause
  exit /b 0
)
if /i "%~1"=="--list-profiles" (
  %PYTHON_CMD% "build\build_autonome.py" --list-profiles
  pause
  exit /b 0
)
if /i "%~1"=="--no-zip" (
  set "EXTRA_ARGS=!EXTRA_ARGS! --no-zip"
  shift
  goto :parse_args
)
if /i "%~1"=="--skip-assemble-lite" (
  set "EXTRA_ARGS=!EXTRA_ARGS! --skip-assemble-lite"
  shift
  goto :parse_args
)
REM Premier argument non-option = nom de profil
set "PROFILE=%~1"
shift
goto :parse_args
:parse_done

if not exist "requirements_install_autonome.txt" if /i "!PROFILE!"=="full" (
  echo ERREUR: requirements_install_autonome.txt introuvable.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   Construction distribution AUTONOME Lite
echo   Profil : !PROFILE!
echo ============================================================
echo.

echo [1/2] Assemblage external_apps\lite ...
%PYTHON_CMD% "build\assemble_external_apps_lite.py" --clean
if errorlevel 1 (
  echo Echec assemblage Lite.
  pause
  exit /b 1
)

echo [2/2] Build distribution ^(profil=!PROFILE!^) ...
%PYTHON_CMD% "build\build_autonome.py" --profile "!PROFILE!" --skip-assemble-lite !EXTRA_ARGS!

set "RC=!errorlevel!"
echo.
if not "!RC!"=="0" (
  echo Echec build ^(code !RC!^).
  pause
  exit /b !RC!
)

if /i "!PROFILE!"=="full" (
  echo Dossier: build\distributions\autonome\
  echo ZIP    : build\distributions\NPOAP_AUTONOME_*.zip
) else (
  echo Dossier: build\distributions\autonome_!PROFILE!\
  echo ZIP    : build\distributions\NPOAP_AUTONOME_!PROFILE!_*.zip
)
echo Doc    : docs\DISTRIBUTION_AUTONOME.md
echo Profils : full ^| exoplanetes ^| asteroides ^| binaires
echo           ^(construire_distribution_autonome.bat list^)
echo.
pause
exit /b 0
