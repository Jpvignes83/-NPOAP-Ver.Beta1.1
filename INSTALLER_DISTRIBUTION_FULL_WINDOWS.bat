@echo off
REM ===================================================================
REM Retro-compatibilite -- profil "full"
REM L'installation unifiee se fait via INSTALLER_NPOAP_ASTROENV_WINDOWS.bat
REM ===================================================================
call "%~dp0INSTALLER_NPOAP_ASTROENV_WINDOWS.bat"
exit /b %errorlevel%
