# Errata V3.2 (05/11/2026)

Os registros abaixo foram gerados pela lógica anterior e NÃO foram editados. A classificação correta é:

- `RUN-20261105_154231375-TASK-0003-codex_cli`: EXECUTION_SUCCESS, **TASK_REJECTED** (critério "line_count confere" = no; o Codex devolveu line_count 0 porque o prompt da V2 o proibia de executar comandos).
- `TRANSFER-20261105_154231373-TASK-0003`: estado gravado `completed` — o correto seria `task_rejected_review_required`.
- `diagnostics\v3_1_real_evidence.*`: veredito `A_CODEX_EXECUTOU_COM_SUCESSO` — o correto seria `EXECUCAO_OK_MAS_TAREFA_REJEITADA`.

Esses registros não bloqueiam reexecução (o estado antigo é `completed`); a revisão humana já foi feita nesta errata.
