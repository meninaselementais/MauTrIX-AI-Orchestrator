#!/usr/bin/env python3
"""Diagnóstico SOMENTE LEITURA dos agentes de programação instalados.

O que faz:
  - localiza executáveis no PATH;
  - roda '<cmd> --version' e '<cmd> --help' (com limite de tempo, sem stdin);
  - roda o comando de status de autenticação SOMENTE se estiver em config/agents.json;
  - procura no --help os marcadores de execução não interativa;
  - grava o resultado em diagnostics/ (UTF-8).

O que NÃO faz:
  - não lê tokens, cookies, chaves, keyring nem arquivos de configuração dos agentes;
  - não imprime nem grava variáveis de ambiente;
  - não acessa a rede por conta própria;
  - não executa nenhum prompt, não altera nenhum projeto, não usa git;
  - não consulta cota (isso é sempre 'STATUS DESCONHECIDO' sem fonte oficial).

Uso: python tools\\diagnose.py [--allow-gui]
"""
import datetime
import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "agents.json"
OUT = ROOT / "diagnostics"
TIMEOUT_S = 20
MAX_CHARS = 3000

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
LONG_TOKEN = re.compile(r"[A-Za-z0-9_\-]{32,}")
UNSUPPORTED = re.compile(r"(unknown|unrecognized|invalid|unexpected)\s+(command|option|subcommand|argument)", re.I)


def redact(text: str) -> str:
    return LONG_TOKEN.sub("<redigido>", EMAIL.sub("<email>", text or ""))


def run(argv, limit=MAX_CHARS, scrub=True):
    """limit/scrub: o texto de ajuda completo (limit grande, scrub=False) é usado só em memória
    para procurar marcadores; V1 truncava o --help em 3000 caracteres e gerou falso negativo."""
    info = {"argv": [Path(argv[0]).name] + argv[1:], "exit_code": None, "stdout": "", "stderr": "",
            "timed_out": False, "error": None}
    try:
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=TIMEOUT_S, stdin=subprocess.DEVNULL)
        info["exit_code"] = p.returncode
        info["stdout"] = (redact(p.stdout) if scrub else p.stdout)[:limit]
        info["stderr"] = (redact(p.stderr) if scrub else p.stderr)[:limit]
    except subprocess.TimeoutExpired:
        info["timed_out"] = True
        info["error"] = f"tempo esgotado ({TIMEOUT_S}s)"
    except OSError as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def check_auth(path, spec):
    if not spec:
        return {"state": "DESCONHECIDO", "motivo": "sem comando de status documentado"}
    result = run([path] + spec["argv"])
    blob = result["stdout"] + "\n" + result["stderr"]
    kept = {}
    try:
        data = json.loads(result["stdout"])
        if isinstance(data, dict):
            kept = {k: data[k] for k in spec.get("keep_json_keys", []) if k in data}
    except ValueError:
        pass
    if result["timed_out"] or result["error"]:
        state = "INDETERMINADO"
    elif UNSUPPORTED.search(blob):
        state = "COMANDO_NAO_SUPORTADO"
    elif spec.get("documented_exit_semantics"):
        state = "AUTENTICADO" if result["exit_code"] == 0 else "NAO_AUTENTICADO"
    elif (spec.get("positive_regex") and result["exit_code"] == 0
          and re.search(spec["positive_regex"], blob, re.I | re.M)
          and not re.search(r"not\s+logged|logged\s+out|no\s+credentials", blob, re.I)):
        # Evidência positiva explícita impressa pelo próprio comando de status. Só vale como
        # AUTENTICADO; ausência dela continua INDETERMINADO (o caso negativo não foi observado).
        state = "AUTENTICADO"
    else:
        state = "INDETERMINADO"
    return {"state": state, "exit_code": result["exit_code"], "campos_permitidos": kept,
            "primeira_linha": first_line(result["stdout"] or result["stderr"])[:120] if not kept else "",
            "confirmacao_da_fonte": spec.get("confirmacao"), "erro": result["error"]}


def diagnose(agent, allow_gui):
    out = {"id": agent["id"], "display": agent["display"], "instalado": False, "caminho": None,
           "versao": None, "autenticacao": None, "execucao_nao_interativa": None,
           "cota": {"status": agent["quota"]["status"], "motivo": agent["quota"]["motivo"]},
           "notas": []}
    path = None
    for cmd in agent["commands"]:
        path = shutil.which(cmd)
        if path:
            break
    if not path:
        out["notas"].append("Executável não encontrado no PATH: " + ", ".join(agent["commands"]))
        return out
    out["instalado"] = True
    out["caminho"] = path
    if agent.get("gui_risk") and not allow_gui:
        out["versao"] = "NAO_EXECUTADO (aplicativo gráfico; use --allow-gui para tentar)"
        out["autenticacao"] = {"state": "DESCONHECIDO", "motivo": "aplicativo gráfico não executado"}
        out["execucao_nao_interativa"] = {"suportada_segundo_o_help": None, "motivo": "não executado"}
        return out

    version = run([path] + agent["version_args"])
    out["versao"] = first_line(version["stdout"] or version["stderr"]) if version["exit_code"] == 0 else \
        "ERRO: " + str(version["error"] or f"codigo {version['exit_code']}")

    help_run = run([path, "--help"], limit=300000, scrub=False)
    help_text = help_run["stdout"] + "\n" + help_run["stderr"]
    markers = agent["headless"].get("markers_no_help", [])
    evidence = {}
    for marker in markers:
        lines = [ln.strip()[:160] for ln in help_text.splitlines() if marker in ln]
        evidence[marker] = lines[:3]
    out["execucao_nao_interativa"] = {
        "confirmacao_da_fonte": agent["headless"].get("confirmacao"),
        "invocacao_esperada": agent["headless"].get("invocacao"),
        "marcadores_encontrados_no_help_local": {m: bool(v) for m, v in evidence.items()},
        "evidencia": evidence,
        "help_executou": help_run["exit_code"] == 0,
    }
    out["autenticacao"] = check_auth(path, agent.get("auth_check"))
    return out


def main():
    allow_gui = "--allow-gui" in sys.argv
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    now = datetime.datetime.now()
    git = shutil.which("git")
    git_version = first_line(run([git, "--version"])["stdout"]) if git else None
    report = {
        "gerado_em": now.isoformat(timespec="seconds"),
        "sistema": platform.platform(),
        "python": sys.version.split()[0],
        "git": git_version,
        "agentes": [diagnose(a, allow_gui) for a in config["agents"]],
        "aviso": "Cota: STATUS DESCONHECIDO para todos os agentes. Nenhum token, cookie ou arquivo de autenticação foi lido.",
    }
    OUT.mkdir(exist_ok=True)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    text = json.dumps(report, indent=2, ensure_ascii=False)
    (OUT / f"diagnostico_{stamp}.json").write_text(text, encoding="utf-8")
    (OUT / "ultimo.json").write_text(text, encoding="utf-8")

    lines = [f"# Diagnóstico — {report['gerado_em']}", "", f"Sistema: {report['sistema']} | Python {report['python']} | Git: {report['git']}", "",
             "| Agente | Instalado | Versão | Autenticação | Cota |", "|---|---|---|---|---|"]
    for a in report["agentes"]:
        auth = (a["autenticacao"] or {}).get("state", "-")
        lines.append(f"| {a['display']} | {'sim' if a['instalado'] else 'não'} | {a['versao'] or '-'} | {auth} | {a['cota']['status']} |")
    (OUT / "ultimo.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nGravado em: {OUT}")


if __name__ == "__main__":
    main()
