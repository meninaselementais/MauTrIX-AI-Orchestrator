@echo off
rem V4 - cria o repositorio Git DESCARTAVEL em lab\git_lab e faz o commit-base (so dos arquivos de exemplo).
rem E a unica operacao de commit da V4 e so existe no laboratorio descartavel. Nao toca em nenhum outro repositorio.
if /i not "%~1"=="inner" (
  cmd /k ""%~f0" inner"
  exit /b
)
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist diagnostics mkdir diagnostics
set LOG=diagnostics\v4_lab_git_log.txt
echo [%DATE% %TIME%] inicio > %LOG%
if exist lab\git_lab\.git (
  echo lab\git_lab ja e um repositorio Git. Mostrando o estado atual, sem alterar nada.
  python tools\lab_git.py state >> %LOG% 2>&1
  goto :fim
)
echo Isto cria um repositorio Git SOMENTE em lab\git_lab e faz UM commit-base com os arquivos de exemplo.
set /p CONF=Digite SIM para continuar, qualquer outra coisa cancela: 
if /i not "%CONF%"=="SIM" (
  echo Cancelado. Nada foi feito.
  goto :fim
)
python tools\lab_git.py init --confirm LAB-GIT-INIT >> %LOG% 2>&1
echo [%DATE% %TIME%] init terminou, codigo %ERRORLEVEL% >> %LOG%
:fim
echo Estado inicial: reports\GITLAB_BASELINE.json/.md (ou GITLAB_STATE). Log: %LOG%
echo Pode fechar esta janela.
