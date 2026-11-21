@echo off
setlocal EnableDelayedExpansion
REM ===================================================================
REM NPOAP AUTONOME -- conda astroenv + pip (coeur + optionnels)
REM Place a la racine de la distribution autonome.
REM ===================================================================
title NPOAP -- Installation autonome (coeur + optionnels)
cd /d "%~dp0"

echo.
echo ============================================================
echo   NPOAP AUTONOME -- Installation complete
echo ============================================================
echo   1^) conda astroenv + requirements.txt ^(profil autonome^)
echo   2^) rappels WSL very_Lite ^(KBMOD / astrometry / FSPS^)
echo   3^) sources Lite vendues : external_apps\lite\{core,optionnels,accessories}
echo.

if not exist "requirements.txt" (
  if exist "requirements_install_autonome.txt" (
    copy /Y "requirements_install_autonome.txt" "requirements.txt" >nul
  ) else (
    echo ERREUR: requirements.txt / requirements_install_autonome.txt introuvable.
    pause
    exit /b 1
  )
)

call "%~dp0INSTALLER_NPOAP_ASTROENV_WINDOWS.bat"
set "RC=!errorlevel!"
if not "!RC!"=="0" (
  echo.
  echo Echec installation pip/conda ^(code !RC!^).
  pause
  exit /b !RC!
)

echo.
echo ------------------------------------------------------------
echo Suite systeme optionnelle ^(WSL very_Lite, hors pip^)
echo ------------------------------------------------------------
echo   install_wsl.bat
echo   install_ubuntu_wsl_very_lite.bat
echo   install_kbmod_wsl.bat          ^(apres Miniconda dans WSL^)
echo   install_optionnels.bat         ^(MSVC / CMake / WSL si besoin^)
echo Doc: docs\DISTRIBUTION_AUTONOME.md  et  docs\WSL_VERY_LITE.md
echo.
echo Lancement: LANCER_NPOAP_ASTROENV.bat
echo.
pause
exit /b 0
