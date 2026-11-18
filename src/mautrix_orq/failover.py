"""Gerenciador de transferência entre agentes (V3).

Regras:
- Só tarefas autorizadas (--confirm), read_only, dentro de lab/. Nada de projetos reais.
- Um único detentor de locks durante TODA a cadeia (sem janela para execução simultânea).
- Cada agente executa no máximo UMA vez por tarefa; nenhuma repetição automática no mesmo agente.
- Transferir só quando oc.can_transfer() afirma que é seguro: limite de uso confirmado ou erro de
  autenticação, sem saída aceita e sem alterações; ou falha antes de o agente iniciar.
- Erro técnico, timeout, resultado desconhecido, violação: PARAR e exigir revisão humana. O registro
  da transferência fica 'stopped_unknown_result' e bloqueia nova execução da mesma tarefa até revisão.
- Se não houver agente elegível: parar.
"""
import json
import time
from pathlib import Path

from . import availability, outcomes as oc
from .common import HANDOFFS, LAB_ROOT, LOGS, REPORTS, load_agents, now_iso, snapshot, validate_task
from .executor import execute
from .locks import LockError, RunLocks

BLOCKING_STATES = ("in_progress", "stopped_unknown_result", "task_rejected_review_required",
                   "task_unverified_review_required", "violation_review_required", "changes_present_review_required")


def _tlog(event: dict) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOGS / "transfers.log", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": now_iso(), **event}, ensure_ascii=False) + "\n")


def _blocking_record(task_id: str):
    for path in sorted(REPORTS.glob(f"TRANSFER-*-{task_id}.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return path.name
        if rec.get("state") in BLOCKING_STATES:
            return path.name
    return None


def _write_transfer(path: Path, rec: dict) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
    md = [f"# Transferência {rec['transfer_id']}", "",
          f"- Tarefa: {rec['task_id']}  Estado: **{rec['state']}**  Motivo final: {rec.get('final_reason')}",
          f"- Prioridade configurada: {rec['priority']}",
          f"- Início: {rec['started_at']}  Fim: {rec.get('finished_at')}", "", "## Passos"]
    for s in rec["steps"]:
        md.append(f"- {s['n']}. {s['agent']} → {s.get('decision')} | resultado: {s.get('outcome')} | "
                  f"run: {s.get('run_id')} | {s.get('reason')}")
    md += ["", "## Disponibilidade no início", "```json", json.dumps(rec["availability_at_start"], indent=2,
                                                                  ensure_ascii=False), "```", ""]
    path.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")


def _handoff(task: dict, steps: list, report: dict, reason: str, n: int) -> tuple:
    """Preserva o contexto em disco e devolve (caminho, texto curto para o prompt do próximo agente)."""
    HANDOFFS.mkdir(parents=True, exist_ok=True)
    path = HANDOFFS / f"HANDOFF-{task['task_id']}-{n}.json"
    path.write_text(json.dumps({
        "task": task, "from_agent": report["agent"], "outcome": report["outcome"], "reason": reason,
        "limit": report.get("limit"), "limits_hit": report.get("limits_hit"),
        "files_created": report["files_created"], "files_changed": report["files_changed"],
        "files_deleted": report["files_deleted"], "previous_run_id": report["run_id"],
        "previous_runs": [s.get("run_id") for s in steps], "created_at": now_iso(),
        "partial_output_accepted": False}, indent=2, ensure_ascii=False), encoding="utf-8")
    why = {oc.QUOTA_LIMITED: "limite de uso", oc.AUTH_ERROR: "erro de autenticação"}.get(report["outcome"],
                                                                                        "falha antes de iniciar")
    text = (f"CONTEXTO DE TRANSFERÊNCIA: esta tarefa foi iniciada pelo agente {report['agent']}, que parou por "
            f"{why}. Nenhum arquivo do laboratório foi alterado (verificado por SHA-256) e nenhum resultado parcial "
            f"foi aceito. Refaça a tarefa do início, sem presumir nada do agente anterior.")
    return path, text


def run_with_failover(task_path: Path, confirm: str) -> dict:
    now = now_iso()
    rec = {"schema_version": 1, "transfer_id": None, "task_id": "TASK-0000", "state": "in_progress",
           "started_at": now, "finished_at": None, "priority": [], "availability_at_start": {}, "steps": [],
           "final_reason": None, "final_outcome": None, "handoffs": []}
    try:
        task = json.loads(Path(task_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        rec.update(state="rejected", final_reason=f"tarefa ilegível: {exc}")
        return rec
    errors = validate_task(task, allow_any=True)
    rec["task_id"] = task.get("task_id", "TASK-0000")
    if errors:
        rec.update(state="rejected", final_reason="; ".join(errors))
        return rec
    if confirm != task["task_id"]:
        rec.update(state="rejected", final_reason="falta --confirm igual ao task_id")
        return rec
    cfg = availability.load_failover_config()
    if cfg.get("enabled_for_real_projects"):
        rec.update(state="rejected", final_reason="enabled_for_real_projects deve permanecer false nesta versão")
        return rec
    agents = load_agents()
    pinned = task["agent"] != "any_available"
    priority = [task["agent"]] if pinned else list(cfg["priority"])
    rec["priority"] = priority
    rec["availability_at_start"] = availability.snapshot_all(priority)
    tid = f"{time.strftime('%Y%m%d_%H%M%S')}{int(time.time() * 1000) % 1000:03d}-{task['task_id']}"
    rec["transfer_id"] = f"TRANSFER-{tid}"
    tpath = REPORTS / f"{rec['transfer_id']}.json"

    project = Path(task["project_path"]).resolve()
    try:
        locks = RunLocks(project, task["task_id"], "failover_manager", 3600)
        locks.__enter__()
    except LockError as exc:
        rec.update(state="stopped_busy", final_reason=f"BUSY: {exc}")
        _write_transfer(tpath, rec)
        _tlog({"transfer": rec["transfer_id"], "state": "stopped_busy"})
        return rec

    try:
        blocking = _blocking_record(task["task_id"])
        if blocking:
            rec.update(state="rejected", final_reason=f"registro anterior bloqueia nova execução ({blocking}): "
                       "resultado desconhecido ou transferência interrompida; revisar manualmente e mover o registro "
                       "para reports\\resolved\\")
            _write_transfer(tpath, rec)
            return rec
        _write_transfer(tpath, rec)
        eligible, skipped = availability.select(priority, agents)
        for agent, why in skipped:
            rec["steps"].append({"n": len(rec["steps"]) + 1, "agent": agent, "decision": "skipped", "reason": why})
        handoff_text = None
        last_report = None
        for agent in eligible:
            step = {"n": len(rec["steps"]) + 1, "agent": agent, "decision": "running", "run_id": None}
            rec["steps"].append(step)
            _write_transfer(tpath, rec)
            task_i = {**task, "agent": agent, "limits": {**task["limits"], "max_attempts": 1}}
            report = execute(task=task_i, confirm=confirm, handoff=handoff_text, held_locks=True)
            last_report = report
            step.update(run_id=report["run_id"], outcome=report["outcome"], status=report["status"])
            _tlog({"transfer": rec["transfer_id"], "agent": agent, "outcome": report["outcome"]})
            if report["outcome"] == oc.SUCCESS and report.get("task_verdict") != oc.TASK_ACCEPTED:
                # Sucesso técnico, mas critério obrigatório reprovado/não verificado: NÃO é erro de cota,
                # NÃO transfere, NÃO conta como concluída. Resultado preservado; exige revisão humana.
                rejected = report.get("task_verdict") == oc.TASK_REJECTED
                why = "critérios não atendidos: " + "; ".join(report.get("rejected_criteria", [])) if rejected \
                    else "critérios não verificáveis pelo orquestrador"
                step.update(decision="review_required", reason=why)
                rec.update(state="task_rejected_review_required" if rejected else "task_unverified_review_required",
                           final_reason=why, final_outcome=report["task_verdict"])
                break
            if report["outcome"] == oc.SUCCESS:
                step.update(decision="completed", reason="tarefa aprovada (TASK_ACCEPTED)")
                moved = any(x["decision"] == "transferred" for x in rec["steps"])
                rec.update(state="completed_after_transfer" if moved else "completed",
                           final_reason="tarefa concluída", final_outcome=oc.SUCCESS)
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
            # nenhum passo terminou em conclusão ou parada: acabaram os agentes elegíveis
            reason = "nenhum agente elegível" if last_report is None else \
                "todos os agentes elegíveis pararam por limite/autenticação"
            rec.update(state="stopped_no_agent", final_reason=reason,
                       final_outcome=last_report["outcome"] if last_report else None)
        rec["finished_at"] = now_iso()
        _write_transfer(tpath, rec)
        _tlog({"transfer": rec["transfer_id"], "state": rec["state"]})
        return rec
    finally:
        locks.release()
