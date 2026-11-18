@echo off
rem Teste de laboratorio V2 com Codex CLI. Somente leitura, dentro de lab\projeto_descartavel.
cd /d "%~dp0"
python tools\supervisor.py dry-run instructions\TASK-0002_codex_lab.json
echo.
echo Pressione uma tecla para EXECUTAR de verdade o teste (Ctrl+C cancela).
pause >nul
python tools\supervisor.py run instructions\TASK-0002_codex_lab.json --confirm TASK-0002
echo.
pause
