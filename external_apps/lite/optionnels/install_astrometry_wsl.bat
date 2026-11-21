@echo off
REM NPOAP - Installe astrometry.net dans la distro WSL (preferer Ubuntu-NPOAP-Lite).
REM Sans catalogues d'index (astrometry-data-*) : voir docs\WSL_VERY_LITE.md.
REM Une fenetre WSL peut demander le mot de passe sudo (sauf very_Lite NOPASSWD).
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set "WSL_DISTRO="
for /f "delims=" %%D in ('powershell -NoProfile -Command "@(wsl -l -q 2>$null) | ForEach-Object { $_.Trim() } | Where-Object { $_ -ieq 'Ubuntu-NPOAP-Lite' } | Select-Object -First 1"') do set "WSL_DISTRO=%%D"
if defined WSL_DISTRO (
  set "WSL_ARGS=-d Ubuntu-NPOAP-Lite"
  echo Distro cible : Ubuntu-NPOAP-Lite
) else (
  set "WSL_ARGS="
  echo Distro cible : WSL par defaut
)
echo.
echo Mise a jour des paquets et installation astrometry.net via WSL...
echo ^(--no-install-recommends ; pas d'indexs multi-Go^)
wsl !WSL_ARGS! bash -c "sudo DEBIAN_FRONTEND=noninteractive apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends astrometry.net"
echo.
if %errorLevel% neq 0 (
    echo Echec : ouvrez une session WSL ^(wsl^), verifiez sudo, puis :
    echo   sudo apt-get update ^&^& sudo apt-get install -y --no-install-recommends astrometry.net
) else (
    echo OK : astrometry.net installe dans WSL.
    echo Indexs optionnels ^(gros^) : sudo apt-get install astrometry-data-tycho2
)
pause
