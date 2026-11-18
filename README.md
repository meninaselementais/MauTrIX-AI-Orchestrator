# MauTrIX AI Orchestrator — V1

Orquestrador local, gratuito, para o Windows, que coordena três agentes de programação (Claude Code, OpenAI Codex CLI, Google Antigravity) com um coordenador GPT **supervisionado por humano**.

**Estado da V1:** estrutura, diagnóstico dos agentes, arquitetura de adaptadores, protocolo de contexto, limitações e plano de versões. **Nenhum agente é executado automaticamente. Nenhum serviço permanente.**

## Como rodar o diagnóstico (somente leitura)

Dê dois cliques em `Executar_Diagnostico.cmd` ou rode `python tools\diagnose.py`. Resultado em `diagnostics\ultimo.json` e `diagnostics\ultimo.md`.

O diagnóstico procura os executáveis no PATH, roda `--version` e `--help` (20 s de limite, sem entrada), roda o comando de status de autenticação só quando está listado em `config\agents.json` e **não lê tokens, cookies nem arquivos de autenticação**. O Antigravity IDE (interface gráfica) é apenas localizado, não executado.

## Estrutura

| Pasta/arquivo | Conteúdo |
|---|---|
| `config/agents.json` | Definição dos adaptadores, com o nível de confirmação de cada afirmação |
| `schemas/` | `task.schema.json` (instrução) e `report.schema.json` (relatório) |
| `tools/diagnose.py` | Diagnóstico somente leitura |
| `docs/01_ARQUITETURA.md` | Adaptadores, ciclo de vida da tarefa, exclusão mútua |
| `docs/02_PROTOCOLO_CONTEXTO.md` | Fluxo GPT → agente → relatório → GPT |
| `docs/03_LIMITACOES.md` | O que foi e o que não foi confirmado |
| `docs/04_PLANO_VERSOES.md` | V1.1 a V6 |
| `docs/05_SEGURANCA.md` | Regras obrigatórias |
| `instructions/`, `reports/`, `runs/`, `logs/`, `locks/`, `diagnostics/` | Dados de trabalho (vazios na V1) |

## Regras que valem sempre

Sem commit, push, merge ou tag automáticos. Nunca `git reset --hard` nem `git clean`. Um escritor por projeto. Cota desconhecida aparece como **STATUS DESCONHECIDO**. Nada neste projeto altera `C:\Projetos\CS-Puzzle-Fighter-96`.
