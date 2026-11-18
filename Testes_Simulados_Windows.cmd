@echo off
rem V3.3 - roda SOMENTE os testes simulados (55). Nenhum agente real (Claude/Codex) e iniciado e nenhuma cota e usada.
rem Os testes usam uma copia temporaria do orquestrador e agentes falsos; MAUTRIX_TEST_MODE=1 impede alcancar agentes reais.
if /i not "%~1"=="inner" (
  cmd /k ""%~f0" inner"
  exit /b
)
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist diagnostics mkdir diagnostics
set LOG=diagnostics\v3_3_simulados.txt
echo [%DATE% %TIME%] inicio > %LOG%
python --version >> %LOG% 2>&1
python tests\test_v3_simulated.py --json diagnostics\v3_3_simulados.json >> %LOG% 2>&1
set RC=%ERRORLEVEL%
echo [%DATE% %TIME%] codigo de saida %RC% >> %LOG%
powershell -NoProfile -Command "$pat = 'fake_agent' + '.py'; $p = Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine.Contains($pat) -and $_.CommandLine -notmatch 'Get-CimInstance' }; if ($p) { 'ATENCAO: processos fake_agent restantes:'; $p | ForEach-Object { '  PID ' + $_.ProcessId + ' pai ' + $_.ParentProcessId + ' : ' + $_.CommandLine } } else { 'Processos fake_agent restantes: nenhum' }" >> %LOG% 2>&1
echo Codigo de saida: %RC%  (0 = todos passaram)
findstr /C:"verificacoes passaram" /C:"verificações passaram" /C:"FAIL" %LOG%
echo Log completo: %LOG%   JSON: diagnostics\v3_3_simulados.json
echo Esperado: 55/55 verificacoes passaram e nenhum fake_agent restante. Pode fechar esta janela.
