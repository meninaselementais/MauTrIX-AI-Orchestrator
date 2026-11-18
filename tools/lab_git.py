#!/usr/bin/env python3
"""Prepara e inspeciona o repositório Git DESCARTÁVEL do laboratório (lab\\git_lab). V4.

  python tools\\lab_git.py state                          -> lê e grava o estado atual (somente leitura)
  python tools\\lab_git.py init --confirm LAB-GIT-INIT    -> git init + commit-base DENTRO de lab\\git_lab (ação do usuário)

O orquestrador NUNCA faz commit durante tarefas. O único commit é este commit-base do laboratório descartável,
só com os arquivos de exemplo, executado por você com confirmação explícita. Não toca em nenhum outro repositório
e não altera configuração global do Git (identidade e opções são passadas por -c / config local do laboratório).
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from mautrix_orq import gitops  # noqa: E402
from mautrix_orq.common import LAB_BASELINE_FILES, LAB_GIT, REPORTS, ROOT, now_iso  # noqa: E402
from mautrix_orq.writescope import tree_snapshot  # noqa: E402

IDENT = ["-c", "user.name=MauTrIX Lab", "-c", "user.email=lab@mautrix.invalid", "-c", "commit.gpgsign=false"]


def run_git(*args, cwd=LAB_GIT):
    exe = gitops.git_path()
    if not exe:
        raise SystemExit("git não encontrado no PATH")
    p = subprocess.run([exe, *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit(f"git {' '.join(args[:3])} falhou: {p.stderr.strip()[:300]}")
    return p.stdout


def describe() -> dict:
    st = gitops.state(LAB_GIT)
    tree = tree_snapshot(LAB_GIT)
    tracked = set(gitops.tracked_files(LAB_GIT))
    return {"captured_at": now_iso(), "git_version": subprocess.run([gitops.git_path(), "--version"], capture_output=True,
                                                                     text=True).stdout.strip(),
            "branch": st["branch"], "head": st["head"], "tracked_changes": st["tracked_changes"],
            "untracked": st["untracked"], "in_progress": st["in_progress"],
            "files": {k: {"bytes": v[0], "sha256": v[1], "tracked": k in tracked,
                          "ignored_or_untracked": k not in tracked} for k, v in sorted(tree.items())}}


def save(info: dict, name: str) -> None:
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{name}.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    md = [f"# {name}", "", f"- Capturado: {info['captured_at']}  Git: {info['git_version']}",
          f"- Branch: {info['branch']}  HEAD: {info['head']}", f"- Alterações rastreadas pendentes: {info['tracked_changes'] or 'nenhuma'}",
          f"- Não rastreados: {info['untracked'] or 'nenhum'}", "", "## Arquivos"]
    md += [f"- `{k}` {v['bytes']} bytes sha256 {v['sha256'][:12]}… {'rastreado' if v['tracked'] else 'NÃO rastreado/ignorado'}"
           for k, v in info["files"].items()]
    (REPORTS / f"{name}.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def cmd_init(confirm: str) -> int:
    if confirm != "LAB-GIT-INIT":
        print("Recusado: use --confirm LAB-GIT-INIT")
        return 2
    if LAB_GIT.resolve().parent != (ROOT / "lab").resolve() or LAB_GIT.name != "git_lab":
        print("Recusado: caminho do laboratório inesperado")
        return 2
    if (LAB_GIT / ".git").exists():
        print("lab\\git_lab já é um repositório Git. Nada foi feito (use 'state').")
        return 1
    missing = [f for f in LAB_BASELINE_FILES if not (LAB_GIT / f).is_file()]
    if missing:
        print("Recusado: arquivos de exemplo ausentes em lab\\git_lab: " + ", ".join(missing))
        return 2
    run_git("init", "--template=", "--initial-branch=main")
    run_git("config", "core.autocrlf", "false")      # config LOCAL do laboratório; hashes estáveis no Windows
    run_git("config", "core.safecrlf", "false")
    run_git("add", "--", *LAB_BASELINE_FILES)   # SOMENTE os arquivos de exemplo; qualquer outro arquivo fica não rastreado
    run_git(*IDENT, "commit", "-m", "Commit-base do laboratório Git descartável (V4)")
    # arquivos NÃO rastreados / ignorados usados para provar preservação
    for name, text in (("rascunho_local.txt", "Rascunho local NÃO rastreado. Deve sobreviver a qualquer tarefa.\n"),
                       ("cache_local.tmp", "Arquivo ignorado pelo .gitignore. Deve sobreviver a qualquer tarefa.\n")):
        if not (LAB_GIT / name).exists():          # nunca sobrescreve um arquivo já existente
            (LAB_GIT / name).write_text(text, encoding="utf-8")
    info = describe()
    save(info, "GITLAB_BASELINE")
    print(json.dumps({k: info[k] for k in ("branch", "head", "tracked_changes", "untracked")}, indent=2, ensure_ascii=False))
    print("Estado inicial gravado em reports\\GITLAB_BASELINE.json/.md")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("state")
    i = sub.add_parser("init"); i.add_argument("--confirm", required=True)
    a = ap.parse_args()
    if a.cmd == "init":
        return cmd_init(a.confirm)
    if not (LAB_GIT / ".git").exists():
        print("lab\\git_lab ainda não é um repositório. Rode: python tools\\lab_git.py init --confirm LAB-GIT-INIT")
        return 1
    info = describe()
    save(info, "GITLAB_STATE")
    print(json.dumps({k: info[k] for k in ("branch", "head", "tracked_changes", "untracked")}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
