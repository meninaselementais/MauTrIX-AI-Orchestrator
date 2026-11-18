@echo off
rem V4 - roda SOMENTE testes simulados (V3: 55 + V4 escrita controlada). Nenhum agente real e iniciado; nenhuma cota e usada.
rem Os testes criam copias temporarias do orquestrador e um repositorio Git descartavel fora de lab\git_lab. Exige git no PATH.
if /i not "%~1"=="inner" (
  cmd /k ""%~f0" inner"
  exit /b
)
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist diagnostics mkdir diagnostics
set LOG=diagnostics\v4_simulados.txt
echo [%DATE% %TIME%] inicio > %LOG%
python --version >> %LOG% 2>&1
git --version >> %LOG% 2>&1
if errorlevel 1 (
  echo ERRO: git nao encontrado no PATH. Instale o Git for Windows e tente de novo.
  echo ERRO: git nao encontrado >> %LOG%
  goto :fim
)
echo Rodando testes V3 (55)...
python tests\test_v3_simulated.py --json diagnostics\v4_v3_simulados.json >> %LOG% 2>&1
set RC3=%ERRORLEVEL%
echo [%DATE% %TIME%] V3 codigo de saida %RC3% >> %LOG%
echo Rodando testes V4 (escrita controlada)...
python tests\test_v4_write.py --json diagnostics\v4_simulados.json >> %LOG% 2>&1
set RC4=%ERRORLEVEL%
echo [%DATE% %TIME%] V4 codigo de saida %RC4% >> %LOG%
powershell -NoProfile -Command "$pat = 'fake_agent' + '.py'; $p = Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine.Contains($pat) -and $_.CommandLine -notmatch 'Get-CimInstance' }; if ($p) { 'ATENCAO: processos fake_agent restantes:'; $p | ForEach-Object { '  PID ' + $_.ProcessId + ' pai ' + $_.ParentProcessId + ' : ' + $_.CommandLine } } else { 'Processos fake_agent restantes: nenhum' }" >> %LOG% 2>&1
echo Codigos de saida: V3=%RC3% V4=%RC4%  (0 = todos passaram)
findstr /C:"passaram" /C:"FAIL" /C:"INCOMPLETA" /C:"Traceback" /C:"fake_agent" %LOG%
:fim
echo Log completo: %LOG%
echo Esperado: V3 55/55, V4 56/56, codigos 0 e nenhum fake_agent restante. Pode fechar esta janela.
