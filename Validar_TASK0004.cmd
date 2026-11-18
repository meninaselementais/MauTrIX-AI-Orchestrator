@echo off
rem V3.3 - validacao do Codex com contexto embutido (TASK-0004). Somente leitura, somente em lab\projeto_descartavel.
rem Etapa 1 (sempre): dry-run, NAO inicia nenhum agente. Etapa 2 (so com "SIM"): UMA execucao real do Codex.
if /i not "%~1"=="inner" (
  cmd /k ""%~f0" inner"
  exit /b
)
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist diagnostics mkdir diagnostics
set LOG=diagnostics\task0004_log.txt
echo [%DATE% %TIME%] inicio > %LOG%
echo ETAPA 1: dry-run (nenhum agente sera iniciado)
python tools\validar_task0004.py dry-run >> %LOG% 2>&1
set DRY=%ERRORLEVEL%
echo [%DATE% %TIME%] dry-run terminou, codigo %DRY% >> %LOG%
echo Dry-run terminou com codigo %DRY%. Detalhes: diagnostics\task0004_dryrun.md
if not "%DRY%"=="0" (
  echo Dry-run reprovado. A execucao real NAO sera oferecida.
  goto :fim
)
echo.
echo ETAPA 2: UMA execucao REAL do Codex (consome uma pequena parte da cota).
set /p CONF=Digite SIM para executar, qualquer outra coisa cancela: 
if /i not "%CONF%"=="SIM" (
  echo [%DATE% %TIME%] cancelado pelo usuario >> %LOG%
  echo Cancelado. Nada foi executado.
  goto :fim
)
echo [%DATE% %TIME%] execucao real iniciada >> %LOG%
python tools\validar_task0004.py run --confirm TASK-0004 >> %LOG% 2>&1
echo [%DATE% %TIME%] execucao real terminou, codigo %ERRORLEVEL% >> %LOG%
echo Terminou com codigo %ERRORLEVEL%. Evidencias: diagnostics\task0004_evidence.md e .json
:fim
echo Log completo: %LOG%
echo Pode fechar esta janela.
