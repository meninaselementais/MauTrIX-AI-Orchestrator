@echo off
rem Diagnostico complementar V1.1 - SOMENTE LEITURA. Nao executa tarefas, nao le credenciais.
cd /d "%~dp0"
python tools\diagnose.py
python tools\diagnose_v1_1.py
echo.
pause
