# 09 — Validação da V3 no Windows (V3.1) e correção da V3.2

Data: 05/11/2026. Python 3.11.9 (Windows). Escopo: somente `lab\projeto_descartavel`, somente leitura.
Real = executado com agente de verdade. Simulado = agentes falsos (`tests\fakes\fake_agent.py`).

## 1. Execuções reais registradas

| Fonte | Agente | Resultado real |
|---|---|---|
| V2 `RUN-…031328042` e `…031425392` | Claude Code 2.1.302 | exit 0, 3/3 critérios (line_count 12) |
| V2 `RUN-…031345590` | Codex 0.166.0 | limite de uso confirmado (mensagem real), exit 1 |
| V2 `RUN-…031336113` | Codex 0.166.0 | bloqueio por lock, agente não iniciado |
| **V3.1 `RUN-20261105_154231375-TASK-0003-codex_cli`** | Codex 0.166.0 | exit 0, JSON válido, **critérios yes/yes/no**, `line_count` 0 contra 12 |

A execução da V3.1 foi classificada pela versão anterior como `completed_with_issues`, e o script de evidências deu
o veredito `A_CODEX_EXECUTOU_COM_SUCESSO` e o gerenciador gravou `TRANSFER-…154231373` como `completed`. **Isso estava errado.**

## 2. Causa da divergência (com evidências)

| Hipótese | Conclusão | Evidência |
|---|---|---|
| Arquivo / interpretação do arquivo | descartada | `texto_exemplo.txt` tem 12 linhas não vazias (contagem independente do orquestrador, igual à do Claude nas duas execuções da V2) |
| Contagem do Codex | **não houve contagem** | `stdout_1.txt`: o Codex disse "não há ferramenta de leitura de texto disponível que respeite a proibição de executar comandos"; nenhum evento de comando no JSONL; `line_count: 0` e `word_count: 0` como "marcadores de indisponibilidade" |
| Prompt | **causa raiz** | o prompt da V2 dizia a todos os agentes "Não execute comandos". O Claude lê pelas ferramentas Read/Glob/Grep; o Codex só lê arquivos por shell. O Codex obedeceu à proibição e não leu o arquivo |
| Schema | contribuinte | aceita qualquer inteiro, inclusive 0 como placeholder; um JSON válido com dados falsos passa pelo schema |
| Validador | **correto** | reprovou o terceiro critério (`met: no`) |
| Classificação | **defeito** | `outcome: SUCCESS` valia como "sucesso"; `completed_with_issues` não era tratado como reprovação; o gerenciador gravou `completed`; o script de evidências olhava só o estado e deu veredito A com "Problemas: nenhum" |

## 3. Correção (V3.2)

Separação explícita em três níveis, gravada em cada relatório:
- `execution_result`: `EXECUTION_SUCCESS` quando o processo executou e devolveu resultado estruturado sem efeitos colaterais.
- `task_verdict`: `TASK_ACCEPTED` (todos os critérios atendidos), `TASK_REJECTED` (algum critério falhou), `TASK_UNVERIFIED` (algum critério não verificável) ou `NOT_EVALUATED`.
- `status`: `completed` **somente** com `TASK_ACCEPTED`; senão `task_rejected` / `task_unverified`.

Mudanças:
- **Failover:** execução com `TASK_REJECTED` não transfere, não é tratada como cota, não vira `completed`. O estado vira `task_rejected_review_required` e bloqueia nova execução da mesma tarefa até revisão humana. O resultado fica preservado.
- **Disponibilidade:** `AVAILABLE_VERIFIED` só com `TASK_ACCEPTED`. Registros `AVAILABLE_VERIFIED` anteriores à V3.2 são ignorados (voltam a UNKNOWN).
- **Evidências:** o veredito A/B exige `TASK_ACCEPTED`; rejeição produz `EXECUCAO_OK_MAS_TAREFA_REJEITADA` e código de saída 1.
- **Prompt:** regra de leitura por agente. Claude usa Read/Glob/Grep. Codex pode usar shell **somente para ler** (o sandbox continua `read-only`, nada de permissão foi aberto). Se não conseguir ler: `line_count = -1`, sem inventar números.
- O arquivo de exemplo **não** foi alterado, e o critério de aprovação não foi relaxado.

Registros históricos preservados sem edição. Errata em `reports\ERRATA_V3_2.md`.

## 4. Testes

**Simulados no Windows (V3.1, Python 3.11.9): 22 de 22 passaram**, dos testes A a K2, com `diagnostics\v3_1_simulados.json`. Os dois processos de teste "travados" (timeout) estavam encerrados ao fim.

**Simulados no Linux (V3.2, Python 3.13): 35 de 35 passaram.** Os 22 anteriores mais 13 novos.
- Exit 0 com todos os critérios aprovados.
- Exit 0 com um critério reprovado.
- JSON válido com dados incorretos (zeros, reproduzindo a resposta real).
- Resposta ausente.
- `run` direto com critério reprovado.
- Três veredictos do script de evidências (A, B e tarefa rejeitada).
- Registro antigo ignorado.
- Os cenários de limite real, erro técnico, transferência e preservação de arquivos seguem nos 22 originais.

**Pendente:** reexecutar os 35 no Windows (`Validar_V3_Windows.cmd`, passo 1). Reproduzi offline o veredito sobre os critérios reais da V3.1: `TASK_REJECTED`.

## 5. Diferenças Linux × Windows
- Agentes falsos: atalhos `.cmd` com `MX_PY` no Windows; scripts com shebang no Linux.
- Separador de PATH, encerramento de processo (`taskkill /T /F` × `kill`) e checagem de PID (`tasklist` × `os.kill(pid,0)`) são específicos de plataforma.
- Nenhuma diferença de resultado nos 22 testes comuns.
- O `Validar_V3_Windows.cmd` original encerrou antes do passo 3 (causa não provada); o `Executar_V3_Real.cmd` o substituiu e funcionou.

## 6. Limitações
Detecção de limite do Claude ainda não observada em campo. O prompt revisado do Codex não foi testado com o Codex real. O critério de linhas é específico do laboratório. Locks órfãos exigem remoção manual. Cota restante: STATUS DESCONHECIDO.

## 7. Recomendação
**Não liberar a V3 ainda.** A classificação foi corrigida e coberta por testes simulados, mas faltam (a) os 35 testes no Windows e (b) uma nova execução real do Codex com o prompt corrigido, que precisa terminar em `TASK_ACCEPTED` (ou em limite confirmado com transferência aprovada pelo Claude). Sem forçar consumo de cota. Projetos reais continuam desabilitados.


---

## 8. V3.3 — Diagnóstico final do sandbox do Codex

**Causa identificada (evidência × hipótese).**
- *Comprovado localmente:* nas execuções reais do Codex (0.166.0, Windows) o `exec_command` do próprio Codex falha com `CreateProcess Rejected … blocked by policy`, até para `Get-Content` simples. Isso é bloqueio de política do shell do agente, não erro de codificação: o canal Python↔agente é UTF-8 (`stdout_1.txt` com acentos corretos) e o `codex sandbox ... Get-Content` feito pelo usuário leu o arquivo.
- *Mojibake visto pelo usuário:* é do Windows PowerShell 5.1, que lê UTF-8 sem BOM como ANSI; resolve com `Get-Content -Encoding UTF8`. É independente do bloqueio e não afeta a contagem de linhas.
- *Não comprovado:* a causa interna do bloqueio. Relatos da comunidade (openai/codex #59314, #23965, xezar #1009) descrevem o mesmo sintoma na 0.166.0 no Windows, também com `--ignore-user-config`; não há confirmação oficial. `--ignore-user-config` não foi provado como causa.
- `codex sandbox` e `codex exec` usam caminhos de código diferentes; por isso um funciona e o outro não.

**Correções (somente no adaptador Codex e na classificação; sandbox continua `read-only`).**
1. `context_delivery: "embedded"` (opcional, padrão `agent_reads`): o orquestrador lê os arquivos de contexto em UTF-8 estrito, limite de 64 KiB, e os entrega no prompt como DADOS entre `<<<ARQUIVO … [sha]>>>`. O Codex não precisa de shell.
2. `exec_extra_args` (opcional): lista permitida com `[]` ou `-c windows.sandbox="unelevated"`. Qualquer outro valor é recusado. Isso não afrouxa o sandbox.
3. Classificação separada: política (`diagnosis.kind = policy`), codificação (`encoding`), cota, autenticação e transitório. Arquivo de contexto que não é UTF-8 falha ANTES de iniciar o agente (`failure_kind = input_encoding`) e não transfere.
4. Relatório sempre traz `diagnosis`; TASK_REJECTED indica a causa provável.
5. Defeito achado pelos testes e corrigido: um comentário engolia as entradas `BUSY` e `POLICY_REJECTED` de `STATUS_BY_OUTCOME`; comando recusado pela política causava `KeyError`.

**Testes.** Simulados, Linux, Python 3.13: **45 de 45** (35 anteriores + R1 a R8: bloqueio de política, erro de codificação, saída correta com entrega embutida, prompt embutido e read-only, arquivos preservados, classificação, arquivo não-UTF-8, extras permitidos/recusados). **Não houve execução real de Claude ou Codex na V3.3.** Pendente: rodar os 45 no Windows.

**Limitação.** Com `agent_reads`, o Codex 0.166.0 no Windows não consegue ler arquivos por conta própria. Para projetos reais isso continua sendo impedimento até correção do Codex ou atualização de versão; `embedded` só serve a arquivos pequenos em UTF-8.

## 9. Procedimento mínimo para UMA revalidação real do Codex (aguarda autorização)
1. Rodar `Validar_V3_Windows.cmd`, passo 1 (45 testes simulados).
2. Em `config\agents.json`, bloco `codex_cli`: `"context_delivery": "embedded"`. Opcional, só se a primeira tentativa ainda falhar por política: `"exec_extra_args": ["-c", "windows.sandbox=\"unelevated\""]`.
3. `Executar_V3_Real.cmd`, digitar SIM. Uma única execução, TASK-0003, apenas o laboratório.
4. Esperado: `TASK_ACCEPTED` com `line_count = 12`. Se vier `TASK_REJECTED`, ver `diagnosis` no relatório; não repetir automaticamente.


## 10. Resultado real da TASK-0004 e encerramento da V3.3

**Execução real (única, 2026-11-05 17:26, Codex 0.166.0, `context_delivery: "embedded"`, sandbox `read-only`):** `RUN-20261105_172601117-TASK-0004-codex_cli`. EXECUTION_SUCCESS, TASK_ACCEPTED, status `completed`, exit 0, 14,8 s, `line_count = 12`, `word_count = 114`, JSON válido, três critérios aprovados, nenhum arquivo do laboratório alterado, locks vazios, histórico (TASK-0003 e demais) preservado. Veredito `VALIDACAO_APROVADA`. Evidência: `diagnostics/task0004_evidence.json/.md` (classe: executada pelo agente e verificada pelo orquestrador; leitura feita nesta etapa, sem nova execução).

**O que isso comprova:** o bloqueio anterior era do shell do Codex, não do orquestrador; entregar o conteúdo no prompt contorna o problema sem afrouxar o sandbox. **O que não comprova:** causa interna do bloqueio, nem acesso autônomo.

**Limitação registrada.** O modo `embedded` funciona para arquivos pequenos (≤ 64 KiB, UTF-8), escolhidos antecipadamente pelo orquestrador. Ele **não substitui o acesso autônomo do agente ao projeto**: o Codex continua sem conseguir listar, buscar ou ler arquivos por conta própria nesta versão/ambiente, porque o shell dele segue bloqueado por política. Projetos reais, que exigem navegação e leitura dirigida pelo agente, continuam fora do escopo para o Codex.

**Defeito encontrado e corrigido (campo `agent_started`).** Ver `errata/ERRATA_V3_3.md` (no projeto: `reports\ERRATA_V3_3.md`). Defeito do script `validar_task0004.py`; relatório do executor estava correto (`true`). Regressão S3c; relatórios históricos não editados.

**Outra observação (não é defeito).** `reports\TRANSFER-20261105_172526021-TASK-0003.json` (estado `rejected`, sem passos) é a recusa correta de uma nova tentativa de TASK-0003 pelo bloqueio `task_rejected_review_required`; nenhum agente iniciou.

**Testes simulados (Linux, Python 3.13, agentes falsos): 54 de 54.** (35 da V3.2 + R1–R8 + S1–S7 + S3c.) Nenhum teste real de Claude ou Codex foi feito nesta etapa. **Pendente: executar no Windows (ver seção 11; a primeira execução deu 52/54).**

**Procedimento para os testes no Windows (sem agentes reais, sem cota):**
1. Abrir `C:\Projetos\MauTrIX-AI-Orchestrator` e executar `Testes_Simulados_Windows.cmd` (a janela fica aberta).
2. Conferir `diagnostics\v3_3_simulados.txt`: linha "55/55 verificações passaram", código de saída 0, "Processos fake_agent restantes: nenhum".
3. Se algo falhar, não executar tarefas reais; enviar o arquivo `diagnostics\v3_3_simulados.txt`.
Não usar `Validar_V3_Windows.cmd` para isso: o passo 3 dele executa agentes reais.

**Recomendação.** V3.3 pode ser encerrada no escopo de laboratório, condicionada aos testes simulados passarem no Windows (ver seção 11: agora 55). Não habilita projetos reais, `enabled_for_real_projects` permanece `false`, e V4 não foi iniciada.


## 11. Regressões no Windows (52/54) — causa e correção
Primeira execução no Windows (Python 3.11.9): **52 de 54**; falharam **R3** e **S3**; aviso de PID 34696. Detalhes e causa comprovada em `reports\ERRATA_V3_3.md` (errata 2).
- **Causa:** o agente simulado procurava `\n` no prompt, mas no Windows o prompt chega com `\r\n`; o fake emitia "blocked by policy" simulado e `line_count = -1`; o orquestrador classificou corretamente. Defeito só do `tests/fakes/fake_agent.py`; proteções e critérios inalterados; Codex real não afetado.
- **Correção:** normalização de CRLF no fake + teste de regressão R3c (reprova sem a correção; verificado por mutação). Suíte no Linux: **55 de 55**.
- **PID 34696:** os agentes `hang` desta execução (PIDs 3168 e 35516) já estavam encerrados; 34696 é provavelmente o próprio PowerShell da checagem final (autocorrespondência no filtro). Não confirmado por falta de terminal; nada foi encerrado. Checagem corrigida no `.cmd`.
- **Status:** a V3.3 só pode ser encerrada quando o Windows reportar **55/55, código 0, nenhum fake_agent restante** (`diagnostics\v3_3_simulados.txt`).
