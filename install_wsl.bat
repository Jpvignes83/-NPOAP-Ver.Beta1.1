@echo off
REM NPOAP - Installe / met a jour WSL (cible recommandee : Microsoft WSL 3.0.3+).
REM Executez en administrateur si la commande echoue.
REM Release : https://github.com/microsoft/WSL/releases/tag/3.0.3
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "WSL_RELEASE_TAG=3.0.3"
set "WSL_MSI_URL=https://github.com/microsoft/WSL/releases/download/%WSL_RELEASE_TAG%/wsl.%WSL_RELEASE_TAG%.0.x64.msi"
set "WSL_MSI=%LOCALAPPDATA%\NPOAP\WSL\wsl.%WSL_RELEASE_TAG%.0.x64.msi"

echo.
echo ============================================================
echo NPOAP - Installation / mise a jour WSL
echo ============================================================
echo Cible documentee : WSL %WSL_RELEASE_TAG%
echo   https://github.com/microsoft/WSL/releases/tag/%WSL_RELEASE_TAG%
echo Un redemarrage peut etre demande par Windows.
echo.

where wsl >nul 2>&1
if errorlevel 1 (
  echo [INFO] WSL introuvable - installation initiale...
  wsl --install
  echo Code de sortie : %errorLevel%
  goto :after_install
)

echo [INFO] Version WSL actuelle :
wsl --version 2>nul
if errorlevel 1 wsl.exe --status 2>nul

echo.
echo [1/2] Mise a jour via Microsoft ^(wsl --update^)...
wsl --update
set "UPD_RC=!errorLevel!"
echo Code wsl --update : !UPD_RC!

REM Si --update echoue ou version ancienne : MSI GitHub 3.0.3
if /i "%~1"=="msi" goto :install_msi
if /i "%~1"=="github" goto :install_msi
goto :after_install

:install_msi
echo.
echo [2/2] Installation MSI GitHub WSL %WSL_RELEASE_TAG% ...
if not exist "%LOCALAPPDATA%\NPOAP\WSL" mkdir "%LOCALAPPDATA%\NPOAP\WSL"
if exist "%WSL_MSI%" (
  echo [OK] MSI deja present : %WSL_MSI%
) else (
  echo Telechargement : %WSL_MSI_URL%
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%WSL_MSI_URL%' -OutFile '%WSL_MSI%'"
  if errorlevel 1 (
    echo ERREUR: telechargement MSI echoue.
    goto :after_install
  )
)
echo Lancement msiexec ^(droits admin possibles^)...
msiexec /i "%WSL_MSI%" /passive
echo Code msiexec : %errorLevel%

:after_install
echo.
echo Version apres operation :
wsl --version 2>nul
echo.
echo Suite NPOAP recommandee :
echo   install_ubuntu_wsl_very_lite.bat
echo ^(docs\WSL_VERY_LITE.md^)
echo.
echo Forcer le MSI GitHub %WSL_RELEASE_TAG% :
echo   install_wsl.bat msi
echo.
if /i "%NPOAP_AUTO%"=="1" exit /b 0
pause
exit /b 0
