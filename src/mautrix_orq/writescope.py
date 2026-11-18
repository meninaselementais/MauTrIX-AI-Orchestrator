"""Controle de escrita (V4): validação de tarefas de escrita, workspace isolado, verificação de escopo,
promoção com backup e restauração explícita.

Princípio: o agente NUNCA edita o repositório real. Ele trabalha numa CÓPIA (workspaces/<run>/) que não contém
.git nem arquivos não rastreados. Só depois de o orquestrador validar tudo (caminhos autorizados, limites,
UTF-8, validações declarativas, repositório real intacto) as mudanças são promovidas, com backup, de forma atômica
por arquivo. A verificação de hashes complementa o isolamento; não o substitui.
"""
import hashlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path

from .common import (BACKUPS, LAB_GIT, PolicyError, TEST_MODE, diff_snapshots, now_iso)

MAX_FILE_BYTES = 64 * 1024
SAFE_PATH = re.compile(r"^[A-Za-z0-9._\-/]+$")
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
GIT_POLICY_KEYS = ("commit", "push", "merge", "tag")
GIT_POLICY_EXTRA = ("reset", "clean", "rebase", "checkout", "stash")
VALIDATION_TYPES = ("contains", "not_contains", "max_lines", "json_valid")


def norm_rel(value):
    """(caminho_normalizado | None, erro | None). Somente relativo, ASCII seguro, sem .git/.., sem nomes reservados."""
    if not isinstance(value, str) or not value.strip():
        return None, "caminho vazio ou não é texto"
    if value != value.strip() or "\\" in value or value.startswith("/") or ":" in value:
        return None, f"caminho inválido (use barras '/', relativo, sem ':'): {value!r}"
    if not SAFE_PATH.match(value) or len(value) > 200:
        return None, f"caracteres não permitidos no caminho: {value!r}"
    parts = value.split("/")
    for part in parts:
        low = part.lower()
        if part in ("", ".", "..") or part.endswith(".") or low.startswith(".git"):
            return None, f"componente de caminho proibido: {value!r}"
        if low.split(".")[0] in RESERVED:
            return None, f"nome reservado do Windows: {value!r}"
    return value, None


def validate_write_task(task: dict, allow_any: bool = False) -> list:
    errors = []
    for key in ("schema_version", "task_id", "project_path", "agent", "mode", "objective", "limits", "git_policy",
                "allowed_modify", "allowed_create"):
        if key not in task:
            errors.append(f"campo obrigatório ausente: {key}")
    if errors:
        return errors
    if task["schema_version"] != 1:
        errors.append("schema_version deve ser 1")
    if not re.match(r"^TASK-[0-9]{4}$", str(task["task_id"])):
        errors.append("task_id deve seguir TASK-0000")
    agents = ("claude_code", "codex_cli") + (("any_available",) if allow_any else ())
    if task["agent"] not in agents:
        errors.append(f"agente '{task['agent']}' não permitido")
    if task["mode"] != "write_scoped":
        errors.append("mode deve ser 'write_scoped'")
    if not str(task["objective"]).strip():
        errors.append("objective vazio")
    gp = task["git_policy"]
    if not isinstance(gp, dict) or any(gp.get(k) is not False for k in GIT_POLICY_KEYS) \
            or any(gp.get(k) not in (None, False) for k in GIT_POLICY_EXTRA):
        errors.append("git_policy: commit/push/merge/tag devem ser false (e reset/clean/rebase/checkout/stash, se citados)")
    lim = task["limits"]
    if not isinstance(lim, dict) or not all(isinstance(lim.get(k), int) for k in
                                            ("timeout_seconds", "max_attempts", "max_files_changed", "max_bytes_changed")):
        errors.append("limits exige timeout_seconds, max_attempts, max_files_changed e max_bytes_changed inteiros")
    else:
        if not (3 if TEST_MODE else 30) <= lim["timeout_seconds"] <= 1800:
            errors.append("timeout_seconds deve estar entre 30 e 1800")
        if lim["max_attempts"] != 1:
            errors.append("max_attempts deve ser 1 na V4")
        if not 1 <= lim["max_files_changed"] <= 10:
            errors.append("max_files_changed deve estar entre 1 e 10")
        if not 1 <= lim["max_bytes_changed"] <= 200000:
            errors.append("max_bytes_changed deve estar entre 1 e 200000")
    seen = {}
    for field in ("allowed_modify", "allowed_create"):
        lst = task[field]
        if not isinstance(lst, list):
            errors.append(f"{field} deve ser uma lista")
            continue
        for item in lst:
            rel, err = norm_rel(item)
            if err:
                errors.append(f"{field}: {err}")
            elif rel.lower() in seen:
                errors.append(f"caminho repetido ou presente nas duas listas: {rel}")
            else:
                seen[rel.lower()] = field
    if isinstance(task["allowed_modify"], list) and isinstance(task["allowed_create"], list):
        if not task["allowed_modify"] and not task["allowed_create"]:
            errors.append("é preciso autorizar ao menos um arquivo")
        if len(task["allowed_modify"]) + len(task["allowed_create"]) > 10:
            errors.append("no máximo 10 arquivos autorizados")
    for chk in task.get("validation", []):
        if not isinstance(chk, dict) or chk.get("type") not in VALIDATION_TYPES or str(chk.get("path", "")).lower() not in seen:
            errors.append(f"validação inválida ou fora dos arquivos autorizados: {chk!r}")
    try:
        if Path(str(task["project_path"])).resolve(strict=True) != LAB_GIT.resolve():
            errors.append("project_path deve ser exatamente lab\\git_lab (único repositório com escrita na V4)")
    except OSError:
        errors.append("project_path não existe (lab\\git_lab ainda não foi preparado: tools\\lab_git.py init)")
    return errors


# ------------------------------------------------------------------ árvores e workspace
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_snapshot(root: Path) -> dict:
    """rel -> (tamanho, sha256) de todos os arquivos, EXCLUINDO .git. Links simbólicos aparecem como (-1, 'symlink')."""
    root, snap = Path(root), {}
    for cur, dirs, files in os.walk(root):
        if Path(cur) == root and ".git" in dirs:
            dirs.remove(".git")
        for d in list(dirs):
            if os.path.islink(os.path.join(cur, d)):
                snap[str((Path(cur) / d).relative_to(root)).replace("\\", "/")] = (-1, "symlink")
                dirs.remove(d)
        for name in files:
            full = Path(cur) / name
            rel = str(full.relative_to(root)).replace("\\", "/")
            if os.path.islink(full):
                snap[rel] = (-1, "symlink")
                continue
            snap[rel] = (full.stat().st_size, sha256_file(full))
    return snap


def make_workspace(project: Path, ws: Path, tracked: list) -> None:
    """Cópia dos arquivos RASTREADOS (estado atual da árvore de trabalho). Sem .git e sem não rastreados."""
    ws.mkdir(parents=True, exist_ok=False)
    for rel in tracked:
        src = Path(project) / rel
        if src.is_file() and not os.path.islink(src):
            dst = ws / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)


def check_changes(task: dict, created: list, modified: list, deleted: list, ws: Path, after: dict) -> list:
    """Violações de escopo/limites/conteúdo no workspace. Lista de {kind, path, detail}."""
    allow_mod = {p.lower() for p in task["allowed_modify"]}
    allow_new = {p.lower() for p in task["allowed_create"]}
    lim, v = task["limits"], []
    for p in deleted:
        v.append({"kind": "delete_forbidden", "path": p, "detail": "exclusões nunca são permitidas na V4"})
    for p in created:
        if p.lower() not in allow_new:
            v.append({"kind": "create_not_allowed", "path": p, "detail": "criação fora da lista autorizada"})
    for p in modified:
        if p.lower() not in allow_mod:
            v.append({"kind": "modify_not_allowed", "path": p, "detail": "alteração fora da lista autorizada"})
    if len(created) + len(modified) + len(deleted) > lim["max_files_changed"]:
        v.append({"kind": "too_many_files", "path": "*", "detail": f"limite {lim['max_files_changed']} arquivos"})
    total = 0
    for p in created + modified:
        size, digest = after.get(p, (0, ""))
        if digest == "symlink":
            v.append({"kind": "symlink", "path": p, "detail": "link simbólico não é permitido"})
            continue
        total += size
        if size > MAX_FILE_BYTES:
            v.append({"kind": "file_too_large", "path": p, "detail": f"{size} bytes (máx. {MAX_FILE_BYTES})"})
            continue
        data = (Path(ws) / p).read_bytes() if (Path(ws) / p).is_file() else b""
        if b"\x00" in data:
            v.append({"kind": "binary_content", "path": p, "detail": "conteúdo binário (NUL) não permitido"})
            continue
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            v.append({"kind": "not_utf8", "path": p, "detail": "arquivo não é UTF-8 válido"})
    if total > lim["max_bytes_changed"]:
        v.append({"kind": "too_many_bytes", "path": "*", "detail": f"{total} bytes (máx. {lim['max_bytes_changed']})"})
    return v


def run_validations(task: dict, ws: Path) -> list:
    """Validações declarativas executadas EM PROCESSO (sem shell, sem comandos do agente)."""
    out = []
    for chk in task.get("validation", []):
        f = Path(ws) / chk["path"]
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            out.append({"check": chk, "ok": False, "detail": f"não foi possível ler: {exc}"})
            continue
        t = chk["type"]
        if t == "contains":
            ok = str(chk.get("text", "")) in text
        elif t == "not_contains":
            ok = str(chk.get("text", "")) not in text
        elif t == "max_lines":
            ok = len(text.splitlines()) <= int(chk.get("n", 0))
        else:
            try:
                json.loads(text)
                ok = True
            except ValueError:
                ok = False
        out.append({"check": chk, "ok": bool(ok), "detail": "ok" if ok else "falhou"})
    return out


def apply_proposal(structured, task: dict, ws: Path):
    """Modo 'proposal' (Codex): aplica no WORKSPACE as mudanças propostas, só em caminhos autorizados.
    Devolve (aplicadas, violações). Qualquer caminho fora do escopo aborta a aplicação inteira."""
    v, applied = [], []
    changes = structured.get("changes") if isinstance(structured, dict) else None
    if not isinstance(changes, list):
        return applied, [{"kind": "proposal_invalid", "path": "*", "detail": "campo 'changes' ausente"}]
    allow_mod = {p.lower(): p for p in task["allowed_modify"]}
    allow_new = {p.lower(): p for p in task["allowed_create"]}
    plan = []
    for ch in changes:
        rel, err = norm_rel(ch.get("path") if isinstance(ch, dict) else None)
        action = ch.get("action") if isinstance(ch, dict) else None
        content = ch.get("content") if isinstance(ch, dict) else None
        if err or not isinstance(content, str):
            v.append({"kind": "proposal_invalid", "path": str(ch)[:80], "detail": err or "content não é texto"})
        elif action == "modify" and rel.lower() in allow_mod:
            plan.append((allow_mod[rel.lower()], content, True))
        elif action == "create" and rel.lower() in allow_new:
            plan.append((allow_new[rel.lower()], content, False))
        else:
            v.append({"kind": "proposal_path_not_allowed", "path": str(rel), "detail": f"ação {action!r} fora do escopo"})
    if v or len({p[0] for p in plan}) != len(plan):
        return [], v or [{"kind": "proposal_invalid", "path": "*", "detail": "caminho repetido na proposta"}]
    for rel, content, existing in plan:
        dst = Path(ws) / rel
        if existing:
            old = dst.read_bytes() if dst.exists() else b""
            if b"\r\n" in old and b"\n" not in old.replace(b"\r\n", b""):
                content = content.replace("\r\n", "\n").replace("\n", "\r\n")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(content.encode("utf-8"))
        applied.append(rel)
    return applied, []


# ------------------------------------------------------------------ promoção, backup, restauração
def _atomic_write(dst: Path, data: bytes, token: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + f".mx_{token}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, dst)


def promote(project: Path, ws: Path, created: list, modified: list, baseline_real: dict, run_id: str) -> dict:
    """Copia do workspace para o repositório real SOMENTE o que foi validado.
    Antes: confere que o real continua igual ao início (senão CONFLITO, nada é sobrescrito) e faz backup.
    Se algo falhar no meio, desfaz o que foi aplicado usando o backup."""
    project, ws = Path(project), Path(ws)
    bdir = BACKUPS / run_id
    conflicts = []
    for rel in modified:
        real = project / rel
        if not real.is_file() or sha256_file(real) != baseline_real.get(rel, (None, None))[1]:
            conflicts.append(f"{rel}: mudou desde o início da execução")
    for rel in created:
        if (project / rel).exists():
            conflicts.append(f"{rel}: já existe no repositório real")
    if conflicts:
        return {"ok": False, "conflicts": conflicts, "applied": [], "backup_dir": None}
    (bdir / "files").mkdir(parents=True, exist_ok=True)
    manifest = {"run_id": run_id, "created_at": now_iso(), "modified": {}, "created": {}, "state": "pending"}
    for rel in modified:
        dst = bdir / "files" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project / rel, dst)
        manifest["modified"][rel] = {"original_sha256": sha256_file(project / rel), "promoted_sha256": sha256_file(ws / rel)}
    for rel in created:
        manifest["created"][rel] = {"promoted_sha256": sha256_file(ws / rel)}
    (bdir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    token, applied, made_dirs = uuid.uuid4().hex[:8], [], []
    try:
        for rel in modified + created:
            if rel in created:
                parent = (project / rel).parent
                while not parent.exists() and parent != project:
                    made_dirs.append(parent)
                    parent = parent.parent
            _atomic_write(project / rel, (ws / rel).read_bytes(), token)
            applied.append(rel)
        for rel in applied:
            if sha256_file(project / rel) != sha256_file(ws / rel):
                raise OSError(f"verificação pós-gravação falhou: {rel}")
    except Exception as exc:  # noqa: BLE001 - qualquer falha: desfazer com o backup do próprio orquestrador
        for rel in applied:
            try:
                if rel in manifest["modified"]:
                    shutil.copyfile(bdir / "files" / rel, project / rel)
                else:
                    (project / rel).unlink()
            except OSError:
                pass
        for d in made_dirs:
            try:
                d.rmdir()
            except OSError:
                pass
        manifest["state"] = "rolled_back"
        (bdir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {"ok": False, "conflicts": [f"falha na gravação, desfeito com backup: {exc}"], "applied": [],
                "backup_dir": str(bdir)}
    manifest["state"] = "promoted"
    (bdir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"ok": True, "conflicts": [], "applied": applied, "backup_dir": str(bdir)}


def restore(project: Path, run_id: str, confirm: str) -> dict:
    """Restauração EXPLÍCITA de uma promoção. Só desfaz arquivos que ainda estão exatamente como foram promovidos;
    qualquer arquivo editado depois é preservado e relatado. Não usa git."""
    if confirm != f"RESTORE-{run_id}":
        return {"ok": False, "reason": f"confirmação deve ser RESTORE-{run_id}"}
    mf = BACKUPS / run_id / "manifest.json"
    if not mf.is_file():
        return {"ok": False, "reason": "backup não encontrado"}
    m = json.loads(mf.read_text(encoding="utf-8"))
    if m.get("state") != "promoted":
        return {"ok": False, "reason": f"estado do backup é {m.get('state')}; nada a restaurar"}
    project, done, kept = Path(project), [], []
    for rel, info in m["modified"].items():
        cur = project / rel
        if cur.is_file() and sha256_file(cur) == info["promoted_sha256"]:
            shutil.copyfile(BACKUPS / run_id / "files" / rel, cur)
            done.append(rel)
        else:
            kept.append(f"{rel}: alterado depois da promoção; preservado")
    for rel, info in m["created"].items():
        cur = project / rel
        if cur.is_file() and sha256_file(cur) == info["promoted_sha256"]:
            cur.unlink()
            done.append(rel)
        else:
            kept.append(f"{rel}: alterado ou ausente; preservado")
    m["state"] = "restored" if not kept else "restored_partial"
    m["restored_at"] = now_iso()
    mf.write_text(json.dumps(m, indent=2), encoding="utf-8")
    return {"ok": not kept, "restored": done, "preserved": kept}
