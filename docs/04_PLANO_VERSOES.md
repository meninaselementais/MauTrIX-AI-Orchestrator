# 04 — Plano de implementação das próximas versões

Cada versão exige autorização antes de começar e só avança se a anterior estiver validada com evidência real.

| Versão | Objetivo | Entregas | Critério de saída | Depende de |
|---|---|---|---|---|
| **V1** (esta) | Projeto, diagnóstico, protocolo | Estrutura, `agents.json`, schemas, `diagnose.py`, documentos | Diagnóstico executado no Windows e lido; documentos revisados | — |
| **V1.1** | Fechar o inventário | Preencher `docs/06_DIAGNOSTICO.md` com versões e capacidades reais; ajustar `agents.json` pelo `--help` local de `codex exec` e `agy` | Cada capacidade marcada como confirmada localmente ou como desconhecida | Rodar o diagnóstico |
| **V2** | Fluxo supervisionado **manual** | `import`: valida tarefa (schema e política); `package`: gera `PACOTE.md` com o comando exato por agente; `report`: valida e arquiva relatório; `export`: gera `REVIEW-*.md`; lock de projeto | Uma tarefa `read_only` de ponta a ponta, executada pelo humano, com relatório válido | V1.1 |
| **V3** | Execução automática **supervisionada** de agentes com CLI oficial | Adaptador Claude Code (`claude -p`, JSON, permissão restrita, `--max-budget-usd`); adaptador Codex (`codex exec`) depois de confirmar flags; tempo limite com encerramento da árvore de processos; contagem de tentativas; snapshot do Git antes e depois (somente leitura) | Tarefa `read_only` automática por agente, sem alteração no projeto; depois `write` com `allowed_write_paths` | V2 |
| **V4** | Antigravity | Adaptador `agy` somente se houver documentação oficial de modo headless; senão permanece manual | Documentação oficial citada em `agents.json` | V3 |
| **V5** | Estado de cota | Exibir cota **somente** onde houver fonte oficial; senão `STATUS DESCONHECIDO` | Nenhum número sem fonte | V3 |
| **V6** | Painel local sob demanda | Página HTML estática gerada a partir de `reports/`; sem serviço permanente | Abrir o arquivo mostra histórico e estado | V2 |

## Itens transversais

- Testes automatizados do validador de schema e da política (V2).
- Teste de que uma tarefa com `commit: true` é rejeitada.
- Teste de que o diagnóstico não acessa nenhum caminho de autenticação (revisão de código e lista de arquivos tocados).
- `git init` do próprio orquestrador só com autorização; nenhum commit automático.

## Fora de escopo até nova decisão

Coordenação automática com o GPT, APIs pagas, serviços em segundo plano, qualquer alteração em `C:\Projetos\CS-Puzzle-Fighter-96`.
