# 05 — Política de segurança

Regras obrigatórias para qualquer versão do orquestrador. Violação rejeita a tarefa.

## Projetos e Git

1. **Um escritor por projeto.** Lock em `locks/<projeto>.lock` (agente, task_id, horário, validade). Lock vencido exige confirmação humana.
2. **Nunca** executar `git reset --hard`, `git clean`, `git checkout -- .`, `git restore .`, `git stash drop` ou qualquer comando que descarte alterações locais ou arquivos não rastreados.
3. **Nunca** `commit`, `push`, `merge`, `rebase` ou `tag` automáticos. O campo `git_policy` da tarefa é fixo em `false`; qualquer outro valor rejeita a tarefa.
4. Antes e depois de cada execução com escrita, registrar HEAD e `status --short` (somente leitura).
5. Preservar alterações locais e arquivos não rastreados; nunca apagar arquivos sem autorização explícita registrada na tarefa.
6. O diretório do jogo `C:\Projetos\CS-Puzzle-Fighter-96` é projeto de terceiros para este orquestrador: nenhuma versão o altera sem tarefa `write` aprovada pelo humano.

## Agentes

7. Não ler tokens, cookies, chaves, keyring nem arquivos de autenticação dos agentes. O estado de autenticação só vem de comandos oficiais de status.
8. Não desativar permissões, sandbox ou proteções dos agentes. Nada de modos "sem aprovação" amplos; permissões por lista explícita de ferramentas.
9. Não contornar limites de uso: nada de rotacionar contas, repetir em loop ou usar rotas não documentadas.
10. **Claude Code em `-p` executa hooks e conecta MCP do projeto sem pedir confiança.** Só rodar em projetos controlados pelo usuário, e revisar `.claude/settings.json` e `.mcp.json` do alvo antes da primeira execução automática.
11. Modo padrão de toda tarefa é `read_only`.

## Execução

12. Limite de tempo por execução (`timeout_seconds`) e de tentativas (`max_attempts`, no máximo 3). Esgotado, a tarefa termina como `timed_out` ou `failed`; sem nova tentativa silenciosa.
13. Ao encerrar por tempo, matar a árvore de processos (V3).
14. Sem serviço permanente, tarefa agendada ou processo em segundo plano nesta versão.
15. Sem APIs pagas. Sem acesso à rede por parte do orquestrador.

## Registro

16. Cada evento vira linha em `logs/orchestrator.log`; cada execução, uma pasta em `runs/`.
17. Redigir e-mails e sequências longas parecidas com tokens antes de gravar.
18. Relatórios separam execução real de verificação estática; ver `02_PROTOCOLO_CONTEXTO.md`.
19. A cota é sempre `STATUS DESCONHECIDO` sem fonte oficial. Nunca estimar créditos.
