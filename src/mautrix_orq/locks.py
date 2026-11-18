"""Locks: um agente por vez (lock global) e um executor por projeto (lock por projeto).

Criação atômica com O_CREAT|O_EXCL. Um lock existente NUNCA é removido automaticamente: pode haver
uma execução em andamento. Se ficou órfão, o usuário remove manualmente depois de conferir.
"""
import hashlib
import json
import os
import time
from pathlib import Path

from .common import LOCKS, now_iso


class LockError(Exception):
    pass


def _project_slug(project: Path) -> str:
    digest = hashlib.sha1(str(project).lower().encode("utf-8")).hexdigest()[:10]
    return f"project_{project.name}_{digest}".replace(" ", "_")


class RunLocks:
    def __init__(self, project: Path, task_id: str, agent: str, max_age_hint_s: int):
        self.paths = [LOCKS / "_global_agent.lock", LOCKS / f"{_project_slug(project)}.lock"]
        self.meta = {"task_id": task_id, "agent": agent, "pid": os.getpid(), "project": str(project)}
        self.max_age_hint_s = max_age_hint_s
        self.held = []

    def __enter__(self):
        LOCKS.mkdir(parents=True, exist_ok=True)
        try:
            for path in self.paths:
                self._acquire(path)
        except LockError:
            self.release()
            raise
        return self

    def _acquire(self, path: Path) -> None:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            age = int(time.time() - path.stat().st_mtime)
            try:
                holder = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                holder = {}
            hint = ""
            if age > self.max_age_hint_s:
                hint = (f" O lock tem {age}s (acima do esperado): pode estar órfão. Confira se nenhum agente "
                        f"está rodando e remova o arquivo manualmente.")
            raise LockError(f"lock ativo: {path.name} (tarefa {holder.get('task_id')}, agente "
                            f"{holder.get('agent')}).{hint}")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({**self.meta, "acquired_at": now_iso()}, fh)
        self.held.append(path)

    def release(self) -> None:
        for path in reversed(self.held):
            try:
                path.unlink()
            except OSError:
                pass
        self.held = []

    def __exit__(self, *exc):
        self.release()
        return False
