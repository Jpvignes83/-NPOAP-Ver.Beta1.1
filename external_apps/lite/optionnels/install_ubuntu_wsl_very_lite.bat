@echo off
REM NPOAP - Distribution WSL very_Lite (Ubuntu Base + paquets strictement utiles).
REM Alternative legere a install_ubuntu_wsl.bat (Ubuntu Store complet).
REM Docs : docs\WSL_VERY_LITE.md
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

set "DISTRO_NAME=Ubuntu-NPOAP-Lite"
set "UBUNTU_VER=24.04.5"
set "TARBALL=ubuntu-base-%UBUNTU_VER%-base-amd64.tar.gz"
set "BASE_URL=https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release"
set "DOWNLOAD_DIR=%LOCALAPPDATA%\NPOAP\WSL\downloads"
set "INSTALL_DIR=%LOCALAPPDATA%\NPOAP\WSL\%DISTRO_NAME%"
set "TARBALL_PATH=%DOWNLOAD_DIR%\%TARBALL%"
set "PROFILE=full"
if /i "%~1"=="core" set "PROFILE=core"
if /i "%~1"=="astrometry" set "PROFILE=astrometry"
if /i "%~1"=="full" set "PROFILE=full"

echo.
echo ============================================================
echo NPOAP - WSL Ubuntu very_Lite
echo ============================================================
echo Distro   : %DISTRO_NAME%
echo Rootfs   : Ubuntu Base %UBUNTU_VER% (~29 Mo)
echo Profil   : %PROFILE%  ^(core ^| astrometry ^| full^)
echo Install  : %INSTALL_DIR%
echo.
echo IMPORTANT : ne PAS extraire le .tar.gz ^(Explorateur/7-Zip echouent^).
echo            wsl --import consomme l'archive telle quelle.
echo.
echo Contenu systeme : toolchain build + gfortran + git + python3
if /i "!PROFILE!"=="core" (
  echo Astrometry.net : NON ^(profil core^)
) else (
  echo Astrometry.net : OUI ^(sans catalogues d'index multi-Go^)
)
echo.
echo NON inclus : desktop, snapd, recommends APT, CUDA, Miniconda, indexs.
echo.

where wsl >nul 2>&1
if errorlevel 1 (
  echo ERREUR : WSL introuvable. Lancez d'abord install_wsl.bat puis redemarrez si demande.
  goto :fail
)

REM Detecte si la distro existe deja (wsl -l est UTF-16 : passer par PowerShell)
set "DISTRO_EXISTS=0"
for /f "delims=" %%E in ('powershell -NoProfile -Command "$n='%DISTRO_NAME%'; @(wsl -l -q 2>$null) | ForEach-Object { $_.Trim() } | Where-Object { $_ -ieq $n } | Measure-Object | Select-Object -ExpandProperty Count"') do set "DISTRO_EXISTS=%%E"
if not "!DISTRO_EXISTS!"=="0" (
  echo [INFO] Distro %DISTRO_NAME% deja presente.
  if /i "%NPOAP_AUTO%"=="1" (
    echo [AUTO] Reutilise la distro existante ^(bootstrap uniquement^).
    goto :bootstrap_only
  )
  choice /C YN /M "Reinstaller from scratch (unregister + reimport)"
  if errorlevel 2 goto :bootstrap_only
  if errorlevel 1 (
    echo [INFO] wsl --unregister %DISTRO_NAME% ...
    wsl --unregister %DISTRO_NAME%
  )
)

if not exist "%DOWNLOAD_DIR%" mkdir "%DOWNLOAD_DIR%"
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

REM Reutilise un tarball deja telecharge (Downloads ou cache NPOAP), sans extraction.
if not exist "%TARBALL_PATH%" if exist "%USERPROFILE%\Downloads\ubuntu-base-24.04.5-base-amd64.tar.gz" (
  echo [INFO] Copie depuis Downloads : ubuntu-base-24.04.5-base-amd64.tar.gz
  copy /Y "%USERPROFILE%\Downloads\ubuntu-base-24.04.5-base-amd64.tar.gz" "%TARBALL_PATH%" >nul
)
if not exist "%TARBALL_PATH%" if exist "%USERPROFILE%\Downloads\ubuntu-base-24.04.3-base-amd64.tar.gz" (
  echo [INFO] Copie depuis Downloads : ubuntu-base-24.04.3-base-amd64.tar.gz
  set "TARBALL=ubuntu-base-24.04.3-base-amd64.tar.gz"
  set "TARBALL_PATH=%DOWNLOAD_DIR%\!TARBALL!"
  copy /Y "%USERPROFILE%\Downloads\ubuntu-base-24.04.3-base-amd64.tar.gz" "!TARBALL_PATH!" >nul
)

if exist "%TARBALL_PATH%" (
  echo [OK] Tarball deja present : %TARBALL_PATH%
) else (
  echo [INFO] Telechargement %TARBALL% ...
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ProgressPreference='SilentlyContinue'; Try { Invoke-WebRequest -Uri '%BASE_URL%/%TARBALL%' -OutFile '%TARBALL_PATH%'; exit 0 } Catch { Write-Error $_; exit 1 }"
  if errorlevel 1 (
    echo ERREUR : telechargement echoue.
    echo URL : %BASE_URL%/%TARBALL%
    goto :fail
  )
)

echo [INFO] Verification taille tarball...
for %%A in ("%TARBALL_PATH%") do set "TB_SIZE=%%~zA"
if "!TB_SIZE!"=="" set "TB_SIZE=0"
if !TB_SIZE! LSS 10000000 (
  echo ERREUR : tarball trop petit ^(!TB_SIZE! octets^) - telechargement incomplete.
  del /f /q "%TARBALL_PATH%" 2>nul
  goto :fail
)
echo [OK] Tarball : !TB_SIZE! octets

echo [INFO] Import WSL 2 : wsl --import %DISTRO_NAME% ...
wsl --import "%DISTRO_NAME%" "%INSTALL_DIR%" "%TARBALL_PATH%" --version 2
if errorlevel 1 (
  echo ERREUR : wsl --import a echoue.
  goto :fail
)

echo [INFO] Definition comme distro par defaut...
wsl --set-default "%DISTRO_NAME%" >nul 2>&1

:bootstrap_only
REM Racine NPOAP ou external_apps\lite\optionnels\
set "BOOT_SH=%~dp0scripts\bootstrap_npoap_wsl_very_lite.sh"
if not exist "!BOOT_SH!" set "BOOT_SH=%~dp0..\..\..\..\scripts\bootstrap_npoap_wsl_very_lite.sh"
if not exist "!BOOT_SH!" (
  echo ERREUR : script introuvable : bootstrap_npoap_wsl_very_lite.sh
  echo Cherche : %%~dp0scripts\  ou scripts\ a la racine NPOAP
  goto :fail
)

for /f "delims=" %%i in ('wsl -d %DISTRO_NAME% wslpath -a "%BOOT_SH%" 2^>nul') do set "BOOT_WSL=%%i"
if not defined BOOT_WSL (
  echo ERREUR : wslpath a echoue pour le script bootstrap.
  goto :fail
)

REM Nom utilisateur Linux : alphanumerique issu du login Windows
set "NPOAP_USER=npoap"
for /f "delims=" %%U in ('powershell -NoProfile -Command "$u=$env:USERNAME -replace '[^A-Za-z0-9._-]','' ; if ([string]::IsNullOrWhiteSpace($u)) { 'npoap' } else { $u.ToLower() }"') do set "NPOAP_USER=%%U"
echo [INFO] Bootstrap APT ^(profil=!PROFILE!, user=!NPOAP_USER!^)...
echo        Mot de passe : ubuntu-base n'en a pas ; execution en root.
REM Normalise CRLF -> LF (fichiers edites sous Windows) puis lance le bootstrap.
wsl -d %DISTRO_NAME% -u root bash -c "sed -i 's/\r$//' '!BOOT_WSL!' && NPOAP_WSL_PROFILE='!PROFILE!' NPOAP_WSL_USER='!NPOAP_USER!' bash '!BOOT_WSL!'"
if errorlevel 1 (
  echo ERREUR : bootstrap APT a echoue.
  goto :fail
)

echo.
echo ============================================================
echo WSL very_Lite pret : %DISTRO_NAME%
echo ============================================================
echo Ouvrir :  wsl -d %DISTRO_NAME%
echo Suite  :
echo   install_astrometry_wsl.bat   ^(si profil core seulement^)
echo   install_kbmod_wsl.bat        ^(apres Miniconda + astroenv py3.11 dans WSL^)
echo   Installation_fsps\prospector.bat  ^(Prospector/FSPS^)
echo Doc    : docs\WSL_VERY_LITE.md
echo.
if /i "%NPOAP_AUTO%"=="1" exit /b 0
pause
exit /b 0

:fail
echo.
echo Echec installation WSL very_Lite.
if /i "%NPOAP_AUTO%"=="1" exit /b 1
pause
exit /b 1
