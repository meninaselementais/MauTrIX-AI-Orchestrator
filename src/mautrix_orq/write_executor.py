"""Executor de ESCRITA CONTROLADA (V4). Só opera em lab\\git_lab; um agente por vez; uma tentativa por agente.

Camadas preventivas (a verificação de hash NÃO é a defesa principal):
 1. O agente roda numa CÓPIA (workspaces/<run>/) sem .git e sem arquivos não rastreados: o repositório real não
    está no diretório de trabalho dele.
 2. Claude: --restricted (sem shell/rede, ferramentas de arquivo confinadas ao diretório de trabalho), --tools e
    --allowedTools por arquivo, dontAsk sem prompts. Codex: continua read-only e só PROPÕE; quem escreve é o
    orquestrador.
 3. Nada chega ao repositório real sem passar por: caminhos autorizados, limites, UTF-8, validações declarativas,
    repositório real intacto durante a execução, ausência de conflito, backup, gravação atômica e verificação.
 4. Git é somente leitura aqui (sem commit/reset/clean/merge/rebase/push/tag).
"""
import difflib
import json
import time
from pathlib import Path

from . import availability, gitops, outcomes as oc, writescope as ws
from .common import (BACKUPS, LAB_GIT, MANIFESTS, PATCHES, RUNS, WORKSPACES, PolicyError, diff_snapshots,
                     load_agents, now_iso, redact)
from .adapters import InputEncodingError, get_adapter
from .executor import _base_report, _log, _write_report, run_process
from .locks import LockError, RunLocks

WRITE_STATUS = {oc.SUCCESS: "completed", oc.BUSY: "rejected_by_policy", oc.POLICY_REJECTED: "rejected_by_policy",
                oc.QUOTA_LIMITED: "blocked_by_limit", oc.AUTH_ERROR: "failed", oc.TECHNICAL_ERROR: "failed",
                oc.TIMEOUT: "timed_out", oc.UNKNOWN_RESULT: "failed", oc.VIOLATION: "violation_review_required"}
CRIT_SCOPE = "Somente caminhos autorizados foram alterados e nada foi excluído"
CRIT_LIMITS = "Limites de arquivos e bytes respeitados; conteúdo é texto UTF-8"
CRIT_CHANGED = "Houve ao menos uma alteração autorizada"
CRIT_VALID = "Validações declaradas aprovadas"
CRIT_SCHEMA = "A resposta do agente é um JSON válido conforme o schema"
CRIT_KEEP = "Repositório real, histórico Git e arquivos não rastreados preservados"
STRATEGIES = ("workspace_edit", "proposal")


def current_fingerprint(project: Path) -> str:
    return gitops.fingerprint(project, ws.tree_snapshot(project))


def _unified(rel: str, old: str, new: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}"))


def execute_write(task_path=None, confirm: str = None, dry_run: bool = False, task: dict = None, handoff: str = None,
                  held_locks: bool = False, expect_fingerprint: str = None) -> dict:
    started = now_iso()
    if task is None:
        try:
            task = json.loads(Path(task_path).read_text(encoding="utf-8"))
            errors = ws.validate_write_task(task)
        except (OSError, ValueError) as exc:
            task, errors = {}, [f"não foi possível ler a tarefa: {exc}"]
    else:
        errors = ws.validate_write_task(task)
    stamp = time.strftime("%Y%m%d_%H%M%S") + f"{int(time.time() * 1000) % 1000:03d}"
    run_id = f"RUN-{stamp}-{task.get('task_id', 'TASK-0000')}-{task.get('agent', 'x')}"
    run_dir, ws_dir = RUNS / run_id, WORKSPACES / run_id
    report = _base_report(task, run_id, started)
    report["handoff_received"] = bool(handoff)
    report["write"] = {"strategy": None, "git_before": None, "git_after": None, "workspace": None,
                       "changes": {"created": [], "modified": [], "deleted": []}, "violations": [], "validations": [],
                       "promoted": False, "workspace_changed": False, "backup_dir": None, "patch": None,
                       "manifest": None, "fingerprint_before": None, "fingerprint_after": None, "pending_changes": [],
                       "untracked_before": []}
    W = report["write"]

    def finish(outcome, summary, extra=(), next_action="", status=None):
        report["outcome"] = outcome
        report["execution_result"] = "EXECUTION_SUCCESS" if outcome == oc.SUCCESS else outcome
        report["status"] = status or WRITE_STATUS[outcome]
        report["summary"] = summary
        report["errors"] += list(extra)
        report["next_action_suggested"] = next_action
        report["finished_at"] = now_iso()
        _log({"run_id": run_id, "status": report["status"], "outcome": outcome, "mode": "write_scoped"})
        if dry_run:
            return report
        _write_report(report, run_dir)
        availability.update_from_report(report)
        return report

    if errors:
        return finish(oc.POLICY_REJECTED, "Tarefa de escrita rejeitada na validação.", errors, "Corrigir a tarefa.")
    if confirm != task["task_id"] and not dry_run:
        return finish(oc.POLICY_REJECTED, "Execução não autorizada: falta --confirm com o ID da tarefa.",
                      ["--confirm ausente ou diferente do task_id"], "Reenviar com --confirm " + task["task_id"])
    if availability.load_failover_config().get("enabled_for_real_projects"):
        return finish(oc.POLICY_REJECTED, "enabled_for_real_projects deve permanecer false.", [], "Corrigir a configuração.")
    spec = load_agents().get(task["agent"])
    if not spec or not spec.get("enabled", False):
        return finish(oc.POLICY_REJECTED, "Agente desativado na configuração.", [f"agente {task['agent']} desativado"])
    adapter = get_adapter(spec)
    strategy = spec.get("write_strategy") or getattr(adapter, "default_write_strategy", None)
    W["strategy"] = strategy
    if strategy not in STRATEGIES or not hasattr(adapter, "build_write_command" if strategy == "workspace_edit"
                                                  else "build_proposal_command"):
        return finish(oc.POLICY_REJECTED, "Este agente não tem estratégia de escrita controlada habilitada.",
                      [f"write_strategy={strategy!r} não suportada por {task['agent']}"], "Usar outro agente.")
    if not gitops.git_path():
        return finish(oc.POLICY_REJECTED, "git não encontrado no PATH; a V4 exige Git para o laboratório.", [])
    project = LAB_GIT.resolve()

    locks = None
    if not dry_run and not held_locks:
        try:
            locks = RunLocks(project, task["task_id"], task["agent"], task["limits"]["timeout_seconds"] + 300)
            locks.__enter__()
        except LockError as exc:
            return finish(oc.BUSY, "Outro agente ou execução está ativo.", [str(exc)], "Aguardar o término.")
    try:
        return _run(task, report, W, finish, adapter, spec, strategy, project, run_id, run_dir, ws_dir, dry_run,
                    handoff, expect_fingerprint)
    finally:
        if locks:
            locks.release()


def _run(task, report, W, finish, adapter, spec, strategy, project, run_id, run_dir, ws_dir, dry_run, handoff,
         expect_fp):
    # ---------------- 1. Git antes: branch, HEAD, pendências, não rastreados
    if not gitops.is_repo_root(project):
        return finish(oc.POLICY_REJECTED, "lab\\git_lab não é a raiz de um repositório Git.",
                      ["execute tools\\lab_git.py init --confirm LAB-GIT-INIT"], "Preparar o laboratório Git.")
    st = gitops.state(project)
    tracked = gitops.tracked_files(project)
    tree = ws.tree_snapshot(project)
    fp = gitops.fingerprint(project, tree)
    W["git_before"] = {k: st[k] for k in ("branch", "detached", "head", "tracked_changes", "untracked", "in_progress")}
    W["pending_changes"], W["untracked_before"], W["fingerprint_before"] = st["tracked_changes"], st["untracked"], fp
    problems = []
    if st["head"] is None:
        problems.append("repositório sem commit inicial")
    if st["in_progress"]:
        problems.append(f"operação Git em andamento: {st['in_progress']}")
    dirty = {c["path"] for c in st["tracked_changes"]}
    for p in task["allowed_modify"]:
        if p not in tracked:
            problems.append(f"{p}: arquivo a modificar não está rastreado pelo Git")
        if p in dirty:
            problems.append(f"{p}: já tem alterações pendentes (desconhecidas); não será sobrescrito")
    for p in task["allowed_create"]:
        if (project / p).exists():
            problems.append(f"{p}: já existe; use allowed_modify")
    if problems:
        return finish(oc.POLICY_REJECTED, "Pré-condições Git não atendidas.", problems, "Revisar o repositório do laboratório.")
    if expect_fp and expect_fp != fp:
        return finish(oc.VIOLATION, "O repositório mudou entre passos da cadeia; execução recusada para não "
                      "sobrescrever alterações desconhecidas.", ["fingerprint divergente"], "Revisão humana obrigatória.")

    # ---------------- 2. comando (nada é executado ainda)
    ws_root = project if dry_run else ws_dir
    exe = adapter.locate() if dry_run else None
    if not dry_run:
        avail = adapter.availability()
        report["agent_version"] = avail.get("version")
        if not avail.get("found"):
            return finish(oc.TECHNICAL_ERROR, "Executável do agente não encontrado.", ["não encontrado no PATH"])
        if avail.get("auth_state") != "AUTENTICADO":
            return finish(oc.AUTH_ERROR, "Agente não autenticado ou autenticação indeterminada.",
                          [f"auth_state={avail.get('auth_state')}"], "Fazer login manualmente.")
        exe = avail["path"]
    try:
        if not dry_run:
            ws.make_workspace(project, ws_dir, tracked)
        builder = adapter.build_write_command if strategy == "workspace_edit" else adapter.build_proposal_command
        argv, prompt = builder(exe or adapter.command, task, ws_root, run_dir, handoff)
    except InputEncodingError as exc:
        report["failure_kind"] = "input_encoding"
        return finish(oc.TECHNICAL_ERROR, "Erro de codificação em arquivo autorizado (não é bloqueio de política).",
                      ["ENCODING: " + str(exc)])
    except PolicyError as exc:
        return finish(oc.POLICY_REJECTED, "Comando recusado pela política.", [str(exc)])
    report["command"] = [Path(argv[0]).name] + [(a if len(str(a)) < 80 else str(a)[:60] + "…") for a in argv[1:]]
    if dry_run:
        return finish(oc.SUCCESS, "DRY-RUN: nada foi executado nem criado. Veja 'command' e 'write'.", [], "", status="completed")

    # ---------------- 3. manifesto de preservação (antes de o agente iniciar)
    mdir = MANIFESTS / run_id
    mdir.mkdir(parents=True, exist_ok=True)
    manifest = {"run_id": run_id, "task_id": task["task_id"], "created_at": now_iso(), "git": W["git_before"],
                "fingerprint": fp, "allowed_modify": task["allowed_modify"], "allowed_create": task["allowed_create"],
                "files": {k: {"bytes": v[0], "sha256": v[1], "tracked": k in tracked} for k, v in sorted(tree.items())}}
    (mdir / "preservation.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    W["manifest"], W["workspace"] = str(mdir / "preservation.json"), str(ws_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "task.json").write_text(json.dumps(task, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    before_ws = ws.tree_snapshot(ws_dir)

    # ---------------- 4. execução do agente (UMA vez) no workspace
    res = run_process(argv, prompt, ws_dir, task["limits"]["timeout_seconds"])
    report["agent_started"] = bool(res["started"])
    (run_dir / "stdout_1.txt").write_text(redact(res["stdout"]), encoding="utf-8")
    (run_dir / "stderr_1.txt").write_text(redact(res["stderr"]), encoding="utf-8")
    parsed = adapter.parse(res["stdout"], res["stderr"], res["exit_code"], run_dir) if not res["timed_out"] \
        else {"structured": None, "error_text": "", "text": "", "agent_reported_error": False}
    report["attempts"].append({"n": 1, "exit_code": res["exit_code"], "seconds": res["seconds"],
                               "timed_out": res["timed_out"], "error": res["error"]})
    report["exit_code"], report["timed_out"] = res["exit_code"], res["timed_out"]
    report["evidence"].append({"claim": f"Agente executado no workspace isolado; código de saída {res['exit_code']}",
                               "class": "executed_by_agent", "source": f"runs/{run_id}/stdout_1.txt"})

    # ---------------- 5. o repositório REAL foi tocado durante a execução?
    tree_now = ws.tree_snapshot(project)
    st_now = gitops.state(project)
    if gitops.fingerprint(project, tree_now) != fp:
        c, m, d = diff_snapshots(tree, tree_now)
        W["violations"].append({"kind": "real_repo_changed_during_run", "path": "*",
                                "detail": json.dumps({"created": c, "modified": m, "deleted": d}, ensure_ascii=False)})
        report["side_effects"] = True
        report["risks"].append("VIOLAÇÃO: o repositório real mudou durante a execução do agente. Nada foi promovido "
                               "nem restaurado automaticamente; revise manualmente.")
        return finish(oc.VIOLATION, "O repositório real foi alterado durante a execução (fora do workspace).",
                      [], "Revisão humana obrigatória; use backups/manifests para comparar.")

    after_ws = ws.tree_snapshot(ws_dir)
    ac, am, ad = diff_snapshots(before_ws, after_ws)
    W["workspace_changed"] = bool(ac or am or ad)
    report["side_effects"] = W["workspace_changed"]
    W["changes"] = {"created": ac, "modified": am, "deleted": ad}
    report["files_created"], report["files_changed"], report["files_deleted"] = ac, am, ad

    # ---------------- 6. falhas do processo
    if not res["started"]:
        return finish(oc.TECHNICAL_ERROR, "O processo do agente não pôde ser iniciado.", [res["error"] or ""])
    err_text = parsed["error_text"]
    cls = oc.classify_text(err_text) if (res["exit_code"] != 0 or parsed["agent_reported_error"]) else oc.classify_text("")
    report["limit"] = {"kind": cls["kind"], "confirmed": cls["confirmed"],
                       "retry_hint_reported_by_agent": cls["retry_hint_reported_by_agent"]}
    diag = oc.classify_text(err_text)
    report["diagnosis"] = {"kind": diag["kind"], "raw": diag["raw"] if diag["kind"] else None}
    if err_text.strip():
        report["errors"].append(redact(err_text)[:600])
    if W["workspace_changed"] and strategy == "proposal":
        W["violations"].append({"kind": "agent_wrote_in_readonly", "path": ",".join(ac + am + ad)[:200],
                                "detail": "o agente alterou o workspace apesar de estar em modo somente leitura"})
        return finish(oc.VIOLATION, "Agente em modo proposta alterou arquivos; descartado.", [], "Revisão humana.")
    if res["timed_out"]:
        return finish(oc.TIMEOUT, f"Tempo esgotado ({task['limits']['timeout_seconds']}s); "
                      + ("há alterações PARCIAIS no workspace (não promovidas)." if W["workspace_changed"] else "sem alterações."),
                      [], "Revisar manualmente; o repositório real não foi tocado.")
    if res["exit_code"] != 0 or parsed["agent_reported_error"]:
        if cls["kind"] == "quota":
            return finish(oc.QUOTA_LIMITED, "Limite de uso confirmado pela mensagem do agente.", [],
                          "Aguardar renovação ou usar outro agente.")
        if cls["kind"] == "auth":
            return finish(oc.AUTH_ERROR, "Erro de autenticação reportado pelo agente.", [], "Fazer login manualmente.")
        return finish(oc.TECHNICAL_ERROR, "Erro técnico (não identificado como limite de uso).", [],
                      f"Ler runs/{run_id}/stderr_1.txt.")
    structured = parsed["structured"]
    report["agent_output"] = structured
    if structured is None or not isinstance(structured, dict):
        return finish(oc.UNKNOWN_RESULT, "Código 0, mas sem resultado estruturado confiável.", [], "Revisar manualmente.")
    schema_ok = (isinstance(structured.get("summary"), str) and
                 (isinstance(structured.get("changes"), list) if strategy == "proposal"
                  else isinstance(structured.get("files_changed"), list) and isinstance(structured.get("notes"), list)))

    # ---------------- 7. proposta (Codex): o ORQUESTRADOR escreve no workspace, só em caminhos autorizados
    if strategy == "proposal" and schema_ok:
        applied, pv = ws.apply_proposal(structured, task, ws_dir)
        W["violations"] += pv
        after_ws = ws.tree_snapshot(ws_dir)
        ac, am, ad = diff_snapshots(before_ws, after_ws)
        W["workspace_changed"], W["changes"] = bool(ac or am or ad), {"created": ac, "modified": am, "deleted": ad}
        report["files_created"], report["files_changed"], report["files_deleted"] = ac, am, ad
        report["side_effects"] = False  # quem escreveu foi o orquestrador, não o agente
        (run_dir / "proposal.json").write_text(json.dumps(structured, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---------------- 8. escopo, limites, conteúdo, validações
    W["violations"] += ws.check_changes(task, ac, am, ad, ws_dir, after_ws)
    if W["violations"]:
        report["risks"].append("VIOLAÇÃO de escopo: " + "; ".join(f"{v['kind']}:{v['path']}" for v in W["violations"])[:400])
        return finish(oc.VIOLATION, "Violação de escopo: nada foi promovido; workspace preservado para revisão.", [],
                      "Revisão humana obrigatória.")
    W["validations"] = ws.run_validations(task, ws_dir)
    scope_ok = not any(v["kind"] in ("delete_forbidden", "create_not_allowed", "modify_not_allowed") for v in W["violations"])
    checks = {CRIT_SCHEMA: "yes" if schema_ok else "no", CRIT_SCOPE: "yes" if scope_ok else "no",
              CRIT_LIMITS: "yes", CRIT_CHANGED: "yes" if (ac or am) else "no",
              CRIT_VALID: "yes" if all(v["ok"] for v in W["validations"]) else "no", CRIT_KEEP: "not_verified"}

    # ---------------- 9. promoção (só se tudo acima passou)
    promoted = None
    if all(v == "yes" for k, v in checks.items() if k != CRIT_KEEP):
        promoted = ws.promote(project, ws_dir, ac, am, tree, run_id)
        if not promoted["ok"]:
            W["violations"].append({"kind": "promotion_conflict", "path": "*", "detail": "; ".join(promoted["conflicts"])})
            W["backup_dir"] = promoted.get("backup_dir")
            return finish(oc.VIOLATION, "Conflito na promoção: nada foi sobrescrito.", promoted["conflicts"],
                          "Revisão humana obrigatória.")
        W["promoted"], W["backup_dir"] = True, promoted["backup_dir"]
        tree_after = ws.tree_snapshot(project)
        c2, m2, d2 = diff_snapshots(tree, tree_after)
        st_after = gitops.state(project)
        W["git_after"] = {k: st_after[k] for k in ("branch", "detached", "head", "tracked_changes", "untracked", "in_progress")}
        keep_ok = (sorted(c2) == sorted(ac) and sorted(m2) == sorted(am) and not d2
                   and st_after["head"] == st["head"] and st_after["branch"] == st["branch"]
                   and st_after["refs_sha256"] == st["refs_sha256"]
                   and all(u in st_after["untracked"] for u in st["untracked"] if u not in ac)
                   and all(tree_after.get(k) == v for k, v in tree.items() if k not in am))
        checks[CRIT_KEEP] = "yes" if keep_ok else "no"
        W["fingerprint_after"] = gitops.fingerprint(project, tree_after)
        PATCHES.mkdir(parents=True, exist_ok=True)
        parts = [_unified(r, (BACKUPS / run_id / "files" / r).read_text(encoding="utf-8"), (project / r).read_text(encoding="utf-8")) for r in am]
        parts += [_unified(r, "", (project / r).read_text(encoding="utf-8")) for r in ac]
        patch = PATCHES / f"{run_id}.diff"
        patch.write_text("".join(parts) + "\n# git diff (arquivos rastreados)\n" + gitops.diff_text(project), encoding="utf-8")
        W["patch"] = str(patch)
        report["evidence"] += [
            {"claim": "Hashes antes/depois e preservação do repositório real conferidos", "class": "verified_by_orchestrator",
             "source": W["manifest"]},
            {"claim": "git diff e diff unificado salvos", "class": "verified_by_orchestrator", "source": str(patch)}]
        if not keep_ok:
            report["risks"].append("Preservação falhou após a promoção; use write-restore (explícito) ou revise.")
            report["acceptance_result"] = [{"criterion": k, "met": v} for k, v in checks.items()]
            return finish(oc.VIOLATION, "Promoção feita, mas a verificação de preservação falhou.", [],
                          "Revisão humana obrigatória (backup disponível).")
    report["acceptance_result"] = [{"criterion": k, "met": v} for k, v in checks.items()]
    verdict = oc.task_verdict(report["acceptance_result"])
    report["task_verdict"] = verdict
    report["rejected_criteria"] = [r["criterion"] for r in report["acceptance_result"] if r["met"] == "no"]
    if verdict != oc.TASK_ACCEPTED:
        tag = "task_rejected" if verdict == oc.TASK_REJECTED else "task_unverified"
        return finish(oc.SUCCESS, f"EXECUTION_SUCCESS, mas {verdict}: " + "; ".join(report["rejected_criteria"])
                      + " (nada foi promovido; workspace preservado).", [], "Revisar; não repetir automaticamente.", status=tag)
    return finish(oc.SUCCESS, f"Tarefa aprovada (TASK_ACCEPTED): {len(ac)} criado(s), {len(am)} modificado(s) e promovido(s) "
                  "com backup. Nenhum commit foi feito.", [], "Revisar o diff; commit só com autorização.")
