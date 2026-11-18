"""Git SOMENTE LEITURA para o orquestrador (V4).

Nenhuma função aqui altera o repositório: só subcomandos de leitura são aceitos, e nunca reset, clean, merge,
rebase, push, tag, commit, checkout, add, stash, etc. O repositório do laboratório é criado/baselinado por
tools/lab_git.py (ação explícita do usuário), nunca pelo orquestrador durante tarefas.
`GIT_OPTIONAL_LOCKS=0` evita que `git status` regrave o índice.
"""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from .common import PolicyError

READ_ONLY_SUBCOMMANDS = {"rev-parse", "status", "diff", "ls-files", "show-ref", "symbolic-ref", "log"}
FORBIDDEN_WORDS = {"reset", "clean", "merge", "rebase", "push", "tag", "commit", "checkout", "switch", "restore",
                   "stash", "add", "rm", "mv", "pull", "fetch", "cherry-pick", "revert", "branch", "config",
                   "gc", "prune", "apply", "am", "init", "clone", "update-ref", "worktree"}


class GitError(Exception):
    pass


def git_path():
    return shutil.which("git")


def _git(project: Path, *args: str, timeout: int = 30) -> str:
    if not args or args[0] not in READ_ONLY_SUBCOMMANDS:
        raise PolicyError(f"subcomando git não permitido (somente leitura): {args[:1]}")
    if any(a in FORBIDDEN_WORDS for a in args):
        raise PolicyError(f"argumento git proibido: {args}")
    exe = git_path()
    if not exe:
        raise GitError("git não encontrado no PATH")
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    p = subprocess.run([exe, "-c", "core.fsmonitor=false", "-c", "core.quotepath=false", "-C", str(project), *args],
                       capture_output=True, timeout=timeout, env=env)
    if p.returncode != 0:
        raise GitError(f"git {args[0]} falhou ({p.returncode}): {p.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return p.stdout.decode("utf-8", "replace")


def is_repo_root(project: Path) -> bool:
    """O diretório é a RAIZ de um repositório (não um subdiretório de outro)."""
    try:
        top = _git(project, "rev-parse", "--show-toplevel").strip()
    except (GitError, OSError):
        return False
    return Path(top).resolve() == Path(project).resolve()


def tracked_files(project: Path) -> list:
    out = _git(project, "ls-files", "-z")
    return sorted(x for x in out.split("\0") if x)


def _in_progress(project: Path) -> list:
    gd = Path(project) / ".git"
    return [n for n in ("MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")
            if (gd / n).exists()]


def state(project: Path) -> dict:
    """Estado Git sem alterar nada: branch, HEAD, alterações pendentes, não rastreados, refs."""
    project = Path(project)
    try:
        branch = _git(project, "symbolic-ref", "--short", "-q", "HEAD").strip()
    except GitError:
        branch = None  # HEAD destacado
    try:
        head = _git(project, "rev-parse", "HEAD").strip()
    except GitError:
        head = None
    raw = _git(project, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    parts = raw.split("\0")
    tracked_changes, untracked, i = [], [], 0
    while i < len(parts):
        item = parts[i]
        i += 1
        if len(item) < 4:
            continue
        xy, path = item[:2], item[3:]
        if xy[0] in "RC":
            i += 1  # -z: o nome original vem como campo seguinte
        (untracked if xy == "??" else tracked_changes).append({"xy": xy, "path": path} if xy != "??" else path)
    try:
        refs = _git(project, "show-ref")
    except GitError:
        refs = ""
    cfg = Path(project) / ".git" / "config"
    return {"branch": branch, "detached": branch is None, "head": head, "tracked_changes": tracked_changes,
            "untracked": sorted(untracked), "in_progress": _in_progress(project),
            "refs_sha256": hashlib.sha256(refs.encode()).hexdigest(),
            "config_sha256": hashlib.sha256(cfg.read_bytes()).hexdigest() if cfg.exists() else None}


def diff_text(project: Path) -> str:
    """git diff do que está modificado em arquivos rastreados (arquivos novos não rastreados não aparecem)."""
    return _git(project, "diff", "--no-color", "--no-ext-diff", "--no-textconv")


def status_short(project: Path) -> str:
    return _git(project, "status", "--short", "--untracked-files=all")


def fingerprint(project: Path, tree: dict) -> str:
    """Impressão digital do repositório: HEAD + refs + árvore de trabalho (sem .git). Muda se QUALQUER coisa mudar."""
    st = state(project)
    blob = json.dumps({"head": st["head"], "refs": st["refs_sha256"], "branch": st["branch"],
                       "tree": {k: list(v) for k, v in sorted(tree.items())}}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()
