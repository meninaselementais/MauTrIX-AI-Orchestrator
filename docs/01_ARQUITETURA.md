# 01 — Arquitetura de adaptadores

Estado: **V1 é só projeto e diagnóstico.** Nenhum agente é executado automaticamente por este projeto.

## Visão geral

```text
Coordenador GPT (humano na ponte)         Orquestrador local (Windows)                 Agentes
─────────────────────────────────         ─────────────────────────────                ───────
instrução (texto) ── cola/importa ──►  inbox: instructions/TASK-NNNN.json
                                         │ valida (schemas/task.schema.json)
                                         │ checa política (docs/05_SEGURANCA.md)
                                         ▼
                                       Adaptador do agente ───────────────────────►  Claude Code
                                         │  (V1: só descreve; V2: gera pacote;       Codex CLI
                                         │   V3: executa com supervisão)             Antigravity CLI / IDE
                                         ▼
                                       reports/TASK-NNNN.json + .md   (schemas/report.schema.json)
                                         │
relatório para revisão ◄── exporta ──  reports/REVIEW-TASK-NNNN.md
```

Não existe comunicação automática com a conversa do GPT. O humano transporta texto nos dois sentidos. O orquestrador só prepara, valida e arquiva.

## Contrato de um adaptador

Todo adaptador descreve o mesmo conjunto de capacidades. Cada campo tem um valor "desconhecido" explícito; ausência de informação nunca vira "sim".

| Campo | Significado | Valores |
|---|---|---|
| `id` | Identificador estável | `claude_code`, `codex_cli`, `antigravity_cli`, `antigravity_ide` |
| `launch` | Comando de inicialização, quando existir | caminho + argumentos, ou `null` |
| `version` | Versão instalada (do `--version` real) | texto ou `null` |
| `auth_state` | Estado de autenticação verificável | `AUTENTICADO`, `NAO_AUTENTICADO`, `INDETERMINADO`, `DESCONHECIDO`, `COMANDO_NAO_SUPORTADO` |
| `can_execute` | Pode executar tarefas sem interface | `supported_official`, `supported_unverified`, `manual_only`, `unsupported` |
| `result_format` | Como o resultado volta | `json`, `stream-json`, `text`, `manual_paste` |
| `limit_detection` | Como reconhecer erro de limite | lista de sinais, ou vazio se não confirmado |
| `quota_state` | Cota restante | sempre `STATUS DESCONHECIDO` sem fonte oficial |
| `run_log` | Registro por execução | arquivo em `runs/` e `logs/` |

A configuração real fica em `config/agents.json`, com o nível de confirmação de cada afirmação (`oficial`, `comunidade`, `nao_confirmado`).

## Estados dos agentes (resumo do que foi apurado em 05/11/2026)

| Agente | Execução sem interface | Verificação de autenticação | Consulta de cota |
|---|---|---|---|
| Claude Code | **Oficial:** `claude -p`, saída `json` ou `stream-json`, `--allowedTools`, `--permission-mode` | **Oficial:** `claude auth status` (JSON; código 0 logado, 1 não) | Não encontrada |
| Codex CLI | **Parcial:** `codex exec` e `--json` citados em issue do repositório oficial; página oficial não lida | **Comunidade:** `codex login status` | Não existe em modo não interativo (issue aberta) |
| Antigravity CLI (`agy`) | **Não confirmado oficialmente:** Google diz que a CLI tem execução headless, sem sintaxe; `agy -p` vem de artigo de terceiros | Sem comando confirmado | Só dentro da interface interativa, segundo terceiros |
| Antigravity IDE | Não se aplica (interface gráfica) | Não se aplica | Sem fonte |

Por isso a arquitetura trata cada agente como **possivelmente manual**. O modo `manual_by_user` é cidadão de primeira classe: o orquestrador prepara o pacote e o humano executa.

## Ciclo de vida de uma tarefa

1. `IMPORTADA`: instrução colada pelo humano em `instructions/`.
2. `VALIDADA`: passou no schema e na política de segurança. Caso contrário `REJEITADA`, com o motivo.
3. `AGUARDANDO_AGENTE`: adaptador escolhido, estado de autenticação e de limite checados.
4. `TRAVADA`: lock do projeto adquirido (um escritor por vez).
5. `EXECUTANDO` (V3+) ou `PACOTE_ENTREGUE` (V2, modo manual).
6. `RELATORIO_RECEBIDO`: relatório no formato padrão salvo em `reports/`.
7. `EXPORTADO`: `REVIEW-TASK-NNNN.md` gerado para revisão pelo coordenador.
8. `ENCERRADA`: lock liberado.

## Exclusão mútua

Um arquivo `locks/<nome-do-projeto>.lock` guarda agente, PID/usuário, `task_id`, horário e validade (TTL). Regras:

- Só um agente com `mode=write` por projeto. Tarefas `read_only` podem coexistir com um escritor, mas nunca com outro escritor.
- Lock vencido não é apagado automaticamente: o orquestrador pede confirmação humana, porque o processo pode ainda estar escrevendo.
- Nada de `git reset --hard` ou `git clean` para "limpar" depois de falha.

## Detecção de limite

Sinais por agente vêm da configuração. Hoje só o Claude Code tem sinais **oficiais** (`system/api_retry` com `error` em `rate_limit`, `overloaded`, `billing_error`, `account_on_hold`). Para os demais a lista está vazia até capturarmos uma mensagem real. Ao detectar limite, o orquestrador:

1. grava `status=blocked_by_limit` e a mensagem bruta;
2. **não** tenta de novo em loop e **não** tenta outro caminho para contornar o limite;
3. marca a cota como `STATUS DESCONHECIDO` e devolve a decisão ao humano (esperar, trocar de agente manualmente).

## Registro

- `runs/TASK-NNNN/`: entrada, saída bruta, estado do Git antes e depois.
- `logs/orchestrator.log`: linha por evento, em UTF-8, sem segredos.
- Redação automática de e-mails e sequências longas parecidas com tokens antes de gravar.
