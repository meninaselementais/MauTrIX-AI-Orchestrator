# 10 — TASK-0004: validação real do Codex com contexto embutido (V3.3)

Status: **preparada, NÃO executada.** Nenhum agente real foi iniciado. Aguarda autorização para consumir cota do Codex.

## Objetivo
Verificar se o Codex 0.166.0 no Windows conclui a leitura de `lab/projeto_descartavel/texto_exemplo.txt` quando o orquestrador entrega o conteúdo no prompt (`context_delivery: "embedded"`), sem depender do shell do agente (que está bloqueado por política).

## Arquivos
| Arquivo | Função |
|---|---|
| `instructions/TASK-0004_codex_embedded_lab.json` | Tarefa nova. `agent: codex_cli` (fixo, sem transferência), `read_only`, `max_attempts: 1`, único contexto `texto_exemplo.txt`. |
| `tools/validar_task0004.py` | `dry-run` (não inicia agente) e `run --confirm TASK-0004` (uma execução real). Gera evidências. |
| `Validar_TASK0004.cmd` | Dry-run automático; execução real só após digitar `SIM`. Janela permanece aberta. |
| `diagnostics/task0004_dryrun.json/.md` | Evidência do dry-run (gerada ao rodar). |
| `diagnostics/task0004_evidence.json/.md` | Evidência da execução real (gerada ao rodar). |
| `diagnostics/task0004_log.txt` | Log da sessão do `.cmd`. |

Alterados nesta etapa: `tests/test_v3_simulated.py` (testes S1–S7). Nada do histórico foi editado.

## Controles de segurança
1. **Agente fixo `codex_cli`**; sem transferência ao Claude; uma tentativa; sem repetição automática.
2. **Execução única**: se já existir relatório `RUN-*-TASK-0004-*`, o script recusa antes de iniciar o agente.
3. **Confirmação dupla**: `SIM` no `.cmd` e `--confirm TASK-0004` no script.
4. **Pré-verificação** (qualquer falha impede a execução): tarefa válida; `mode = read_only`; projeto exatamente `lab\projeto_descartavel`; contexto exatamente `texto_exemplo.txt`; `enabled_for_real_projects = false`; `context_delivery = "embedded"`; `exec_extra_args` na lista permitida; arquivo com 12 linhas não vazias; nenhum lock existente.
5. **Comando conferido sem executá-lo**: `--sandbox read-only`, sem argumento proibido (`danger-full-access`, `--full-auto`, bypass, `--approve-for-me`), prompt contém exatamente o conteúdo do arquivo (SHA-256 no delimitador) e diz que NÃO são necessários comandos; não contém a permissão de shell.
6. **Entrega independente do agente**: o orquestrador lê o arquivo em UTF-8 estrito (limite 64 KiB) e o injeta no prompt como dados. Arquivo que não for UTF-8 falha antes de iniciar o agente.
7. **Histórico preservado**: SHA-256 de `reports/`, `runs/`, `handoffs/`, `logs/` (logs só podem crescer, com início idêntico) antes e depois. TASK-0003, seus relatórios e o registro bloqueante `task_rejected_review_required` não são tocados nem movidos.
8. **Laboratório**: SHA-256 antes/depois; qualquer diferença reprova.
9. **Locks**: exigidos vazios antes e depois.
10. **Projetos reais**: nenhum. O caminho é validado contra `lab\projeto_descartavel`; o projeto do jogo não é referenciado; sem commit, push, tag ou API paga.

## Critérios obrigatórios (veredito `VALIDACAO_APROVADA` só com todos)
- `line_count = 12`
- JSON válido (EXECUTION_SUCCESS com saída estruturada)
- `TASK_ACCEPTED` e status `completed`
- arquivos do laboratório preservados
- locks liberados
- histórico preservado

Qualquer falha gera `VALIDACAO_REPROVADA_*` com o campo `diagnosis` (política, codificação, cota, autenticação). Não repetir automaticamente.

## Testes simulados
S1 dry-run aprovado e sem agente iniciado; S2 recusa sem `embedded`; S3/S3b execução simulada aprovada e histórico preservado; S4 segunda execução recusada; S5 confirmação errada; S6 contagem errada reprovada; S7 laboratório intacto. Total da suíte: 55 de 55 (Linux, agentes simulados). Pendente no Windows.

## Comando exato para a validação real (somente após autorização)
```
cd /d C:\Projetos\MauTrIX-AI-Orchestrator
Validar_TASK0004.cmd
```
Digitar `SIM` quando solicitado. Equivalente manual:
```
python tools\validar_task0004.py dry-run
python tools\validar_task0004.py run --confirm TASK-0004
```

## Resultado real (2026-11-05 17:26)
`VALIDACAO_APROVADA` — ver `docs/09_VALIDACAO_V3_WINDOWS.md`, seção 10, e `errata/ERRATA_V3_3.md` (campo `agent_started` da evidência estava incorreto por defeito do script; já corrigido).
