# 06 — Diagnóstico dos agentes (V1.1, finalizado em 05/11/2026)

Fonte: `diagnostics/v1_1_ultimo.json` (execução local feita pelo usuário às 03:05) e os helps salvos em
`diagnostics/help/`. Só constam fatos confirmados. Nenhuma tarefa real foi executada nesse diagnóstico e
nenhum token, cookie ou arquivo de credenciais foi aberto.

## 1. Executáveis e versões

| Agente | Executável | Versão | Evidência |
|---|---|---|---|
| Claude Code | `...\AppData\Local\Microsoft\WinGet\Links\claude.EXE` | 2.1.302 | `--version` local |
| Codex CLI | `...\AppData\Local\Programs\OpenAI\Codex\bin\codex.EXE` | 0.166.0 | `--version` local |
| Antigravity (app) | `...\AppData\Local\Programs\antigravity\Antigravity.exe` | 2.29.0 (registro HKCU, Google) | registro + pasta; **não executado** |
| Antigravity IDE | `...\AppData\Local\Programs\Antigravity IDE\Antigravity IDE.exe`, `bin\antigravity-ide.cmd` | 2.1.1 (registro HKCU, Google) | registro + pasta; **não executado** |
| Antigravity CLI (`agy`) | não encontrado no PATH | — | `shutil.which` |

Há também `antigravity-updater\installer.exe`. Atalhos no Menu Iniciar: `Antigravity.lnk` e `Antigravity IDE\Antigravity IDE.lnk`.
As pastas de usuário `.antigravity-ide`, `.gemini`, `%APPDATA%\Antigravity` e `%APPDATA%\Antigravity IDE` existem; o conteúdo não foi aberto.

## 2. Métodos de execução não interativa

**Claude Code** — `claude -p` (stdin aceito). Flags confirmadas no `--help` local: `--output-format text|json|stream-json`,
`--json-schema`, `--allowedTools`, `--disallowedTools`, `--permission-mode` (acceptEdits, auto, bypassPermissions, manual,
dontAsk, plan), `--permission-prompts host|none`, `--max-budget-usd`, `--restricted`, `--safe-mode`,
`--no-session-persistence`, `--effort`. **`--max-turns` não existe nesta versão.** A flag `--dangerously-skip-permissions`
existe e é proibida pela política do orquestrador.

**Codex CLI** — `codex exec [PROMPT]` (prompt por argumento ou stdin; alias `e`). Flags confirmadas em `codex exec --help`:
`--sandbox read-only|workspace-write|danger-full-access`, `--cd`, `--skip-git-repo-check`, `--ephemeral`,
`--ignore-user-config`, `--json` (JSONL), `--output-schema`, `--output-last-message`, `--color`, `--model`, `--profile`,
`--config`. `--ask-for-approval` e `--full-auto` **não** existem em `exec`. A flag de bypass total existe e é proibida.

**Antigravity** — nenhuma interface de automação confirmada. A fonte oficial diz só que a CLI tem modo headless, sem sintaxe;
`agy -p` vem de artigo de terceiros e `agy` não está instalado. A IDE é gráfica. Se o `Antigravity.exe` 2.29.0 inclui uma
CLI não foi verificado (executá-lo poderia abrir janela). Permanece **desativado**.

## 3. Autenticação

| Agente | Estado | Base |
|---|---|---|
| Claude Code | confirmado (`loggedIn: true`, `authMethod: claude.ai`) | `claude auth status`, saída documentada oficialmente |
| Codex CLI | confirmado localmente ("Logged in using ChatGPT", código 0) | `codex login status`; só a mensagem positiva é aceita, o caso negativo não foi observado |
| Antigravity | desconhecido | nenhum comando verificado |

## 4. Cota e detecção de limite

Cota restante dos três: **STATUS DESCONHECIDO**. Nenhum comando oficial e não interativo foi encontrado nos helps locais
(nenhuma linha dos helps trata de uso/limite). Não há estimativa de créditos neste projeto.

- Claude Code: sinais documentados em `system/api_retry` (`rate_limit`, `overloaded`, `billing_error`, `account_on_hold`).
- Codex CLI e Antigravity: detecção só por padrão de texto na saída de erro (heurística, não oficial).
- `total_cost_usd` do Claude é estimativa do cliente, não cota.

## 5. Não verificado

- Formato exato dos erros de limite do Codex e do Claude em `-p` (sem mensagem real capturada).
- Se `--restricted` e `--safe-mode` do Claude funcionam juntos em `-p` (será visto no teste da V2).
- Comportamento do Antigravity em modo headless.

## 5b. Resultados reais da V2 (4 relatórios em `reports\`, 05/11/2026 03:13–03:14)

| Relatório | Agente | Classe do resultado | Evidência |
|---|---|---|---|
| RUN-…031328042-TASK-0001 | Claude Code 2.1.302 | **Execução bem-sucedida** (exit 0, 10,5 s, 3/3 critérios, `line_count` 12 = contagem do orquestrador, lab intacto) | relatório + SHA-256 |
| RUN-…031336113-TASK-0002 | Codex 0.166.0 | **Bloqueio por lock** (`_global_agent.lock` retido por TASK-0001); agente não iniciado | `rejected_by_policy` |
| RUN-…031345590-TASK-0002 | Codex 0.166.0 | **Bloqueio por limite de uso** (exit 1, 2,1 s, sem saída, lab intacto). Mensagem real: "You've hit your usage limit… try again at 3:53 AM." | eventos `error` e `turn.failed` |
| RUN-…031425392-TASK-0001 | Claude Code 2.1.302 | **Execução bem-sucedida** (exit 0, 10,9 s, 3/3 critérios) | relatório + SHA-256 |

Não observados em execução real: erro de autenticação, erro técnico, timeout (cobertos só por testes simulados na V3).

- A autenticação confirmada do Codex não implicou cota disponível.
- A execução bem-sucedida do Codex continua **pendente**.
- O limite do Codex foi identificado pela mensagem de erro; a cota restante segue STATUS DESCONHECIDO.
- `--restricted` + `--safe-mode` funcionaram juntos no Claude `-p`.
- O horário na mensagem do Codex é dica do agente (sem data nem fuso) e não é usado pelo orquestrador.

## 6. Participação na V2

| Agente | V2 |
|---|---|
| Claude Code | participa (somente leitura, laboratório) |
| Codex CLI | participa (somente leitura, laboratório) |
| Antigravity | desativado |
