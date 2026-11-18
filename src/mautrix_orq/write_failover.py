"""Transferência entre agentes em tarefas de ESCRITA (V4).

Regras (mais estritas que na leitura):
- Só transfere se o agente parou por limite/autenticação confirmados (ou falhou antes de iniciar) E o workspace dele
  NÃO tem nenhuma alteração. Se o agente já alterou arquivos, PARA e exige revisão humana ('changes_present_review_required').
- Violação de escopo ou do repositório real: PARA ('violation_review_required').
- Antes de cada passo a impressão digital do repositório real é conferida: se mudou entre passos (algo desconhecido
  alterou arquivos), o passo seguinte é recusado. Um segundo agente nunca sobrescreve alterações desconhecidas.
- Nada é promovido a partir de um agente que não terminou com TASK_ACCEPTED.
"""
import json
import time
from pathlib import Path

from . import availability, outcomes as oc
from .common import LAB_GIT, REPORTS, load_agents, now_iso
from .failover import _blocking_record, _handoff, _tlog, _write_transfer
from .locks import LockError, RunLocks
from .write_executor import STRATEGIES, current_fingerprint, execute_write
from . import writescope as ws


def run_write_with_failover(task_path: Path, confirm: str) -> dict:
    rec = {"schema_version": 1, "transfer_id": None, "task_id": "TASK-0000", "state": "in_progress",
           "started_at": now_iso(), "finished_at": None, "priority": [], "availability_at_start": {}, "steps": [],
           "final_reason": None, "final_outcome": None, "handoffs": [], "mode": "write_scoped"}
    try:
        task = json.loads(Path(task_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        rec.update(state="rejected", final_reason=f"tarefa ilegível: {exc}")
        return rec
    errors = ws.validate_write_task(task, allow_any=True)
    rec["task_id"] = task.get("task_id", "TASK-0000")
    if errors:
        rec.update(state="rejected", final_reason="; ".join(errors))
        return rec
    if confirm != task["task_id"]:
        rec.update(state="rejected", final_reason="falta --confirm igual ao task_id")
        return rec
    cfg = availability.load_failover_config()
    if cfg.get("enabled_for_real_projects"):
        rec.update(state="rejected", final_reason="enabled_for_real_projects deve permanecer false")
        return rec
    agents = load_agents()
    priority = [task["agent"]] if task["agent"] != "any_available" else list(cfg.get("write_priority") or cfg["priority"])
    rec["priority"] = priority
    rec["availability_at_start"] = availability.snapshot_all(priority)
    tid = f"{time.strftime('%Y%m%d_%H%M%S')}{int(time.time() * 1000) % 1000:03d}-{task['task_id']}"
    rec["transfer_id"] = f"TRANSFER-{tid}"
    tpath = REPORTS / f"{rec['transfer_id']}.json"
    project = LAB_GIT.resolve()
    try:
        locks = RunLocks(project, task["task_id"], "write_failover_manager", 3600)
        locks.__enter__()
    except LockError as exc:
        rec.update(state="stopped_busy", final_reason=f"BUSY: {exc}")
        _write_transfer(tpath, rec)
        return rec
    try:
        blocking = _blocking_record(task["task_id"])
        if blocking:
            rec.update(state="rejected", final_reason=f"registro anterior bloqueia nova execução ({blocking}): revisar "
                       "manualmente e mover o registro para reports\\resolved\\")
            _write_transfer(tpath, rec)
            return rec
        try:
            fp = current_fingerprint(project)
        except Exception as exc:  # noqa: BLE001
            rec.update(state="rejected", final_reason=f"não foi possível ler o repositório do laboratório: {exc}")
            _write_transfer(tpath, rec)
            return rec
        _write_transfer(tpath, rec)
        eligible, skipped = availability.select(priority, agents)
        for agent, why in skipped:
            rec["steps"].append({"n": len(rec["steps"]) + 1, "agent": agent, "decision": "skipped", "reason": why})
        handoff_text, last = None, None
        for agent in eligible:
            step = {"n": len(rec["steps"]) + 1, "agent": agent, "decision": "running", "run_id": None}
            rec["steps"].append(step)
            _write_transfer(tpath, rec)
            task_i = {**task, "agent": agent, "limits": {**task["limits"], "max_attempts": 1}}
            report = execute_write(task=task_i, confirm=confirm, handoff=handoff_text, held_locks=True, expect_fingerprint=fp)
            last = report
            W = report.get("write") or {}
            step.update(run_id=report["run_id"], outcome=report["outcome"], status=report["status"])
            _tlog({"transfer": rec["transfer_id"], "agent": agent, "outcome": report["outcome"], "mode": "write"})
            if report["outcome"] == oc.SUCCESS and report.get("task_verdict") == oc.TASK_ACCEPTED and W.get("promoted"):
                step.update(decision="completed", reason="tarefa aprovada e promovida")
                moved = any(x["decision"] == "transferred" for x in rec["steps"])
                rec.update(state="completed_after_transfer" if moved else "completed", final_reason="tarefa concluída",
                           final_outcome=oc.SUCCESS)
                break
            if report["outcome"] == oc.SUCCESS:
                rejected = report.get("task_verdict") == oc.TASK_REJECTED
                why = ("critérios não atendidos: " + "; ".join(report.get("rejected_criteria", []))) if rejected \
                    else "critérios não verificáveis"
                step.update(decision="review_required", reason=why)
                rec.update(state="task_rejected_review_required" if rejected else "task_unverified_review_required",
                           final_reason=why, final_outcome=report.get("task_verdict"))
                break
            if report["outcome"] == oc.VIOLATION:
                why = "violação: " + "; ".join(f"{v['kind']}:{v['path']}" for v in W.get("violations", []))[:300]
                step.update(decision="stopped", reason=why)
                rec.update(state="violation_review_required", final_reason=why, final_outcome=oc.VIOLATION)
                break
            if W.get("workspace_changed"):
                why = "o agente já alterou arquivos (no workspace); transferir poderia perder ou duplicar trabalho"
                step.update(decision="stopped", reason=why)
                rec.update(state="changes_present_review_required", final_reason=why, final_outcome=report["outcome"])
                break
            ok, why = oc.can_transfer(report)
            if not ok:
                step.update(decision="stopped", reason=why)
                rec.update(state="stopped_unknown_result", final_reason=why, final_outcome=report["outcome"])
                break
            hpath, handoff_text = _handoff(task, rec["steps"], report, why, len(rec["handoffs"]) + 1)
            rec["handoffs"].append(str(hpath.name))
            step.update(decision="transferred", reason=why)
            _write_transfer(tpath, rec)
        else:
            rec.update(state="stopped_no_agent",
                       final_reason="nenhum agente elegível" if last is None else
                       "todos os agentes elegíveis pararam por limite/autenticação",
                       final_outcome=last["outcome"] if last else None)
        rec["finished_at"] = now_iso()
        _write_transfer(tpath, rec)
        _tlog({"transfer": rec["transfer_id"], "state": rec["state"], "mode": "write"})
        return rec
    finally:
        locks.release()
