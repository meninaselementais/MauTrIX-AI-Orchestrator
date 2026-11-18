@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist diagnostics mkdir diagnostics
echo === Python ===
python --version
echo.
echo === PASSO 1: testes SIMULADOS (nenhum agente real e usado) ===
python tests\test_v3_simulated.py --json diagnostics\v3_1_simulados.json > diagnostics\v3_1_simulados.txt 2>&1
echo codigo de saida: %ERRORLEVEL%
type diagnostics\v3_1_simulados.txt
echo.
echo === Processos fake_agent remanescentes (esperado: nenhum) ===
wmic process where "CommandLine like '%%fake_agent.py%%'" get ProcessId,CommandLine 2>nul | findstr /i fake_agent || echo nenhum
echo.
echo === PASSO 2: status antes do teste real ===
python tools\supervisor.py status
echo.
echo O PASSO 3 executa UM failover REAL de LEITURA no laboratorio (pode consumir uma pequena parte da cota de Codex/Claude).
echo Pressione uma tecla para continuar ou feche a janela para cancelar.
pause >nul
python tools\real_failover_test.py > diagnostics\v3_1_real_saida.txt 2>&1
echo codigo de saida: %ERRORLEVEL%
type diagnostics\v3_1_real_saida.txt
echo.
pause
