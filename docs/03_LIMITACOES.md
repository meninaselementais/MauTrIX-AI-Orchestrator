# 03 — Relatório de limitações (V1)

Data da apuração: 05/11/2026. Fontes lidas pela web nesta sessão; versões instaladas ainda **não** conhecidas (dependem de `Executar_Diagnostico.cmd`).

## Limitações do projeto

| # | Limitação | Consequência |
|---|---|---|
| L1 | Não há canal automático com a conversa do GPT. | O humano copia e cola instruções e relatórios. O orquestrador nunca afirma o contrário. |
| L2 | A V1 não executa agentes. | Só inventário, projeto e protocolo. |
| L3 | Cota restante é desconhecida para os três agentes. | Todo relatório mostra `STATUS DESCONHECIDO`. Não há estimativa de créditos. |
| L4 | O orquestrador só enxerga o que a máquina local mostra. | O diagnóstico depende do PATH do usuário; instalações fora do PATH aparecem como "não encontrado". |

## O que foi confirmado e o que não foi

| Agente | Confirmado em fonte oficial | Não confirmado |
|---|---|---|
| **Claude Code** | `claude -p`; `--output-format text/json/stream-json`; `--allowedTools`; `--permission-mode`; `--permission-prompts none`; `--max-budget-usd`; `claude auth status` (JSON, código 0/1); `claude doctor`; categorias de erro `rate_limit`, `overloaded`, `billing_error`, `account_on_hold`. | Comando para consultar uso restante da assinatura. |
| **Codex CLI** | Nada lido diretamente: as páginas oficiais redirecionaram para um domínio fora da lista de acesso. | Sintaxe completa de `codex exec`; garantias de `codex login status`. A issue #10233 do repositório oficial (resposta de mantenedor) cita `codex exec --json` e `codex login status`, e diz que não há status de cota fora do `/status` interativo. |
| **Antigravity** | Em artigo do Google Cloud: existem CLI, IDE e SDK; a CLI serve para execução headless (sem sintaxe). | Nome do comando, flags, autenticação e cota em fonte oficial. O nome `agy` e as flags `-p`, `--output-format` vêm de artigo de terceiros. |

## Riscos específicos já identificados

1. **Claude Code em `-p` carrega hooks e MCP do projeto, mesmo em pasta nunca confiada** (documentação oficial). Só pode rodar em projetos que o usuário controla. Ficou registrado em `05_SEGURANCA.md`.
2. **`--bare` não usa o login da assinatura**, só chave de API. Está fora da V1 gratuita.
3. **`total_cost_usd` do Claude Code é estimativa do cliente.** Não serve como medidor de cota.
4. **Sem detecção confiável de limite** para Codex e Antigravity até capturarmos mensagens reais.
5. **Processos filhos:** em Windows, encerrar um `.cmd` por tempo esgotado pode deixar o processo `node` vivo. A V3 precisa matar a árvore de processos.
6. **Diagnóstico executa `--version` e `--help` dos agentes.** São consultas comuns, mas o `--help` de uma CLI de terceiros pode se comportar de forma inesperada; há limite de tempo de 20 s e stdin fechado. A IDE gráfica **não** é executada por padrão.

## O que não será feito

- Ler tokens, cookies, chaves ou arquivos de autenticação de qualquer agente.
- Usar caminhos não documentados (por exemplo, o servidor `app-server` do Codex para ler limites) como base do produto.
- Contornar ou "driblar" limites de uso.
- Usar API paga.
- Criar serviço permanente ou tarefa agendada nesta versão.
