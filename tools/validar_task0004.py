#!/usr/bin/env python3
"""V3.3 - validação do Codex com contexto EMBUTIDO (TASK-0004). Somente leitura, somente em lab\\projeto_descartavel.

  python tools\\validar_task0004.py dry-run                       -> NÃO inicia nenhum agente; confere tudo e grava evidências
  python tools\\validar_task0004.py run --confirm TASK-0004       -> UMA execução real do Codex (consome cota)

Garantias: agente fixo codex_cli (sem transferência), uma única tentativa, nenhuma segunda execução de TASK-0004,
histórico (TASK-0003, relatórios, execuções, logs, transferências) verificado por SHA-256 antes e depois.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from mautrix_orq.adapters import ALLOWED_EXTRA_ARGS, get_adapter  # noqa: E402
from mautrix_orq.common import (HANDOFFS, LAB_ROOT, LOCKS, LOGS, REPORTS, ROOT, RUNS, diff_snapshots, load_agents,  # noqa: E402
                                now_iso, snapshot, validate_task)
from mautrix_orq.executor import execute  # noqa: E402

TASK_ID = "TASK-0004"
TASK_FILE = ROOT / "instructions" / "TASK-0004_codex_embedded_lab.json"
CONTEXT = "texto_exemplo.txt"
EXPECTED_LINES = 12
OUT = ROOT / "diagnostics"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def history() -> dict:
    """Mapa arquivo -> (tamanho, sha256) de tudo o que é histórico. Logs são só-anexar: guarda tamanho e hash."""
    snap = {}
    for base in (REPORTS, RUNS, HANDOFFS, LOGS):
        if base.exists():
            for rel, val in snapshot(base).items():
                snap[f"{base.name}/{rel}"] = val
    return snap


def history_intact(before: dict) -> list:
    """Problemas: arquivo histórico removido ou alterado. Logs podem crescer (anexo), mas o início deve ser idêntico."""
    problems = []
    for key, (size, digest) in before.items():
        p = ROOT / key
        if not p.exists():
            problems.append(f"histórico removido: {key}")
        elif key.startswith("logs/") and key.endswith(".log"):
            data = p.read_bytes()
            if len(data) < size or hashlib.sha256(data[:size]).hexdigest() != digest:
                problems.append(f"log histórico alterado (não só anexado): {key}")
        elif snapshot_one(p) != (size, digest):
            problems.append(f"histórico alterado: {key}")
    return problems


def snapshot_one(p: Path):
    return (p.stat().st_size, sha(p))


def locks_now() -> list:
    return sorted(p.name for p in LOCKS.glob("*.lock")) if LOCKS.exists() else []


def prior_task_runs() -> list:
    return sorted(p.name for p in REPORTS.glob(f"RUN-*-{TASK_ID}-*.json")) if REPORTS.exists() else []


def preflight(real: bool) -> tuple:
    """Devolve (problemas, evidências). Nunca inicia agente."""
    problems, ev = [], {"checked_at": now_iso()}
    try:
        task = json.loads(TASK_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"tarefa ilegível: {exc}"], ev
    errs = validate_task(task)
    project = Path(task["project_path"]).resolve()
    lab_project = (LAB_ROOT / "projeto_descartavel").resolve()
    ev["task"] = {"task_id": task["task_id"], "agent": task["agent"], "mode": task["mode"], "project": str(project),
                  "context_files": task["context_files"], "max_attempts": task["limits"]["max_attempts"]}
    if errs:
        problems += [f"tarefa inválida: {e}" for e in errs]
    if task["task_id"] != TASK_ID:
        problems.append("task_id deve ser TASK-0004")
    if task["agent"] != "codex_cli":
        problems.append("agent deve ser codex_cli (sem transferência)")
    if task["mode"] != "read_only":
        problems.append("mode deve ser read_only")
    if project != lab_project:
        problems.append("project_path deve ser exatamente lab\\projeto_descartavel")
    if task["context_files"] != [CONTEXT]:
        problems.append(f"context_files deve ser exatamente ['{CONTEXT}']")
    if task["limits"]["max_attempts"] != 1:
        problems.append("max_attempts deve ser 1")
    if "puzzle" in str(project).lower() or "cs-" in str(project).lower():
        problems.append("o caminho parece ser o do projeto do jogo")

    fcfg = json.loads((ROOT / "config" / "failover.json").read_text(encoding="utf-8"))
    ev["enabled_for_real_projects"] = fcfg.get("enabled_for_real_projects")
    if fcfg.get("enabled_for_real_projects"):
        problems.append("enabled_for_real_projects deve ser false")

    spec = load_agents().get("codex_cli", {})
    ev["codex_config"] = {"context_delivery": spec.get("context_delivery"), "exec_extra_args": spec.get("exec_extra_args"),
                          "enabled": spec.get("enabled")}
    if spec.get("context_delivery") != "embedded":
        problems.append("config\\agents.json: codex_cli.context_delivery deve ser 'embedded'")
    if list(spec.get("exec_extra_args", [])) not in ALLOWED_EXTRA_ARGS:
        problems.append("config\\agents.json: exec_extra_args fora da lista permitida")
    if not spec.get("enabled"):
        problems.append("codex_cli está desativado na configuração")

    ctx = project / CONTEXT
    if not ctx.is_file():
        problems.append(f"{CONTEXT} não existe no laboratório")
    else:
        raw = ctx.read_bytes()
        own = sum(1 for ln in raw.decode("utf-8-sig", errors="replace").splitlines() if ln.strip())
        ev["context_file"] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "non_empty_lines": own}
        if own != EXPECTED_LINES:
            problems.append(f"o arquivo tem {own} linhas não vazias; esperado {EXPECTED_LINES}")

    # Comando e prompt são MONTADOS (nada é executado): confirma sandbox, ausência de bypass e conteúdo embutido.
    try:
        adapter = get_adapter(spec)
        exe = adapter.locate() or "codex"
        ev["codex_executable_found_in_path"] = bool(adapter.locate())
        argv, prompt = adapter.build_command(exe, task, project, ROOT / "runs" / "_dryrun_nao_criado", None)
        ev["command"] = [Path(argv[0]).name] + [a if len(str(a)) < 80 else str(a)[:60] + "…" for a in argv[1:]]
        ev["sandbox"] = argv[argv.index("--sandbox") + 1]
        if ev["sandbox"] != "read-only":
            problems.append("sandbox não é read-only")
        block = prompt.split("<<<ARQUIVO " + CONTEXT, 1)
        inner = block[1].split(">>>\n", 1)[1].split("\n<<<FIM", 1)[0] if len(block) > 1 and ">>>\n" in block[1] else None
        ev["prompt"] = {
            "embeds_file_content": inner is not None and inner.strip() == ctx.read_bytes().decode("utf-8-sig").strip(),
            "embedded_non_empty_lines": sum(1 for ln in (inner or "").splitlines() if ln.strip()),
            "tells_agent_no_commands_needed": "NÃO é necessário executar comandos" in prompt,
            "tells_agent_to_use_shell": "Você PODE usar comandos de shell" in prompt}
        if not ev["prompt"]["embeds_file_content"]:
            problems.append("o prompt não contém o conteúdo exato do arquivo")
        if ev["prompt"]["embedded_non_empty_lines"] != EXPECTED_LINES:
            problems.append("o bloco embutido não tem 12 linhas não vazias")
        if not ev["prompt"]["tells_agent_no_commands_needed"] or ev["prompt"]["tells_agent_to_use_shell"]:
            problems.append("o prompt não dispensa o uso de comandos pelo agente")
    except Exception as exc:  # noqa: BLE001 - qualquer falha aqui impede a execução real
        problems.append(f"não foi possível montar comando/prompt: {type(exc).__name__}: {exc}")

    ev["locks_before"] = locks_now()
    if ev["locks_before"]:
        problems.append("locks existentes: " + ", ".join(ev["locks_before"]))
    ev["previous_task0004_runs"] = prior_task_runs()
    if real and ev["previous_task0004_runs"]:
        problems.append("TASK-0004 já foi executada; esta validação é de execução única: " + ", ".join(ev["previous_task0004_runs"]))
    ev["task0003_history_files"] = sorted(k for k in history() if "TASK-0003" in k)
    return problems, ev


def write(name: str, ev: dict, lines: list) -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(ev, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def cmd_dry_run() -> int:
    problems, ev = preflight(real=False)
    ev.update(mode="dry-run", agent_started=False, problems=problems,
              verdict="DRY_RUN_OK" if not problems else "DRY_RUN_COM_PROBLEMAS")
    md = ["# TASK-0004 - dry-run (nenhum agente foi iniciado)", "", f"Veredito: **{ev['verdict']}**", "",
          f"- Config Codex: {ev.get('codex_config')}", f"- Sandbox: {ev.get('sandbox')}",
          f"- Arquivo: {ev.get('context_file')}", f"- Prompt: {ev.get('prompt')}",
          f"- Comando: {' '.join(ev.get('command', []))}", f"- Locks: {ev.get('locks_before')}",
          f"- TASK-0003 preservada (arquivos de histórico): {len(ev.get('task0003_history_files', []))}",
          f"- Execuções anteriores de TASK-0004: {ev.get('previous_task0004_runs')}",
          "", "Problemas: " + ("; ".join(problems) if problems else "nenhum")]
    write("task0004_dryrun", ev, md)
    return 0 if not problems else 1


def cmd_run(confirm: str) -> int:
    if confirm != TASK_ID:
        print("Recusado: use --confirm TASK-0004")
        return 2
    problems, ev = preflight(real=True)
    ev.update(mode="real", agent_started=False)
    if problems:
        ev.update(problems=problems, verdict="INTERROMPIDO_NA_PRE_VERIFICACAO")
        write("task0004_evidence", ev, ["# TASK-0004 - interrompida antes de iniciar o agente", "", *[f"- {p}" for p in problems]])
        return 1
    hist_before, lab_before = history(), snapshot(LAB_ROOT)
    report = execute(TASK_FILE, confirm=TASK_ID)       # UMA execução; agente fixo; sem transferência
    created, modified, deleted = diff_snapshots(lab_before, snapshot(LAB_ROOT))
    out = report.get("agent_output") if isinstance(report.get("agent_output"), dict) else None
    ev["run"] = {k: report.get(k) for k in ("run_id", "agent", "agent_version", "outcome", "execution_result", "task_verdict",
                                            "status", "exit_code", "side_effects", "summary", "errors", "diagnosis",
                                            "acceptance_result", "rejected_criteria", "limit")}
    ev["agent_output"] = out
    # V3.3 (correção): agent_started vem do relatório do executor; antes ficava com o False de antes da execução.
    ev["agent_started"] = report.get("agent_started") is True
    ev["run"]["agent_started"] = report.get("agent_started")
    ev["lab_diff"] = {"created": created, "modified": modified, "deleted": deleted}
    ev["locks_after"] = locks_now()
    ev["history_problems"] = history_intact(hist_before)
    checks = {
        "line_count = 12": bool(out) and out.get("line_count") == EXPECTED_LINES,
        "JSON válido": out is not None and report.get("execution_result") == "EXECUTION_SUCCESS",
        "TASK_ACCEPTED": report.get("task_verdict") == "TASK_ACCEPTED" and report.get("status") == "completed",
        "arquivos preservados": not (created or modified or deleted),
        "locks liberados": not ev["locks_after"],
        "histórico (TASK-0003 etc.) preservado": not ev["history_problems"],
        "agent_started consistente com a execução": ev["agent_started"] is True}
    ev["criteria"] = checks
    ev["problems"] = [f"critério falhou: {k}" for k, ok in checks.items() if not ok]
    ev["verdict"] = "VALIDACAO_APROVADA" if all(checks.values()) else \
        "VALIDACAO_REPROVADA" + ("_" + str(report.get("task_verdict")) if report.get("task_verdict") else "")
    md = ["# TASK-0004 - validação real do Codex (contexto embutido)", "", f"Veredito: **{ev['verdict']}**", "",
          *[f"- [{'x' if ok else ' '}] {k}" for k, ok in checks.items()], "",
          f"- Execução: {ev['run']['execution_result']}  Tarefa: {ev['run']['task_verdict']}  Status: {ev['run']['status']}  "
          f"Saída: {ev['run']['exit_code']}", f"- Run: {ev['run']['run_id']}", f"- Diagnóstico: {ev['run']['diagnosis']}",
          f"- Diferença no laboratório: {ev['lab_diff']}", f"- Locks depois: {ev['locks_after']}",
          f"- Problemas: {ev['problems'] or 'nenhum'}", "", "Não repetir automaticamente. Reprovação exige revisão humana."]
    write("task0004_evidence", ev, md)
    return 0 if ev["verdict"] == "VALIDACAO_APROVADA" else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("dry-run")
    r = sub.add_parser("run"); r.add_argument("--confirm", required=True)
    a = ap.parse_args()
    return cmd_dry_run() if a.cmd == "dry-run" else cmd_run(a.confirm)


if __name__ == "__main__":
    sys.exit(main())
