@echo off
REM Ouvre une invite CMD dans astroenv (même logique que activate_astroenv.bat en double-clic).
REM Ancienne variante avec journal : utilisez directement activate_astroenv.bat ou ouvrez logs\ manuellement.

cd /d "%~dp0"
call "%~dp0activate_astroenv.bat"
exit /b %ERRORLEVEL%
