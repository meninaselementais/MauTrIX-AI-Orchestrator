#!/usr/bin/env python3
"""V3.1 - teste REAL controlado do failover, SOMENTE leitura, SOMENTE em lab\\projeto_descartavel.

Executa UMA vez o gerenciador de failover com TASK-0003, coleta evidências antes/depois e grava
diagnostics\\v3_1_real_evidence.json/.md. NÃO reexecuta nada, não provoca consumo de cota, não usa git/API paga.
Se o resultado for desconhecido, erro técnico, timeout, alteração de arquivos ou falha de isolamento: PARA e registra.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from mautrix_orq import availability  # noqa: E402
from mautrix_orq.common import LAB_ROOT, LOCKS, REPORTS, ROOT, load_agents, now_iso, snapshot, diff_snapshots, validate_task  # noqa: E402
from mautrix_orq.failover import run_with_failover  # noqa: E402

TASK = ROOT / "instructions" / "TASK-0003_failover_lab.json"
OUT = ROOT / "diagnostics"


def locks_now():
    return sorted(p.name for p in LOCKS.glob("*.lock")) if LOCKS.exists() else []


def main() -> int:
    problems, ev = [], {"started_at": now_iso(), "python": sys.version.split()[0]}
    task = json.loads(TASK.read_text(encoding="utf-8"))
    cfg = json.loads((ROOT / "config" / "failover.json").read_text(encoding="utf-8"))
    agents = load_agents()
    ev["preflight"] = {
        "mode": task["mode"], "agent": task["agent"], "project_path": task["project_path"],
        "validate_errors": validate_task(task, allow_any=True),
        "enabled_for_real_projects": cfg.get("enabled_for_real_projects"),
        "priority": cfg["priority"],
        "agents_enabled": {k: v.get("enabled") for k, v in agents.items()},
        "locks_before": locks_now(),
        "availability_before": availability.snapshot_all([a for a, s in agents.items() if s.get("enabled")]),
    }
    if ev["preflight"]["validate_errors"] or task["mode"] != "read_only" or cfg.get("enabled_for_real_projects"):
        problems.append("falha de pré-verificação: tarefa/configuração fora do escopo seguro")
    if ev["preflight"]["locks_before"]:
        problems.append("locks existentes antes do teste: " + ", ".join(ev["preflight"]["locks_before"]))
    if problems:
        ev["verdict"], ev["problems"] = "INTERROMPIDO_NA_PRE_VERIFICACAO", problems
        return finish(ev)
    before = snapshot(LAB_ROOT)
    ev["lab_before"] = {k: v[1] for k, v in before.items()}
    transfer = run_with_failover(TASK, "TASK-0003")
    after = snapshot(LAB_ROOT)
    created, modified, deleted = diff_snapshots(before, after)
    ev["lab_after"] = {k: v[1] for k, v in after.items()}
    ev["lab_diff"] = {"created": created, "modified": modified, "deleted": deleted}
    ev["locks_after"] = locks_now()
    ev["transfer"] = {k: transfer.get(k) for k in ("transfer_id", "state", "final_reason", "priority", "steps", "handoffs")}
    steps = [s for s in transfer.get("steps", []) if s.get("decision") != "skipped"]
    ev["agent_initially_chosen"] = steps[0]["agent"] if steps else None
    ev["agent_that_executed_successfully"] = next((s["agent"] for s in steps if s.get("decision") == "completed"), None)
    ev["transfer_reason"] = next((s.get("reason") for s in steps if s.get("decision") == "transferred"), None)
    runs = []
    for s in steps:
        if s.get("run_id"):
            rp = REPORTS / f"{s['run_id']}.json"
            if rp.exists():
                r = json.loads(rp.read_text(encoding="utf-8"))
                runs.append({k: r.get(k) for k in ("run_id", "agent", "agent_version", "outcome", "execution_result",
                                                   "task_verdict", "status", "exit_code", "side_effects", "limit",
                                                   "acceptance_result", "rejected_criteria", "errors")})
    ev["runs"] = runs
    state = transfer.get("state")
    if created or modified or deleted:
        problems.append("ARQUIVOS ALTERADOS NO LABORATÓRIO: " + json.dumps(ev["lab_diff"]))
    if ev["locks_after"]:
        problems.append("locks remanescentes: " + ", ".join(ev["locks_after"]))
    if state in ("completed", "completed_after_transfer") and not all(
            r.get("task_verdict") == "TASK_ACCEPTED" for r in runs if r.get("outcome") == "SUCCESS"):
        problems.append("inconsistência: estado concluído sem TASK_ACCEPTED")
        ev["verdict"] = "INCONSISTENTE"
    elif state == "completed" and ev["agent_that_executed_successfully"] == "codex_cli":
        ev["verdict"] = "A_CODEX_EXECUTOU_COM_SUCESSO"
    elif state == "completed_after_transfer" and ev["agent_that_executed_successfully"] == "claude_code" \
            and ev["agent_initially_chosen"] == "codex_cli":
        ev["verdict"] = "B_LIMITE_CONFIRMADO_E_TRANSFERIDO_AO_CLAUDE"
    elif state == "completed":
        ev["verdict"] = f"CONCLUIDO_POR_{(ev['agent_that_executed_successfully'] or '?').upper()}_SEM_TRANSFERENCIA"
    elif state in ("task_rejected_review_required", "task_unverified_review_required"):
        # sucesso técnico da execução NÃO é aprovação da tarefa
        ev["verdict"] = "EXECUCAO_OK_MAS_TAREFA_REJEITADA" if state.startswith("task_rejected") \
            else "EXECUCAO_OK_MAS_TAREFA_NAO_VERIFICADA"
        problems.append(f"{state}: {transfer.get('final_reason')}")
    else:
        ev["verdict"] = "INTERROMPIDO"
        problems.append(f"estado final {state}: {transfer.get('final_reason')}")
    if problems and not ev["verdict"].startswith(("INTERROMPIDO", "EXECUCAO_OK", "INCONSISTENTE")):
        ev["verdict"] += "_COM_PROBLEMAS"
    ev["problems"] = problems
    return finish(ev)


def finish(ev) -> int:
    ev["finished_at"] = now_iso()
    OUT.mkdir(exist_ok=True)
    (OUT / "v3_1_real_evidence.json").write_text(json.dumps(ev, indent=2, ensure_ascii=False), encoding="utf-8")
    md = ["# Evidências V3.1 - teste real controlado", "", f"Veredito: **{ev['verdict']}**", ""]
    for k in ("agent_initially_chosen", "agent_that_executed_successfully", "transfer_reason"):
        md.append(f"- {k}: {ev.get(k)}")
    md.append(f"- locks antes: {ev['preflight']['locks_before']}  depois: {ev.get('locks_after')}")
    md.append(f"- diferença no laboratório: {ev.get('lab_diff')}")
    for r in ev.get("runs", []):
        md.append(f"- {r['run_id']}: {r['agent']} outcome={r['outcome']} exit={r['exit_code']} efeitos={r['side_effects']} "
                  f"execução={r.get('execution_result')} tarefa={r.get('task_verdict')} "
                  f"critérios={[a['met'] for a in r['acceptance_result']]}")
    md += ["", "Problemas: " + (", ".join(ev["problems"]) if ev.get("problems") else "nenhum"), ""]
    (OUT / "v3_1_real_evidence.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0 if ev["verdict"].startswith(("A_", "B_")) and not ev.get("problems") else 1


if __name__ == "__main__":
    sys.exit(main())
