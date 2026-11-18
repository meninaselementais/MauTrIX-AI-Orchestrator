@echo off
rem V3: transferencia entre agentes, SOMENTE no laboratorio (lab\). Nao usar em projetos reais.
cd /d "%~dp0"
python tools\supervisor.py status
echo.
echo Pressione uma tecla para EXECUTAR o failover de laboratorio (Ctrl+C cancela).
pause >nul
python tools\supervisor.py failover instructions\TASK-0003_failover_lab.json --confirm TASK-0003
echo.
pause
