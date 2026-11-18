@echo off
rem Somente verifica disponibilidade e autenticacao. Nao executa tarefas.
cd /d "%~dp0"
python tools\supervisor.py check
echo.
pause
