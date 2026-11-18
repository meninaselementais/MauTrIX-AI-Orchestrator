# 02 — Protocolo de transferência de contexto (fluxo supervisionado)

Objetivo: levar uma instrução do coordenador GPT até um agente e trazer o resultado de volta **sem** API paga e **sem** afirmar que existe canal automático com a conversa do GPT. O humano é a ponte.

## Fluxo

| # | Quem | Ação | Arquivo |
|---|---|---|---|
| 1 | GPT | Elabora a instrução no formato abaixo | texto na conversa |
| 2 | Humano | Cola em `instructions/TASK-NNNN.json` | `schemas/task.schema.json` |
| 3 | Orquestrador | Valida schema e política; rejeita com motivo se violar | `logs/orchestrator.log` |
| 4 | Orquestrador | Escolhe agente disponível (autenticado, sem limite conhecido) e gera o pacote | `runs/TASK-NNNN/PACOTE.md` |
| 5 | Agente | Executa (V2: o humano roda; V3+: o orquestrador roda com supervisão) | `runs/TASK-NNNN/` |
| 6 | Orquestrador | Salva relatório padronizado | `reports/TASK-NNNN.json` e `.md` |
| 7 | Orquestrador | Exporta resumo para revisão | `reports/REVIEW-TASK-NNNN.md` |
| 8 | Humano | Cola o `REVIEW` na conversa com o GPT | — |
| 9 | GPT | Revisa e emite a próxima instrução | volta ao passo 1 |

## Formato da instrução

JSON conforme `schemas/task.schema.json`. Campos que importam para segurança:

- `mode`: `read_only` (padrão) ou `write`. `write` exige `allowed_write_paths` não vazio e confirmação humana antes de executar.
- `limits`: `timeout_seconds` e `max_attempts` (máximo 3).
- `git_policy`: `commit`, `push`, `merge`, `tag` fixos em `false`. Qualquer valor diferente rejeita a tarefa.
- `acceptance`: critérios verificáveis; cada um aparece no relatório como `yes`, `no` ou `not_verified`.

Exemplo mínimo:

```json
{
  "schema_version": 1,
  "task_id": "TASK-0001",
  "created_by": "coordenador GPT",
  "project_path": "C:\\Projetos\\ExemploDeProjeto",
  "agent": "any_available",
  "mode": "read_only",
  "objective": "Listar os testes existentes e dizer como cada um é executado.",
  "context_files": ["README.md"],
  "limits": {"timeout_seconds": 600, "max_attempts": 1},
  "git_policy": {"commit": false, "push": false, "merge": false, "tag": false},
  "acceptance": ["Lista de testes com o comando de cada um", "Nenhum arquivo alterado"]
}
```

## Formato do relatório

JSON conforme `schemas/report.schema.json`, com versão em Markdown para leitura. Regras que vieram da prática da V11.2 do jogo:

1. **Cada resultado leva uma classe de evidência:** `executed_by_agent`, `executed_by_user`, `static_review`, `reused_from_previous_run` ou `not_verified`. Verificação estática nunca é descrita como teste executado.
2. **Estado do Git antes e depois** (HEAD e `status --short`), ou `null` se não foi possível obter, dizendo por quê.
3. **Limite detectado:** `detected`, tipo e mensagem bruta. `quota_status` é sempre `STATUS DESCONHECIDO`.
4. **Critérios de aceite** com `yes`/`no`/`not_verified`.
5. **Riscos e pendências** em listas separadas.

## Pacote de revisão para o GPT

`reports/REVIEW-TASK-NNNN.md` é curto e autossuficiente:

1. objetivo e agente usado (com versão);
2. status e critérios de aceite;
3. evidências por classe;
4. arquivos alterados e criados;
5. estado do Git;
6. riscos e pendências;
7. a pergunta final: "Qual a próxima instrução?".

Não inclui logs completos, só caminhos. Logs ficam em `runs/`.

## Importar a próxima instrução

Mesmo caminho do passo 2. O orquestrador recusa instruções que:

- peçam `commit`, `push`, `merge`, `tag`, `git reset --hard` ou `git clean`;
- apontem para fora de `project_path` ou dentro de `forbidden_paths`;
- peçam para ler arquivos de autenticação, cookies ou tokens;
- peçam para contornar limite de uso ou desativar proteções do agente;
- não tenham critérios de aceite.

## Troca de agente no meio de uma série

Quando um agente bate no limite, a tarefa seguinte pode ir a outro agente. O contexto que acompanha é o **relatório anterior** e os arquivos já em disco, nunca um histórico de conversa copiado. Cada agente começa lendo os documentos de continuidade do projeto (no caso do jogo, `CONTINUIDADE_PROJETO.md`).
