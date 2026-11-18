@echo off
rem Teste de laboratorio V2 com Claude Code. Somente leitura, dentro de lab\projeto_descartavel.
cd /d "%~dp0"
python tools\supervisor.py dry-run instructions\TASK-0001_claude_lab.json
echo.
echo Pressione uma tecla para EXECUTAR de verdade o teste (Ctrl+C cancela).
pause >nul
python tools\supervisor.py run instructions\TASK-0001_claude_lab.json --confirm TASK-0001
echo.
pause
