"""Executor supervisionado (V2, estendido na V3).

Nada roda sozinho: só executa quando chamado pela CLI com --confirm <TASK-ID>.
Fluxo: validar -> agente habilitado -> disponibilidade/autenticação -> locks -> snapshot antes ->
UMA execução do agente (timeout, sem bypass) -> snapshot depois -> classificação -> relatório.
A V3 não repete automaticamente uma execução que chegou a iniciar o agente.
"""
import json
import os
import subprocess
import time
from pathlib import Path

from . import __version__, availability, outcomes as oc
from .adapters import InputEncodingError, get_adapter
from .common import (LAB_ROOT, LOGS, REPORTS, RUNS, PolicyError, diff_snapshots, load_agents, now_iso, redact,
                     snapshot, validate_task)
from .locks import LockError, RunLocks

# Critérios que o orquestrador sabe verificar sozinho. Qualquer outro critério fica "not_verified".
CRIT_NO_CHANGES = "Nenhum arquivo do laboratório foi criado, alterado ou removido"
CRIT_STRUCTURED = "A resposta do agente é um JSON válido conforme o schema"
CRIT_LINES = "line_count informado confere com a contagem feita pelo orquestrador"

# "completed" só vale com TASK_ACCEPTED (ver finish)
STATUS_BY_OUTCOME = {oc.SUCCESS: "completed", oc.BUSY: "rejected_by_policy", oc.POLICY_REJECTED: "rejected_by_policy",
                     oc.QUOTA_LIMITED: "blocked_by_limit", oc.AUTH_ERROR: "failed", oc.TECHNICAL_ERROR: "failed",
                     oc.TIMEOUT: "timed_out", oc.UNKNOWN_RESULT: "failed", oc.VIOLATION: "completed_with_issues"}


def _log(event: dict) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOGS / "executor.log", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": now_iso(), **event}, ensure_ascii=False) + "\n")


def run_process(argv, stdin_text, cwd, timeout):
    """Executa o agente com timeout; no timeout encerra a árvore de processos."""
    start = time.time()
    flags = 0x00000200 if os.name == "nt" else 0  # CREATE_NEW_PROCESS_GROUP
    try:
        p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8", errors="replace", cwd=str(cwd), creationflags=flags)
    except OSError as exc:
        return {"exit_code": None, "stdout": "", "stderr": "", "timed_out": False, "started": False,
                "error": f"{type(exc).__name__}: {exc}", "seconds": 0.0}
    timed_out = False
    try:
        out, err = p.communicate(input=stdin_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        else:
            p.kill()
        try:
            out, err = p.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            out, err = "", ""
    return {"exit_code": p.returncode, "stdout": out or "", "stderr": err or "", "timed_out": timed_out,
            "started": True, "error": None, "seconds": round(time.time() - start, 1)}


def _expected_line_count(project: Path, task: dict):
    files = task.get("context_files", [])
    if len(files) != 1:
        return None
    text = (project / files[0]).read_text(encoding="utf-8", errors="replace")
    return sum(1 for ln in text.splitlines() if ln.strip())


def _base_report(task, run_id, started):
    return {"schema_version": 1, "task_id": task.get("task_id", "TASK-0000"), "run_id": run_id,
            "agent": task.get("agent", "?"), "agent_version": None, "how_run": "automatic_by_orchestrator",
            "orchestrator_version": __version__, "project_path": str(task.get("project_path", "")),
            "objective": task.get("objective", ""), "mode": task.get("mode"), "started_at": started,
            "finished_at": started, "status": "rejected_by_policy", "outcome": oc.POLICY_REJECTED,
            "agent_started": False, "side_effects": False, "timed_out": False, "exit_code": None, "attempts": [],
            "summary": "", "files_changed": [], "files_created": [], "files_deleted": [], "evidence": [],
            "git_state": {"before": None, "after": None},
            "limits_hit": {"detected": False, "kind": None, "raw_message": None,
                           "quota_status": "STATUS DESCONHECIDO"},
            "limit": {"kind": None, "confirmed": False, "retry_hint_reported_by_agent": None},
            "execution_result": None, "task_verdict": oc.NOT_EVALUATED, "diagnosis": {"kind": None, "raw": None},
            "failure_kind": None, "rejected_criteria": [],
            "handoff_received": False, "errors": [], "risks": [], "pending": [], "acceptance_result": [],
            "agent_output": None, "next_action_suggested": ""}


def _write_report(report: dict, run_dir: Path) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    base = REPORTS / report["run_id"]
    base.with_suffix(".json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md = [f"# Relatório {report['run_id']}", "",
          f"- Agente: {report['agent']} ({report.get('agent_version')})",
          f"- Projeto: {report['project_path']}",
          f"- Objetivo: {report['objective']}",
          f"- Início/Fim: {report['started_at']} → {report['finished_at']}",
          f"- Status: **{report['status']}**  Execução: **{report['execution_result']}**  Tarefa: **{report['task_verdict']}**  "
          f"Código de saída: {report['exit_code']}",
          f"- Agente iniciado: {report['agent_started']}  Efeitos colaterais no laboratório: {report['side_effects']}",
          f"- Criados: {report['files_created']}  Alterados: {report['files_changed']}  Removidos: {report['files_deleted']}",
          "", "## Resultado", report["summary"] or "(sem resumo)", ""]
    if report["agent_output"]:
        md += ["## Saída estruturada do agente", "```json",
               json.dumps(report["agent_output"], indent=2, ensure_ascii=False), "```", ""]
    md += ["## Critérios"] + [f"- [{r['met']}] {r['criterion']}" for r in report["acceptance_result"]]
    md += ["", "## Erros"] + ([f"- {e}" for e in report["errors"]] or ["- nenhum registrado"])
    md += ["", "## Riscos"] + ([f"- {e}" for e in report["risks"]] or ["- nenhum registrado"])
    md += ["", "## Evidências"] + [f"- ({e['class']}) {e['claim']}" for e in report["evidence"]]
    md += ["", "## Limites", f"- Limite detectado: {report['limits_hit']['detected']}  "
           f"Cota: {report['limits_hit']['quota_status']}",
           "", "## Próxima ação sugerida", report["next_action_suggested"] or "-", ""]
    base.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")
    return base.with_suffix(".json")


def execute(task_path=None, confirm: str = None, dry_run: bool = False, task: dict = None,
            handoff: str = None, held_locks: bool = False) -> dict:
    """Executa UMA vez o agente indicado em task['agent'].
    held_locks=True: o gerenciador de transferência já detém os locks (não adquirir de novo)."""
    started = now_iso()
    if task is None:
        try:
            task = json.loads(Path(task_path).read_text(encoding="utf-8"))
            errors = validate_task(task)
        except (OSError, ValueError) as exc:
            task, errors = {}, [f"não foi possível ler a tarefa: {exc}"]
    else:
        errors = validate_task(task)
    stamp = time.strftime("%Y%m%d_%H%M%S") + f"{int(time.time() * 1000) % 1000:03d}"
    run_id = f"RUN-{stamp}-{task.get('task_id', 'TASK-0000')}-{task.get('agent', 'x')}"
    run_dir = RUNS / run_id
    report = _base_report(task, run_id, started)
    report["handoff_received"] = bool(handoff)

    def finish(outcome, summary, extra_errors=(), next_action="", status=None):
        report["outcome"] = outcome
        report["execution_result"] = "EXECUTION_SUCCESS" if outcome == oc.SUCCESS else outcome
        report["status"] = status or STATUS_BY_OUTCOME[outcome]
        report["summary"] = summary
        report["errors"] += list(extra_errors)
        report["next_action_suggested"] = next_action
        report["finished_at"] = now_iso()
        _log({"run_id": run_id, "status": report["status"], "outcome": outcome, "exit_code": report["exit_code"]})
        if dry_run:
            return report
        _write_report(report, run_dir)
        availability.update_from_report(report)
        return report

    if errors:
        return finish(oc.POLICY_REJECTED, "Tarefa rejeitada na validação.", errors, "Corrigir a tarefa e reenviar.")
    if confirm != task["task_id"] and not dry_run:
        return finish(oc.POLICY_REJECTED, "Execução não autorizada: falta --confirm com o ID da tarefa.",
                      ["--confirm ausente ou diferente do task_id"], "Reenviar com --confirm " + task["task_id"])

    spec = load_agents().get(task["agent"])
    if not spec or not spec.get("enabled", False):
        return finish(oc.POLICY_REJECTED, "Agente desativado na configuração.",
                      [f"agente {task['agent']} está desativado"], "Usar claude_code ou codex_cli.")
    adapter = get_adapter(spec)
    avail = adapter.availability()
    report["agent_version"] = avail.get("version")
    if not avail.get("found"):
        return finish(oc.TECHNICAL_ERROR, "Executável do agente não encontrado.",
                      ["executável não encontrado no PATH"], "Verificar a instalação.")
    if avail.get("auth_state") != "AUTENTICADO":
        return finish(oc.AUTH_ERROR, "Agente não autenticado ou autenticação indeterminada.",
                      [f"auth_state={avail.get('auth_state')}"], "Fazer login no agente manualmente.")

    project = Path(task["project_path"]).resolve()
    lim = task["limits"]
    try:
        argv, prompt = adapter.build_command(avail["path"], task, project, run_dir, handoff)
    except InputEncodingError as exc:
        report["failure_kind"] = "input_encoding"
        return finish(oc.TECHNICAL_ERROR, "Erro de codificação no arquivo de contexto (não é bloqueio de política).",
                      ["ENCODING: " + str(exc)], "Converter o arquivo para UTF-8; o agente não foi iniciado.")
    except PolicyError as exc:
        return finish(oc.POLICY_REJECTED, "Comando recusado pela política.", [str(exc)])
    report["command"] = [Path(argv[0]).name] + [
        (a if len(str(a)) < 80 else str(a)[:60] + "…") for a in argv[1:]]
    if dry_run:
        return finish(oc.SUCCESS, "DRY-RUN: nada foi executado. Comando que seria usado listado em 'command'.")

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "task.json").write_text(json.dumps(task, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    locks = None
    if not held_locks:
        try:
            locks = RunLocks(project, task["task_id"], task["agent"], lim["timeout_seconds"] + 300)
            locks.__enter__()
        except LockError as exc:
            return finish(oc.BUSY, "Outro agente ou execução está ativo.", [str(exc)],
                          "Aguardar o término ou conferir o lock.")

    try:
        before = snapshot(LAB_ROOT)
        res = run_process(argv, prompt, project, lim["timeout_seconds"])
        report["agent_started"] = bool(res["started"])
        (run_dir / "stdout_1.txt").write_text(redact(res["stdout"]), encoding="utf-8")
        (run_dir / "stderr_1.txt").write_text(redact(res["stderr"]), encoding="utf-8")
        parsed = adapter.parse(res["stdout"], res["stderr"], res["exit_code"], run_dir) if not res["timed_out"] \
            else {"structured": None, "error_text": "", "text": "", "agent_reported_error": False}
        after = snapshot(LAB_ROOT)
        created, modified, deleted = diff_snapshots(before, after)
    finally:
        if locks:
            locks.release()

    report["attempts"].append({"n": 1, "exit_code": res["exit_code"], "seconds": res["seconds"],
                               "timed_out": res["timed_out"], "error": res["error"]})
    report["exit_code"], report["timed_out"] = res["exit_code"], res["timed_out"]
    report["files_created"], report["files_changed"], report["files_deleted"] = created, modified, deleted
    report["side_effects"] = bool(created or modified or deleted)
    report["evidence"].append({"claim": f"Agente executado pelo orquestrador; código de saída {res['exit_code']}",
                               "class": "executed_by_agent", "source": f"runs/{run_id}/stdout_1.txt"})
    report["evidence"].append({"claim": "Snapshot SHA-256 do laboratório antes e depois",
                               "class": "verified_by_orchestrator", "source": "lab/"})
    report["pending"].append("Git não é usado no laboratório; git_state não se aplica.")
    structured = parsed["structured"]
    report["agent_output"] = structured
    if report["side_effects"]:
        report["risks"].append("VIOLAÇÃO: o modo era somente leitura, mas arquivos do laboratório mudaram.")
    err_text = parsed["error_text"]
    cls = oc.classify_text(err_text) if (res["exit_code"] != 0 or parsed["agent_reported_error"]) \
        else oc.classify_text("")
    report["limit"] = {"kind": cls["kind"], "confirmed": cls["confirmed"],
                       "retry_hint_reported_by_agent": cls["retry_hint_reported_by_agent"]}
    if cls["kind"] == "quota":
        report["limits_hit"] = {"detected": True, "kind": "rate_limit", "raw_message": cls["raw"],
                                "quota_status": "STATUS DESCONHECIDO"}
    if res["timed_out"]:
        report["limits_hit"].update(detected=True, kind="timeout")
    # Diagnóstico independente do código de saída: separa política, codificação, cota, autenticação.
    diag = oc.classify_text(err_text)
    signals = diag["kind"]
    out_blob = json.dumps(structured, ensure_ascii=False) if isinstance(structured, dict) else ""
    if oc.looks_mojibake(out_blob):
        report["risks"].append("ENCODING: a saída do agente contém sequências típicas de mojibake.")
        signals = signals or "encoding"
    report["diagnosis"] = {"kind": signals, "raw": diag["raw"] if diag["kind"] else None}
    if err_text.strip():
        report["errors"].append(redact(err_text)[:600])
    if res["error"]:
        report["errors"].append(res["error"])

    expected = _expected_line_count(project, task)
    checks = {CRIT_NO_CHANGES: "yes" if not report["side_effects"] else "no",
              CRIT_STRUCTURED: "yes" if isinstance(structured, dict) and
              all(k in structured for k in ("summary", "line_count", "word_count", "key_points", "next_action"))
              else "no"}
    if expected is not None:
        got = structured.get("line_count") if isinstance(structured, dict) else None
        checks[CRIT_LINES] = "yes" if got == expected and isinstance(got, int) else "no"
        report["evidence"].append({"claim": f"Linhas não vazias contadas pelo orquestrador: {expected}",
                                   "class": "verified_by_orchestrator", "source": task["context_files"][0]})
    report["acceptance_result"] = [{"criterion": c, "met": checks.get(c, "not_verified")}
                                   for c in task["acceptance"]]
    all_met = all(r["met"] == "yes" for r in report["acceptance_result"])

    if not res["started"]:
        return finish(oc.TECHNICAL_ERROR, "O processo do agente não pôde ser iniciado.", [],
                      "Verificar a instalação.")
    if res["timed_out"]:
        return finish(oc.TIMEOUT, f"Tempo esgotado ({lim['timeout_seconds']}s); resultado desconhecido.", [],
                      "Revisar manualmente antes de repetir.")
    if res["exit_code"] != 0 or parsed["agent_reported_error"]:
        if cls["kind"] == "quota":
            return finish(oc.QUOTA_LIMITED, "Limite de uso confirmado pela mensagem do agente.", [],
                          "Aguardar renovação ou usar outro agente; cota restante é STATUS DESCONHECIDO.")
        if cls["kind"] == "auth":
            return finish(oc.AUTH_ERROR, "Erro de autenticação reportado pelo agente.", [],
                          "Fazer login manualmente.")
        return finish(oc.TECHNICAL_ERROR, "Erro técnico (não identificado como limite de uso).", [],
                      "Ler runs/%s/stderr_1.txt." % run_id)
    if structured is None:
        return finish(oc.UNKNOWN_RESULT, "Código 0, mas sem resultado estruturado confiável.", [],
                      "Revisar manualmente antes de repetir.")
    if report["side_effects"]:
        report["task_verdict"] = oc.TASK_REJECTED
        report["rejected_criteria"] = [r["criterion"] for r in report["acceptance_result"] if r["met"] == "no"]
        return finish(oc.VIOLATION, "Executado, mas alterou arquivos em modo somente leitura.", [],
                      "Revisar o laboratório antes de prosseguir.")
    verdict = oc.task_verdict(report["acceptance_result"])
    report["task_verdict"] = verdict
    report["rejected_criteria"] = [r["criterion"] for r in report["acceptance_result"] if r["met"] == "no"]
    if verdict == oc.TASK_REJECTED:
        cause = {"policy": " Causa provável: bloqueio de política do shell do agente (não é cota nem codificação).",
                 "encoding": " Causa provável: erro de codificação (não é bloqueio de política)."}.get(
            report["diagnosis"]["kind"], "")
        return finish(oc.SUCCESS, "EXECUTION_SUCCESS, mas TASK_REJECTED: " + "; ".join(report["rejected_criteria"]) + cause,
                      [], "Revisar o resultado preservado; não repetir automaticamente.", status="task_rejected")
    if verdict == oc.TASK_UNVERIFIED:
        return finish(oc.SUCCESS, "EXECUTION_SUCCESS, mas há critérios não verificados (TASK_UNVERIFIED).", [],
                      "Revisar manualmente.", status="task_unverified")
    return finish(oc.SUCCESS, str(structured.get("summary", ""))[:1000], [],
                  "Sugestão do agente: " + str(structured.get("next_action", ""))[:300])
