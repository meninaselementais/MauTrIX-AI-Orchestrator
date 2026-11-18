# 11 — V4: escrita controlada com Git (laboratório)

Status: **implementada e testada só com agentes SIMULADOS. Nenhum agente real foi executado. Nenhum commit/push/tag feito pelo orquestrador.** O primeiro teste real de escrita aguarda autorização.

## 1. Arquivos
| Arquivo | Função |
|---|---|
| `lab/git_lab/` (README.txt, notas.txt, config.json, src/soma.py, docs/guia.md, .gitignore) | Arquivos de exemplo do repositório descartável. O `.git` só nasce quando você roda `Preparar_Lab_Git.cmd`. |
| `tools/lab_git.py` | `init --confirm LAB-GIT-INIT` (git init + commit-base **somente em lab\git_lab**, cria `rascunho_local.txt` não rastreado e `cache_local.tmp` ignorado) e `state`. Grava `reports\GITLAB_BASELINE.json/.md`. |
| `src/mautrix_orq/gitops.py` | Git **somente leitura** (allowlist `rev-parse/status/diff/ls-files/show-ref/symbolic-ref/log`; recusa reset, clean, merge, rebase, push, tag, commit, checkout, stash, add…). |
| `src/mautrix_orq/writescope.py` | Validação da tarefa de escrita, workspace, escopo/limites/UTF-8, validações declarativas, proposta, promoção com backup, restauração. |
| `src/mautrix_orq/write_executor.py` | Executor de escrita (uma tentativa, um agente). |
| `src/mautrix_orq/write_failover.py` | Transferência segura para escrita. |
| `src/mautrix_orq/adapters.py` | `ClaudeAdapter.build_write_command`, `CodexAdapter.build_proposal_command`, `build_write_prompt`. |
| `schemas/agent_result_write.schema.json`, `schemas/agent_proposal.schema.json` | Formato de resposta do Claude (edição) e do Codex (proposta). |
| `instructions/TASK-1001_write_claude_lab.json`, `TASK-1002_write_codex_proposal_lab.json` | Tarefas de exemplo (NÃO executadas). |
| `tools/supervisor.py` | Novos comandos `write-dry-run`, `write-run`, `write-failover`, `write-restore`. |
| `tests/test_v4_write.py`, `tests/fakes/fake_agent.py` | 56 testes simulados / modos de escrita dos agentes falsos. |
| `Preparar_Lab_Git.cmd`, `V4_DryRun.cmd`, `Testes_V4_Windows.cmd` | Atalhos Windows (janela permanece aberta). |
| `config/failover.json` | `write_priority`: Claude primeiro (edita), Codex depois (propõe). |

## 2. Arquitetura de escrita
```
tarefa (allowed_modify / allowed_create / limites / validações)
  → pré-condições Git (raiz do repo, HEAD, sem merge/rebase em curso, arquivos autorizados limpos e rastreados)
  → manifesto de preservação (hash de TODOS os arquivos, incl. não rastreados e ignorados) + impressão digital do repo
  → workspace isolado: cópia dos arquivos RASTREADOS, sem .git e sem não rastreados
  → agente roda no workspace (cwd) — Claude edita; Codex só devolve uma proposta JSON
  → repo real mudou durante a execução? → VIOLATION (nada é promovido)
  → escopo / limites / UTF-8 / validações declarativas (em processo, sem shell)
  → promoção: confere que o real não mudou, faz backup, grava atomicamente, verifica hash, desfaz com o backup se falhar
  → verificação de preservação (HEAD/branch/refs, não rastreados, demais arquivos idênticos) + patch (diff unificado + git diff)
```
Nenhum commit. Arquivos criados ficam como não rastreados; modificados aparecem em `git status`/`git diff` para você revisar.

## 3. Controles preventivos (o que impede, não só detecta)
1. **Isolamento por cópia:** o repositório real e o `.git` não estão no diretório de trabalho do agente. Violações de escopo ficam no workspace e são descartadas.
2. **Claude:** `--restricted` (remove Bash/PowerShell/WebFetch e confina ferramentas de arquivo ao diretório de trabalho), `--tools Read,Glob,Grep,Edit,Write`, `--allowedTools` com `Edit(./arquivo)`/`Write(./arquivo)` por arquivo, `--disallowedTools Bash,PowerShell,WebFetch,WebSearch,NotebookEdit`, `dontAsk` + `--permission-prompts none`, `--safe-mode`. Flags conferidas no `--help` local (2.1.302). **Não verificado:** a sintaxe exata das regras por arquivo; se divergir, o efeito esperado é negar edições (falha segura → TASK_REJECTED), não ampliar permissão.
3. **Codex:** continua `--sandbox read-only`, `--ignore-user-config`, sem `--full-auto`/bypass/`workspace-write`. Recebe o conteúdo dos arquivos autorizados no prompt (embedded, ≤128 KiB) e devolve `{changes:[{path,action,content}]}`; **o orquestrador** aplica no workspace. Configurar `write_strategy: "workspace_edit"` no Codex é recusado.
4. **Lista explícita:** `allowed_modify` (precisam existir, rastreados e sem pendências) e `allowed_create` (não podem existir). Caminhos relativos, ASCII, sem `..`, `:`, `\`, `.git*`, nomes reservados do Windows.
5. **Limites:** até 10 arquivos, `max_files_changed`, `max_bytes_changed`, 64 KiB por arquivo, só texto UTF-8, sem NUL, sem links simbólicos, **nenhuma exclusão**.
6. **Interrupção em violação:** estado `violation_review_required`; nada promovido; workspace preservado; nova execução bloqueada até revisão.
7. **Conflito:** se o arquivo real mudou desde o início, a promoção é recusada (nunca sobrescreve alteração desconhecida).
8. **Locks:** lock global + por projeto (BUSY em execução simultânea); locks nunca removidos automaticamente.
9. **Git:** só leitura; `GIT_OPTIONAL_LOCKS=0`; sem hooks executados; commit/push/merge/rebase/reset/clean/tag inexistentes no código das tarefas.
10. **Projetos reais:** escrita só em `lab\git_lab` (caminho exato validado); `enabled_for_real_projects` continua `false`.

## 4. Failover de escrita
- Limite/autenticação **antes** de qualquer alteração → transferência segura (handoff sem resultado parcial).
- Agente que **já alterou** o workspace (limite depois de escrever, morte do processo, timeout) → `changes_present_review_required`, sem transferir.
- Violação → `violation_review_required`. Resultado desconhecido/erro técnico → `stopped_unknown_result`.
- A impressão digital do repositório é conferida antes de cada passo: se mudou, o passo seguinte é recusado.
- Uma tentativa por agente; nenhuma repetição automática.

## 5. Resultados SIMULADOS (Linux, Python 3.13, agentes falsos, Git real do sistema)
- **V4: 56 de 56.** Cobrem: laboratório e estado inicial; Git read-only; dry-run sem efeitos; alteração e criação autorizadas (TASK_ACCEPTED, backup, patch, manifesto, locks, histórico); não rastreado e ignorado preservados; HEAD/branch/refs iguais, nenhum commit/tag; alteração, exclusão e criação proibidas; limites (arquivos, bytes, binário); escrita no repositório real (rastreado e não rastreado); falha de validação; interrupção durante a edição; timeout após escrita (processo encerrado); proposta do Codex (ok, fora do escopo, `..`, escrita indevida, validação); pré-condições Git (pendência, merge em curso, sem repo); caminhos inseguros; execução simultânea e lock; failover (limite antes/depois de modificar, violação, morte do processo, ambos no limite, sem transferência, repositório mudou entre passos); recuperação (`write-restore` sem perda e com confirmação exata).
- **V3: 55 de 55** (sem regressão).
- Testes de mutação: removendo a detecção de escrita no repositório real ou o bloqueio de alteração fora da lista, os testes B7/B8/B1 reprovam.
- **Pendente:** rodar no Windows (`Testes_V4_Windows.cmd`), exige `git` no PATH. Nenhum teste real.

## 6. Alternativas oficiais para edição controlada com o Codex (investigação, nada executado)
Fonte: `codex exec --help` local (0.166.0). O shell do agente continua bloqueado; **nada abaixo contorna o bloqueio**.
| Alternativa | Situação |
|---|---|
| **Proposta + aplicação pelo orquestrador** (implementada) | Não depende de shell nem de escrita do agente. Limitada a arquivos pequenos e UTF-8. |
| `--sandbox workspace-write` em workspace isolado | Existe no `--help`. NÃO testado: o shell (CreateProcess) provavelmente continua bloqueado; a ferramenta nativa de edição (`apply_patch`) pode funcionar sem processo, mas **não está verificado**. Só considerar com o workspace descartável e revisão do resultado. |
| `--add-dir` / `--worktree` | Existem no `--help`; só ampliam diretórios graváveis. Não necessários e não adotados. |
| `--output-schema` | Já usado para forçar o formato da proposta. |
Não usar: `--dangerously-bypass…`, `--full-auto`, `--approve-for-me`.

## 7. Limitações
- Só texto UTF-8 pequeno; sem exclusões, renomeações, binários, links simbólicos ou submódulos.
- Claude vê apenas os arquivos rastreados; arquivos não rastreados ficam invisíveis a ele (de propósito).
- O isolamento é por diretório de trabalho e permissões da ferramenta; não é um sandbox de SO. Um agente que ignore as permissões e escreva por caminho absoluto no repositório real é DETECTADO (hash/Git), não impedido; nesse caso nada é promovido e não há restauração automática.
- `rascunho_local.txt` e `cache_local.tmp` só provam preservação no laboratório.
- Quebras de linha: o orquestrador não converte CRLF/LF (exceto na proposta do Codex, que respeita CRLF de arquivo já CRLF).
- `workspaces\` e `backups\` não são apagados automaticamente.

## 8. Riscos restantes
1. Sintaxe das regras `Edit(./arquivo)` do Claude não verificada localmente.
2. Escrita por caminho absoluto fora do workspace (detectada, não impedida).
3. Janela entre a verificação de conflito e a gravação (milissegundos; um processo externo poderia editar no intervalo).
4. Claude pode ler arquivos rastreados fora da lista (leitura é permitida).
5. Windows: Defender/antivírus ou bloqueio de arquivo pode falhar a gravação (desfeito pelo backup); Git ausente no PATH recusa a tarefa.
6. O commit-base do laboratório é feito por `lab_git.py init` (ação sua); qualquer outro commit só com sua autorização.
7. Falhas ainda não observadas em agentes reais (formato de saída do Claude com `Edit`, limites reais).

## 9. Plano para o primeiro teste REAL de escrita (aguarda autorização; consome cota do Claude)
Pré-requisitos (sem cota): (1) `Testes_V4_Windows.cmd` → V3 55/55 e V4 56/56, códigos 0, sem `fake_agent`; (2) `Preparar_Lab_Git.cmd` (digitar SIM) e conferir `reports\GITLAB_BASELINE.md`; (3) `V4_DryRun.cmd` e conferir `command` (`--restricted`, sem `Bash` permitido) e `git_before` limpo.
Execução única, **somente Claude, tarefa TASK-1001** (editar `notas.txt` e criar `resultado.txt`):
```
cd /d C:\Projetos\MauTrIX-AI-Orchestrator
python tools\supervisor.py write-run instructions\TASK-1001_write_claude_lab.json --confirm TASK-1001
```
Esperado: `TASK_ACCEPTED`, `git status` com ` M notas.txt` e `?? resultado.txt`, arquivos não rastreados intactos, HEAD igual, patch em `patches\`. Se for `TASK_REJECTED`/`VIOLATION`: ler `write.violations` e `diagnosis`, não repetir. Desfazer, se quiser: `write-restore <RUN-ID> --confirm RESTORE-<RUN-ID>`. Nenhum commit. Só depois (outra autorização): TASK-1002 (Codex em modo proposta) e um failover real de escrita.

## 10. Primeira validação no Windows e correção (2026-11-05 19:22)
V3: 55/55, código 0. V4: apareceram "34/34" e código 1. **Não foi aprovação:** a suíte V4 implementa **56** verificações, executou 34 e abortou no cenário P4 com `PermissionError` ao apagar, na cópia temporária, o `.git` (objetos do Git são somente leitura no Windows). Defeito do teste; o laboratório real e o commit-base não foram tocados. Correções: `rmtree_force`, `EXPECTED_CHECKS = 56` com `SUITE INCOMPLETA` e código 1 se houver exceção ou contagem diferente, e destaque no `.cmd`. Detalhes em `reports\ERRATA_V3_3.md` (errata V4). Dry-runs conferidos: Git limpo, HEAD = commit-base.
**Revalidação pendente no Windows:** `Testes_V4_Windows.cmd` deve mostrar V3 55/55, V4 **56/56 (esperadas 56)**, ambos com código 0 e nenhum `fake_agent` restante. A pasta temporária `mxv4_eo4fs05o` em `%TEMP%` ficou da execução abortada e pode ser apagada.
