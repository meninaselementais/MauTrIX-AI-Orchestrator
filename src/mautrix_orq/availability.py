"""Gerenciador de disponibilidade dos agentes.

AVAILABLE_VERIFIED só nasce de uma execução real bem-sucedida e EXPIRA. Nunca significa saldo garantido.
Autenticação confirmada NÃO é prova de cota: preflight bem-sucedido deixa o estado como UNKNOWN.
Não há contagem de tokens nem horário de renovação inventado; a dica que o agente imprimir é guardada como texto.
"""
import datetime
import json
import os

from .common import FAILOVER_CONFIG, LOCKS, STATE, now_iso

STATES = ("AVAILABLE_VERIFIED", "QUOTA_LIMITED", "AUTH_ERROR", "TECHNICAL_ERROR", "BUSY", "UNKNOWN")
DEFAULT_TTL = {"AVAILABLE_VERIFIED": 900, "QUOTA_LIMITED": 1800, "AUTH_ERROR": 600, "TECHNICAL_ERROR": 600}
STATE_FILE = STATE / "availability.json"
NOTE = "Disponibilidade verificada não garante saldo ou cota para a próxima tarefa."


def load_failover_config() -> dict:
    cfg = json.loads(FAILOVER_CONFIG.read_text(encoding="utf-8"))
    cfg.setdefault("ttl_seconds", {})
    cfg["ttl_seconds"] = {**DEFAULT_TTL, **cfg["ttl_seconds"]}
    return cfg


def _load() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def _parse(ts: str):
    return datetime.datetime.fromisoformat(ts)


def get(agent: str, now: datetime.datetime = None) -> dict:
    now = now or datetime.datetime.now().astimezone()
    rec = _load().get(agent)
    if not rec:
        return {"state": "UNKNOWN", "note": "sem verificação registrada"}
    if rec.get("state") == "AVAILABLE_VERIFIED" and rec.get("record_schema") != 2:
        # registro gravado antes da V3.2, quando sucesso técnico podia ser confundido com tarefa aprovada
        return {"state": "UNKNOWN", "note": "registro AVAILABLE_VERIFIED anterior à V3.2 ignorado; reverificar"}
    if _parse(rec["expires_at"]) <= now:
        return {"state": "UNKNOWN", "note": f"registro {rec['state']} expirou; reverificar", "previous": rec["state"]}
    return rec


def set_state(agent: str, state: str, source: str, detail: str = "", retry_hint: str = None, ttl: int = None):
    assert state in STATES
    ttl = ttl if ttl is not None else load_failover_config()["ttl_seconds"].get(state, 600)
    now = datetime.datetime.now().astimezone()
    data = _load()
    data[agent] = {"state": state, "since": now.isoformat(timespec="seconds"),
                   "expires_at": (now + datetime.timedelta(seconds=ttl)).isoformat(timespec="seconds"),
                   "ttl_seconds": ttl, "source": source, "record_schema": 2, "detail": detail[:300],
                   "retry_hint_reported_by_agent": retry_hint,
                   "note": NOTE if state == "AVAILABLE_VERIFIED" else
                   "dica do agente (se houver) é só informativa e não é usada em decisões"}
    _save(data)


def is_busy() -> bool:
    return (LOCKS / "_global_agent.lock").exists()


def update_from_report(report: dict) -> None:
    from . import outcomes as o  # evita import circular
    agent, outcome = report.get("agent"), report.get("outcome")
    src = report.get("run_id", "")
    limit = report.get("limit") or {}
    mapping = {o.SUCCESS: "AVAILABLE_VERIFIED", o.QUOTA_LIMITED: "QUOTA_LIMITED", o.AUTH_ERROR: "AUTH_ERROR",
               o.TECHNICAL_ERROR: "TECHNICAL_ERROR", o.TIMEOUT: "TECHNICAL_ERROR",
               o.UNKNOWN_RESULT: "TECHNICAL_ERROR", o.VIOLATION: "TECHNICAL_ERROR"}
    if outcome == o.SUCCESS and report.get("task_verdict") != o.TASK_ACCEPTED:
        return  # executou, mas a tarefa não foi aprovada: não prova disponibilidade útil nem indisponibilidade
    if outcome in mapping and agent:
        set_state(agent, mapping[outcome], source=src, detail=f"outcome={outcome}",
                  retry_hint=limit.get("retry_hint_reported_by_agent"))


def select(priority: list, agents_cfg: dict):
    """Retorna (elegíveis em ordem de prioridade, [(agente, motivo)] ignorados)."""
    eligible, skipped = [], []
    for agent in priority:
        spec = agents_cfg.get(agent)
        if not spec or not spec.get("enabled", False):
            skipped.append((agent, "desativado na configuração"))
            continue
        st = get(agent)["state"]
        if st in ("AVAILABLE_VERIFIED", "UNKNOWN"):
            eligible.append(agent)
        else:
            skipped.append((agent, f"estado {st} ainda válido"))
    return eligible, skipped


def snapshot_all(agent_ids) -> dict:
    out = {a: get(a) for a in agent_ids}
    if is_busy():
        out["_projeto"] = {"state": "BUSY", "note": "lock global ativo"}
    return out
