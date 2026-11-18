# 07 — Uso da V2 (execução supervisionada)

Nada roda ao iniciar. Cada execução exige um comando explícito com `--confirm <TASK-ID>`.

## Comandos

```
python tools\supervisor.py check                              # disponibilidade e autenticação; sem tarefas
python tools\supervisor.py dry-run instructions\TASK-0001_claude_lab.json   # valida e mostra o comando
python tools\supervisor.py run instructions\TASK-0001_claude_lab.json --confirm TASK-0001
```

Atalhos: `Verificar_Agentes.cmd`, `Executar_Teste_Claude.cmd`, `Executar_Teste_Codex.cmd` (mostram o dry-run e esperam uma tecla antes de executar).

## O que o executor faz

1. Valida a tarefa (`schemas/task.schema.json` + regras da V2): agente `claude_code` ou `codex_cli`, `mode=read_only`,
   `git_policy` tudo falso, projeto **dentro de `lab\`**, nunca o projeto do jogo.
2. Exige `--confirm` igual ao `task_id`.
3. Confere agente habilitado, executável, versão e autenticação.
4. Adquire dois locks em `locks\` (um agente por vez + um por projeto). Lock existente nunca é removido sozinho.
5. Tira snapshot SHA-256 do laboratório, executa com timeout (encerra a árvore de processos no `timeout`), repete até
   `max_attempts` (máx. 2) só se falhar sem sinal de limite e sem alterar arquivos.
6. Tira novo snapshot; qualquer arquivo criado/alterado/removido em modo somente leitura vira violação.
7. Grava `reports\RUN-*.json` e `.md` e o material bruto (prompt, stdout, stderr redigidos) em `runs\RUN-*\`. Log em `logs\executor.log`.

## Comandos usados pelos adaptadores (todos confirmados no help local)

- Claude: `claude -p --output-format json --json-schema <schema> --permission-mode dontAsk --permission-prompts none --allowedTools Read,Glob,Grep --restricted --safe-mode --no-session-persistence --effort low` (prompt por stdin, cwd = projeto).
- Codex: `codex exec --sandbox read-only --cd <projeto> --skip-git-repo-check --ephemeral --ignore-user-config --json --color never --output-schema <schema> --output-last-message <arquivo> -` (prompt por stdin).

Nenhum adaptador usa flags que ignoram aprovações ou sandbox; o código recusa qualquer argumento com esses fragmentos.
Sem git, sem commit, sem push, sem API paga, sem leitura de credenciais.

## Relatório

Contém agente, versão, projeto, objetivo, início/fim, código de saída, tentativas, arquivos criados/alterados/removidos,
resultado, erros, riscos, critérios (yes/no/not_verified), evidências classificadas e próxima ação sugerida.
Cota sempre `STATUS DESCONHECIDO`.

## Limitações da V2

Só leitura; só laboratório; sem troca automática por limite (apenas registro); Antigravity desativado; schema de resposta
específico do laboratório; detecção de limite por texto; sem lock de processo órfão automático.
