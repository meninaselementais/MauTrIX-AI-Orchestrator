# Errata V3.3 — `agent_started: false` na evidência da TASK-0004

Data: 2026-11-05. Os relatórios históricos NÃO foram editados; esta errata os qualifica.

**Arquivo afetado:** `diagnostics/task0004_evidence.json` (e `.md`), gerado por `tools/validar_task0004.py` na execução real de TASK-0004.

**Sintoma:** campo de topo `"agent_started": false`, embora a execução real tenha ocorrido (veredito `VALIDACAO_APROVADA`).

**Causa (confirmada):** defeito do script de validação, não do executor. `cmd_run` gravava `agent_started = False` na evidência ANTES de chamar `execute()` e nunca o atualizava. O relatório do executor `reports/RUN-20261105_172601117-TASK-0004-codex_cli.json` traz `"agent_started": true`, `attempts[0].exit_code = 0`, `seconds = 14.8`, evidência `executed_by_agent` — a fonte correta.

**Impacto:** apenas informativo no arquivo de evidência. Nenhum critério de aceitação, veredito, bloqueio ou decisão de transferência usa esse campo da evidência. Execução, `TASK_ACCEPTED`, `line_count = 12`, laboratório, locks e histórico não foram afetados.

**Correção:** o script passa a copiar `agent_started` do relatório do executor (e inclui `run.agent_started`), e há um novo critério `agent_started consistente com a execução`. Regressão: teste S3c (falha se o campo voltar a ser `false` após execução). Verificado por mutação: com a correção removida, S3 e S3c reprovam.

**Registro histórico não modificado:** para a execução real de 2026-11-05 17:26 vale `agent_started = true` conforme o relatório do executor.

---

# Errata V3.3 (2) — falhas R3 e S3 nos testes simulados no Windows (52/54)

Data: 2026-11-05 17:34. Python 3.11.9, Windows. Evidência: `diagnostics/v3_3_simulados.txt/.json`.

**Falhas:** R3 e S3 (`TASK_REJECTED`, `diagnosis.kind = policy`, critério `line_count`); o mesmo código passava no Linux (54/54).

**Causa (comprovada):** defeito do AGENTE SIMULADO, não do orquestrador nem das proteções.
- No Windows o executor entrega o prompt por stdin em modo texto e grava `prompt.txt` com `\r\n` (Python traduz `\n` → `\r\n`). Evidência: `runs/RUN-20261105_172601117-TASK-0004-codex_cli/prompt.txt` tem 62 `\r\n` em 62 quebras de linha; `texto_exemplo.txt` tem só `\n` (12), logo a conversão acontece na entrega.
- O `fake_agent.py` procurava o bloco `<<<ARQUIVO … [sha]>>>\n(...)\n<<<FIM` com `\n` literal. Com `\r\n` a busca falha e o agente falso cai no ramo "sem shell", imprimindo a mensagem de política e devolvendo `line_count = -1`. O orquestrador reagiu corretamente: `TASK_REJECTED` + `policy`.
- Explicação da mensagem "blocked by policy" nesses dois testes: é a mensagem simulada do próprio fake, não um bloqueio real.
- Estado persistente/histórico: descartado. Cada execução usa cópia temporária do projeto com `reports/runs/logs/locks/state` recriados.
- O Codex real NÃO foi afetado: recebeu o prompt com CRLF e concluiu a TASK-0004 (line_count 12).

**Correção:** `tests/fakes/fake_agent.py` normaliza `\r+\n` → `\n` ao ler o prompt. Critérios, proteções e `texto_exemplo.txt` intactos. Regressão R3c: alimenta o fake com o prompt convertido para CRLF (reproduz a condição do Windows em qualquer SO); sem a correção R3c reprova (verificado por mutação).

**PID 34696:** não pertence às execuções `hang` desta suíte. O JSON registra os PIDs dos agentes travados desta execução: 3168 e 35516, ambos `alive_at_end: false` (e H2 passou). O 34696 é compatível com o próprio PowerShell da verificação final, cuja linha de comando contém o texto `fake_agent.py` buscado (autocorrespondência) — hipótese, NÃO confirmada: não havia terminal no Windows nesta etapa para consultá-lo, e nenhum processo foi encerrado. Correção da verificação em `Testes_Simulados_Windows.cmd`: ignora o próprio PowerShell, evita autocorrespondência e lista PID, pai e linha de comando de qualquer sobra.

---

# Errata V4 — suíte V4 no Windows: "34/34" e código 1 (esperado 56/56)

Data: 2026-11-05 19:22. Evidência: `diagnostics/v4_simulados.txt`.

**O que aconteceu:** a suíte V4 executou 34 verificações (todas PASS), depois terminou com exceção e código 1. O "34/34" era a contagem parcial impressa no bloco `finally`, não uma aprovação.

**Causa (comprovada pelo traceback):** `PermissionError [WinError 5]` em `tests/test_v4_write.py`, linha 267 (`shutil.rmtree(LAB / ".git")`, cenário P4 "pasta sem repositório Git"). No Windows os objetos do Git (`.git\\objects\\xx\\…`) são somente leitura e `shutil.rmtree` simples não os apaga. Defeito do TESTE, não do orquestrador. O caminho atingido era `%TEMP%\\mxv4_…\\root\\lab\\git_lab\\.git` — a cópia temporária descartável, **não** o `lab\\git_lab` real. O laboratório real, o commit-base e o `reports\\GITLAB_BASELINE.*` não foram tocados (HEAD dos dry-runs = HEAD do baseline).

**Divergência 34 × 56:** a suíte implementa 56 verificações; 34 vieram antes do P4 (a 35ª). As outras 22 (P4, K, K2, K3, K4, S1, S2, V1–V8, Z etc.) não chegaram a executar. Nada foi reduzido ou removido.
Também faltou proteção contra aprovação parcial: uma suíte interrompida imprimia "N/N passaram".

**Correções (só no teste e no atalho):**
1. P4 e a limpeza entre cenários usam `rmtree_force` (remove o atributo somente leitura antes de apagar), a mesma função já usada para o laboratório temporário.
2. A suíte passa a ter `EXPECTED_CHECKS = 56`; exceção ou contagem diferente imprime `SUITE INCOMPLETA: executadas X de 56`, grava `crashed/executed/expected` no JSON e sai com código 1. Verificado por mutação: forçando uma exceção na posição do P4, o resultado volta a ser "34 de 56 — INCOMPLETA", código 1.
3. `Testes_V4_Windows.cmd` também destaca `INCOMPLETA` e `Traceback` no resumo.

**Dry-runs e laboratório (conferidos):** TASK-1001 e TASK-1002 `completed` (dry-run), `git_before` limpo, branch `main`, HEAD `21de4b9…`, único não rastreado `rascunho_local.txt`; `cache_local.tmp` ignorado e presente. Comandos corretos: Claude `--restricted`, `--tools`, `Edit(./notas.txt)`, sem Bash permitido; Codex `--sandbox read-only`, schema de proposta.
