"""Utilitários compartilhados: caminhos, redação, snapshots de arquivos e validação de tarefas."""
import datetime
import hashlib
import json
import os
import re
from pathlib import Path

ROOT = Path(os.environ.get("MAUTRIX_ROOT") or Path(__file__).resolve().parents[2])
CONFIG_PATH = ROOT / "config" / "agents.json"
LAB_ROOT = ROOT / "lab"
RUNS = ROOT / "runs"
REPORTS = ROOT / "reports"
LOGS = ROOT / "logs"
LOCKS = ROOT / "locks"
SCHEMAS = ROOT / "schemas"
STATE = ROOT / "state"
HANDOFFS = ROOT / "handoffs"
# V4 (escrita controlada)
WORKSPACES = ROOT / "workspaces"   # cópias isoladas onde o agente edita
BACKUPS = ROOT / "backups"         # originais dos arquivos antes de qualquer promoção
MANIFESTS = ROOT / "manifests"     # manifesto de preservação por execução
PATCHES = ROOT / "patches"         # diffs gerados
LAB_GIT = LAB_ROOT / "git_lab"     # ÚNICO repositório Git em que a V4 pode escrever
# Arquivos de exemplo que formam o commit-base do laboratório (somente estes entram no commit; o resto fica não rastreado).
LAB_BASELINE_FILES = (".gitignore", "README.txt", "config.json", "notas.txt", "docs/guia.md", "src/soma.py")
FAILOVER_CONFIG = ROOT / "config" / "failover.json"
# Modo de teste (agentes simulados): relaxa o timeout mínimo e restringe executáveis a MAUTRIX_TEST_BIN.
TEST_MODE = os.environ.get("MAUTRIX_TEST_MODE") == "1"

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
LONG_TOKEN = re.compile(r"[A-Za-z0-9_\-]{32,}")
TASK_ID = re.compile(r"^TASK-[0-9]{4}$")

# V2 só executa estes agentes. Antigravity permanece desativado até haver interface confirmada.
V2_AGENTS = ("claude_code", "codex_cli")

# Fragmentos que NUNCA podem aparecer em uma linha de comando montada pelo orquestrador.
FORBIDDEN_ARG_FRAGMENTS = (
    "--dangerously", "--full-auto", "--yolo", "danger-full-access", "bypassPermissions",
    "--approve-for-me", "--skip-permissions",
)


class PolicyError(Exception):
    """Violação da política de segurança (nunca deve ser contornada)."""


def redact(text: str) -> str:
    return LONG_TOKEN.sub("<redigido>", EMAIL.sub("<email>", text or ""))


def now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def load_agents() -> dict:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {a["id"]: a for a in data["agents"]}


def assert_safe_argv(argv: list) -> None:
    for arg in argv:
        for frag in FORBIDDEN_ARG_FRAGMENTS:
            if frag in str(arg):
                raise PolicyError(f"argumento proibido pela política: contém '{frag}'")
    if any(str(a).strip().lower() in ("reset", "clean") for a in argv):
        raise PolicyError("comandos git destrutivos não são permitidos")


def snapshot(root: Path, max_files: int = 5000) -> dict:
    """Mapa caminho-relativo -> (tamanho, sha256) de todos os arquivos sob root."""
    snap = {}
    count = 0
    for current, _dirs, files in os.walk(root):
        for name in files:
            full = Path(current) / name
            count += 1
            if count > max_files:
                raise PolicyError("laboratório grande demais para o snapshot (limite de arquivos)")
            h = hashlib.sha256()
            try:
                with open(full, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                size = full.stat().st_size
            except OSError:
                h, size = None, -1
            snap[str(full.relative_to(root)).replace("\\", "/")] = (size, h.hexdigest() if h else "ilegivel")
    return snap


def diff_snapshots(before: dict, after: dict):
    created = sorted(k for k in after if k not in before)
    deleted = sorted(k for k in before if k not in after)
    modified = sorted(k for k in after if k in before and after[k] != before[k])
    return created, modified, deleted


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_task(task: dict, allow_any: bool = False) -> list:
    """Retorna lista de erros; vazia se a tarefa pode ser executada. allow_any: aceita agent=any_available
    (somente o gerenciador de transferência, que substitui por um agente concreto antes de executar)."""
    errors = []
    for key in ("schema_version", "task_id", "project_path", "agent", "mode", "objective", "limits",
                "git_policy", "acceptance"):
        if key not in task:
            errors.append(f"campo obrigatório ausente: {key}")
    if errors:
        return errors
    if task["schema_version"] != 1:
        errors.append("schema_version deve ser 1")
    if not isinstance(task["task_id"], str) or not TASK_ID.match(task["task_id"]):
        errors.append("task_id deve seguir TASK-0000")
    if not (allow_any and task["agent"] == "any_available") and task["agent"] not in V2_AGENTS:
        errors.append(f"agente '{task['agent']}' não é executável na V2 (permitidos: {', '.join(V2_AGENTS)})")
    if task["mode"] != "read_only":
        errors.append("a V2 executa somente mode=read_only")
    if not str(task["objective"]).strip():
        errors.append("objective vazio")
    gp = task["git_policy"]
    if not isinstance(gp, dict) or any(gp.get(k) is not False for k in ("commit", "push", "merge", "tag")):
        errors.append("git_policy deve ter commit/push/merge/tag = false")
    lim = task["limits"]
    if not isinstance(lim, dict) or not isinstance(lim.get("timeout_seconds"), int) \
            or not isinstance(lim.get("max_attempts"), int):
        errors.append("limits exige timeout_seconds e max_attempts inteiros")
    else:
        if not (3 if TEST_MODE else 30) <= lim["timeout_seconds"] <= 1800:
            errors.append("timeout_seconds deve estar entre 30 e 1800")
        if not 1 <= lim["max_attempts"] <= 2:
            errors.append("max_attempts deve ser 1 ou 2 na V2")
    if not isinstance(task["acceptance"], list) or not task["acceptance"]:
        errors.append("acceptance deve ser uma lista não vazia")
    # Caminho do projeto: precisa estar DENTRO do laboratório.
    project = Path(str(task["project_path"]))
    try:
        resolved = project.resolve(strict=True)
    except OSError:
        errors.append("project_path não existe")
        return errors
    if "cs-puzzle-fighter" in str(resolved).lower():
        errors.append("o projeto do jogo não pode ser usado como ambiente de teste")
    if not _inside(resolved, LAB_ROOT.resolve()):
        errors.append(f"project_path deve estar dentro do laboratório ({LAB_ROOT})")
    elif not resolved.is_dir():
        errors.append("project_path deve ser uma pasta")
    else:
        for rel in task.get("context_files", []):
            target = (resolved / rel).resolve()
            if not _inside(target, resolved) or not target.is_file():
                errors.append(f"context_file inválido ou fora do projeto: {rel}")
    return errors
