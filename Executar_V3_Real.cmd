@echo off
rem V3.1 passos 2 e 3. A janela permanece aberta (cmd /k) mesmo se algo falhar. Log em diagnostics\v3_1_real_log.txt
if /i not "%~1"=="inner" (
  cmd /k ""%~f0" inner"
  exit /b
)
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist diagnostics mkdir diagnostics
set LOG=diagnostics\v3_1_real_log.txt
echo [%DATE% %TIME%] inicio > %LOG%
echo === PASSO 2: status antes do teste real ===
python tools\supervisor.py status >> %LOG% 2>&1
echo [%DATE% %TIME%] status codigo %ERRORLEVEL% >> %LOG%
type %LOG%
echo.
echo O PASSO 3 executa UM failover REAL de LEITURA no laboratorio (usa uma pequena parte da cota do agente).
echo Pressione uma tecla para continuar, ou feche a janela para cancelar.
pause >nul
echo [%DATE% %TIME%] passo 3 iniciado >> %LOG%
python tools\real_failover_test.py >> %LOG% 2>&1
echo [%DATE% %TIME%] passo 3 terminou, codigo %ERRORLEVEL% >> %LOG%
echo.
type diagnostics\v3_1_real_evidence.md 2>nul
echo.
echo Fim. Log completo: %LOG%. Pode fechar esta janela.
