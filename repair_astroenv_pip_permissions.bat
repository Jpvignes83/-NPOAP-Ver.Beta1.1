@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
REM ------------------------------------------------------------------
REM Accorde au groupe Utilisateurs le droit Modification sur envs\astroenv
REM (pip / site-packages). Utile si Miniconda est sous ProgramData et que
REM pip renvoie WinError 5 sans etre administrateur.
REM Executer une fois en administrateur ^(clic droit sur ce fichier^).
REM ------------------------------------------------------------------

title NPOAP - Droits pip environnement astroenv

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Executez ce script en tant qu'administrateur ^(clic droit ^> Executer en tant qu'administrateur^).
    pause
    exit /b 1
)

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
    echo ERREUR: conda introuvable. Installez Miniconda puis relancez ce script en administrateur.
    pause
    exit /b 1
)

set "ASTRO_ENV_ROOT=!CONDA_ROOT!\envs\astroenv"
if not exist "!ASTRO_ENV_ROOT!" (
    echo ERREUR: environnement astroenv introuvable :
    echo   !ASTRO_ENV_ROOT!
    echo Creez-le avec installation.bat ou : conda create -n astroenv python=3.11 -y
    pause
    exit /b 1
)

echo.
echo Attribution du droit Modification ^(Utilisateurs, heritage^) sur :
echo   !ASTRO_ENV_ROOT!
echo.
icacls "!ASTRO_ENV_ROOT!" /grant "*S-1-5-32-545:(OI)(CI)M" /T
if errorlevel 1 (
    echo.
    echo ECHEC icacls. Verifiez le chemin et les droits administrateur.
    pause
    exit /b 1
)
echo.
echo OK. Vous pouvez lancer NPOAP en session normale ; pip dans astroenv doit accepter les installations.
echo.
pause
exit /b 0
