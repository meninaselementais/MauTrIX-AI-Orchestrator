# 08 — V3: transferência entre agentes (PREPARADA, não habilitada para projetos reais)

Comando: `python tools\supervisor.py failover instructions\TASK-0003_failover_lab.json --confirm TASK-0003`
(`Executar_Failover_Lab.cmd`). Só em `lab\`, só `read_only`. `config\failover.json` mantém
`enabled_for_real_projects: false` e o código recusa qualquer outro valor.

## Estados de disponibilidade (`state\availability.json`)

| Estado | Como surge | Validade |
|---|---|---|
| AVAILABLE_VERIFIED | execução real bem-sucedida | TTL (padrão 900 s); depois volta a UNKNOWN |
| QUOTA_LIMITED | mensagem de limite de uso confirmada (padrão forte) | TTL (padrão 1800 s); depois UNKNOWN |
| AUTH_ERROR | agente não autenticado ou erro de autenticação | TTL 600 s |
| TECHNICAL_ERROR | erro técnico, timeout, resultado desconhecido, violação | TTL 600 s |
| BUSY | lock global ativo (derivado, não gravado) | enquanto o lock existir |
| UNKNOWN | sem registro, registro expirado, ou só autenticação confirmada | — |

Regras: autenticação confirmada **não** é prova de cota (continua UNKNOWN). AVAILABLE_VERIFIED não garante saldo para a
próxima tarefa. Nenhuma contagem de tokens nem horário de renovação é calculada; a dica impressa pelo agente (ex.: "try
again at 3:53 AM") é guardada só como texto informativo e não influencia decisões. Os TTLs são tempo de validade do
registro, não previsão de renovação.

## Política de seleção

1. Tarefa com `agent` fixo: só esse agente, sem transferência.
2. Tarefa com `agent: any_available`: ordem de `config\failover.json` (padrão `codex_cli`, depois `claude_code`).
3. Agentes desativados, QUOTA_LIMITED ou AUTH_ERROR ainda válidos são ignorados; UNKNOWN e AVAILABLE_VERIFIED são elegíveis.
4. Se nada for elegível, para (`stopped_no_agent`) sem iniciar processo algum.

## Regras de transferência

- Um único detentor dos locks (global + projeto) durante toda a cadeia. Lock existente = parar (`stopped_busy`); nunca remover.
- Cada agente executa no máximo uma vez por tarefa; sem repetição automática no mesmo agente.
- Transfere somente se: (limite de uso confirmado **ou** erro de autenticação) **e** sem saída aceita **e** sem alteração
  nos arquivos do laboratório **e** sem timeout; ou se a falha ocorreu antes de o agente iniciar.
- Erro técnico, 429/overloaded/rede, timeout, saída inválida, processo morto, violação: **para** (`stopped_unknown_result`).
  Esse registro bloqueia nova execução da mesma tarefa até revisão humana (mover o `TRANSFER-*` para `reports\resolved\`).
  O mesmo vale para uma transferência interrompida (`in_progress`).
- Contexto preservado em `handoffs\HANDOFF-<tarefa>-<n>.json` (tarefa, agente anterior, resultado, mensagem registrada,
  arquivos alterados, runs anteriores). O prompt do próximo agente recebe só um resumo neutro: parou por limite/autenticação,
  nada foi alterado, refazer do início. Mensagens brutas do agente anterior não entram no prompt.
- Registros: `reports\TRANSFER-*.json/.md`, `logs\transfers.log`, relatórios `RUN-*` de cada passo.

## Resultados dos testes

Ver a entrega da V3: 22 verificações com agentes simulados (`tests\test_v3_simulated.py`), mais os resultados reais da V2.
O formato de erro de limite do Claude no teste simulado é uma SUPOSIÇÃO (não observado); o do Codex replica a mensagem real.

## Limitações

Só laboratório; sem escrita; schema de resposta específico do laboratório; detecção de limite do Claude não observada em
campo; sem notificação ao coordenador; lock órfão exige remoção manual; testes simulados rodam em Linux/macOS.
