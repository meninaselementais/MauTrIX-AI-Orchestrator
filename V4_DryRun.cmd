@echo off
rem V4 - DRY-RUN das tarefas de escrita TASK-1001 (Claude) e TASK-1002 (Codex, proposta). NAO inicia nenhum agente,
rem nao cria workspace e nao altera o repositorio. Mostra o estado Git e o comando que seria usado.
if /i not "%~1"=="inner" (
  cmd /k ""%~f0" inner"
  exit /b
)
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist diagnostics mkdir diagnostics
python tools\supervisor.py write-dry-run instructions\TASK-1001_write_claude_lab.json > diagnostics\v4_dryrun_1001.json 2>&1
echo TASK-1001 dry-run codigo %ERRORLEVEL%
python tools\supervisor.py write-dry-run instructions\TASK-1002_write_codex_proposal_lab.json > diagnostics\v4_dryrun_1002.json 2>&1
echo TASK-1002 dry-run codigo %ERRORLEVEL%
echo Resultados: diagnostics\v4_dryrun_1001.json e v4_dryrun_1002.json. Pode fechar esta janela.
