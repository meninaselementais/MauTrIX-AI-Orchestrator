@echo off
rem Diagnostico SOMENTE LEITURA dos agentes. Nao le tokens, nao executa prompts, nao altera projetos.
cd /d "%~dp0"
python tools\diagnose.py
echo.
pause
