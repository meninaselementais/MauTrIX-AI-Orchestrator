"""Classificação de resultados de execução.

Separa claramente: sucesso, bloqueio por lock (BUSY), limite de uso, erro de autenticação, erro técnico,
timeout e resultado desconhecido. Só mensagens de limite CONFIRMADAS (padrões fortes) viram QUOTA_LIMITED.
Respostas transitórias (429, overloaded, rede) são erro técnico, nunca limite de uso.
"""
import re

from .common import redact

SUCCESS = "SUCCESS"
BUSY = "BUSY"
QUOTA_LIMITED = "QUOTA_LIMITED"
AUTH_ERROR = "AUTH_ERROR"
TECHNICAL_ERROR = "TECHNICAL_ERROR"
TIMEOUT = "TIMEOUT"
UNKNOWN_RESULT = "UNKNOWN_RESULT"
VIOLATION = "VIOLATION"
POLICY_REJECTED = "POLICY_REJECTED"

# Veredito da TAREFA (separado do sucesso técnico da execução).
# EXECUTION_SUCCESS = o processo executou e devolveu resultado estruturado sem efeitos colaterais (outcome SUCCESS).
# TASK_ACCEPTED     = todos os critérios obrigatórios atendidos.
# TASK_REJECTED     = executou, mas um ou mais critérios obrigatórios falharam (nunca é "concluída com sucesso").
# TASK_UNVERIFIED   = nenhum critério falhou, mas algum não pôde ser verificado pelo orquestrador.
# NOT_EVALUATED     = a execução não chegou a produzir resultado avaliável.
TASK_ACCEPTED = "TASK_ACCEPTED"
TASK_REJECTED = "TASK_REJECTED"
TASK_UNVERIFIED = "TASK_UNVERIFIED"
NOT_EVALUATED = "NOT_EVALUATED"


def task_verdict(acceptance_result: list) -> str:
    mets = [r["met"] for r in acceptance_result]
    if "no" in mets:
        return TASK_REJECTED
    if not mets or "not_verified" in mets:
        return TASK_UNVERIFIED
    return TASK_ACCEPTED

# Padrão forte. 'hit your usage limit' / 'purchase more credits' foram observados em mensagem real do Codex (V2).
# 'usage limit reached' (Claude) e 'rate_limit' (evento documentado do Claude) ainda NÃO foram observados localmente.
QUOTA_STRONG = re.compile(
    r"(hit your usage limit|usage limit (reached|exceeded)|purchase more credits|quota (exceeded|exhausted)|"
    r"out of (credits|usage)|\brate_limit\b)", re.I)
AUTH = re.compile(
    r"(not logged in|please (log ?in|run .*login)|login required|unauthori[sz]ed|\b401\b|invalid (api key|credentials)|"
    r"authentication (failed|required|error)|token (expired|invalid)|account_on_hold|billing_error)", re.I)
TRANSIENT = re.compile(
    r"(overloaded|too many requests|\b429\b|http 5\d\d|status 5\d\d|econnreset|etimedout|enotfound|"
    r"network error|connection (reset|refused|closed)|temporarily unavailable|socket hang up)", re.I)
# Bloqueio de política do shell do agente (ex.: Codex no Windows: "CreateProcess Rejected … blocked by policy").
# NÃO é erro de codificação, NÃO é cota e NÃO é erro de autenticação.
POLICY = re.compile(r"(blocked by policy|rejected: [^\n]{0,80}policy|CreateProcess\b[^\n]{0,40}\bRejected)", re.I)
# Erro de codificação de texto (decodificação/codificação), distinto de política.
ENCODING = re.compile(r"(UnicodeDecodeError|UnicodeEncodeError|codec can.t (de|en)code|invalid utf-?8|\bcharmap\b)", re.I)
MOJIBAKE = re.compile(r"(Ã[\u0080-\u00bf]|â€|�)")


def looks_mojibake(text: str) -> bool:
    return bool(MOJIBAKE.search(text or ""))


RETRY_HINT = re.compile(r"try again (?:at|in) ([^.\"}\n]{1,30})", re.I)


def classify_text(text: str) -> dict:
    """kind: quota | auth | transient | None. 'confirmed' só para quota/auth (padrões fortes)."""
    text = text or ""
    for kind, rx in (("quota", QUOTA_STRONG), ("auth", AUTH), ("policy", POLICY), ("encoding", ENCODING),
                     ("transient", TRANSIENT)):
        if rx.search(text):
            hint = RETRY_HINT.search(text) if kind == "quota" else None
            return {"kind": kind, "confirmed": kind != "transient", "raw": redact(text.strip())[:400],
                    "retry_hint_reported_by_agent": hint.group(1).strip() if hint else None}
    return {"kind": None, "confirmed": False, "raw": redact(text.strip())[:400], "retry_hint_reported_by_agent": None}


def can_transfer(report: dict):
    """(permitido, motivo). Regra conservadora: só transfere quando é seguro afirmar que nada aconteceu."""
    if report.get("failure_kind") == "input_encoding":
        return False, "arquivo de contexto não é UTF-8 válido; o problema é do arquivo, não do agente"
    if report.get("side_effects"):
        return False, "arquivos do laboratório mudaram; efeito colateral possível"
    outcome = report.get("outcome")
    started = report.get("agent_started", True)
    if outcome == BUSY:
        return False, "projeto ocupado por outra execução"
    if not started and outcome in (AUTH_ERROR, TECHNICAL_ERROR):
        return True, "falha antes de iniciar o agente (nenhuma tarefa executada)"
    if outcome in (QUOTA_LIMITED, AUTH_ERROR) and report.get("agent_output") is None and not report.get("timed_out"):
        return True, "limite de uso/autenticação confirmado, sem saída e sem alterações"
    return False, f"resultado {outcome} não permite repetir com segurança (resultado desconhecido ou erro técnico)"
