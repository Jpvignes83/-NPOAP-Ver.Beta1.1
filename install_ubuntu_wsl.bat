@echo off
REM NPOAP - Enregistre la distribution Ubuntu Store dans WSL (apres install_wsl.bat).
REM Preferez la variante legere : install_ubuntu_wsl_very_lite.bat (voir docs\WSL_VERY_LITE.md).
setlocal
cd /d "%~dp0"
echo.
echo Installation de la distribution Ubuntu ^(Microsoft Store^) dans WSL...
echo.
echo Astuce : pour une distro minimale NPOAP, utilisez plutot :
echo   install_ubuntu_wsl_very_lite.bat
echo ^(docs\WSL_VERY_LITE.md^)
echo.
wsl --install -d Ubuntu
echo.
if %errorLevel% neq 0 (
    echo Si le message indique que la distribution existe deja, c'est normal.
    echo Lancez Ubuntu depuis le menu demarrer ou : wsl -d Ubuntu
)
pause
