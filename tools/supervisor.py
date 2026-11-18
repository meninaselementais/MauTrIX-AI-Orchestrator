#!/usr/bin/env python3
"""CLI do orquestrador supervisionado. Nada executa ao iniciar; cada comando é explícito.

  python tools\\supervisor.py check                         -> disponibilidade/autenticação (sem tarefas)
  python tools\\supervisor.py status                        -> estados de disponibilidade e transferências abertas
  python tools\\supervisor.py dry-run <tarefa.json>         -> valida e mostra o comando; não executa agente
  python tools\\supervisor.py run <tarefa.json> --confirm TASK-0001        (V2: agente fixo)
  python tools\\supervisor.py failover <tarefa.json> --confirm TASK-0003   (V3: transferência entre agentes, só lab/)
  V4 - escrita controlada (somente lab\\git_lab, nunca faz commit):
  python tools\\supervisor.py write-dry-run <tarefa.json>                   -> valida, mostra Git e comando; nada é criado
  python tools\\supervisor.py write-run <tarefa.json> --confirm TASK-1001   -> UM agente fixo, escreve só se tudo validar
  python tools\\supervisor.py write-failover <tarefa.json> --confirm ID     -> transferência segura (sem alterações prévias)
  python tools\\supervisor.py write-restore <RUN-ID> --confirm RESTORE-<RUN-ID>  -> desfaz uma promoção (explícito)
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from mautrix_orq import availability  # noqa: E402
from mautrix_orq.adapters import get_adapter  # noqa: E402
from mautrix_orq.common import REPORTS, load_agents  # noqa: E402
from mautrix_orq.executor import execute  # noqa: E402
from mautrix_orq.failover import BLOCKING_STATES, run_with_failover  # noqa: E402
from mautrix_orq.common import LAB_GIT  # noqa: E402
from mautrix_orq.write_executor import execute_write  # noqa: E402
from mautrix_orq.write_failover import run_write_with_failover  # noqa: E402
from mautrix_orq.writescope import restore  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="MauTrIX AI Orchestrator - execução supervisionada")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("status")
    d = sub.add_parser("dry-run"); d.add_argument("task")
    r = sub.add_parser("run"); r.add_argument("task"); r.add_argument("--confirm", required=True)
    f = sub.add_parser("failover"); f.add_argument("task"); f.add_argument("--confirm", required=True)
    wd = sub.add_parser("write-dry-run"); wd.add_argument("task")
    wr = sub.add_parser("write-run"); wr.add_argument("task"); wr.add_argument("--confirm", required=True)
    wf = sub.add_parser("write-failover"); wf.add_argument("task"); wf.add_argument("--confirm", required=True)
    wx = sub.add_parser("write-restore"); wx.add_argument("run_id"); wx.add_argument("--confirm", required=True)
    args = ap.parse_args()

    if args.cmd == "check":
        for spec in load_agents().values():
            print(json.dumps(get_adapter(spec).availability(), ensure_ascii=False))
        return 0
    if args.cmd == "status":
        ids = [a for a, s in load_agents().items() if s.get("enabled")]
        print(json.dumps(availability.snapshot_all(ids), indent=2, ensure_ascii=False))
        for p in sorted(REPORTS.glob("TRANSFER-*.json")):
            rec = json.loads(p.read_text(encoding="utf-8"))
            if rec.get("state") in BLOCKING_STATES:
                print("ATENÇÃO - requer revisão:", p.name, rec["state"], rec.get("final_reason"))
        return 0
    if args.cmd in ("write-dry-run", "write-run"):
        rep = execute_write(Path(args.task), confirm=getattr(args, "confirm", None), dry_run=(args.cmd == "write-dry-run"))
        keys = ("run_id", "agent", "status", "outcome", "task_verdict", "exit_code", "summary", "files_created",
                "files_changed", "files_deleted", "errors", "acceptance_result", "command")
        out = {k: rep[k] for k in keys if k in rep}
        out["write"] = {k: rep["write"].get(k) for k in ("strategy", "promoted", "workspace_changed", "violations",
                                                         "validations", "backup_dir", "patch", "manifest", "git_before",
                                                         "git_after", "workspace", "changes", "pending_changes",
                                                         "untracked_before")}
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0 if rep["status"] == "completed" else 1
    if args.cmd == "write-failover":
        rec = run_write_with_failover(Path(args.task), args.confirm)
        print(json.dumps({k: rec.get(k) for k in ("transfer_id", "task_id", "state", "final_reason", "priority",
                                                  "steps", "handoffs")}, indent=2, ensure_ascii=False))
        return 0 if rec["state"] in ("completed", "completed_after_transfer") else 1
    if args.cmd == "write-restore":
        res = restore(LAB_GIT, args.run_id, args.confirm)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1
    if args.cmd == "failover":
        rec = run_with_failover(Path(args.task), args.confirm)
        print(json.dumps({k: rec.get(k) for k in ("transfer_id", "task_id", "state", "final_reason", "priority",
                                                  "steps", "handoffs")}, indent=2, ensure_ascii=False))
        return 0 if rec["state"] in ("completed", "completed_after_transfer") else 1
    report = execute(Path(args.task), confirm=args.confirm if args.cmd == "run" else None,
                     dry_run=(args.cmd == "dry-run"))
    print(json.dumps({k: report[k] for k in ("run_id", "agent", "status", "outcome", "exit_code", "summary",
                                             "files_created", "files_changed", "files_deleted", "errors",
                                             "acceptance_result", "command") if k in report},
                     indent=2, ensure_ascii=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
