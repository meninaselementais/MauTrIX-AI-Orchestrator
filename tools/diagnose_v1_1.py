#!/usr/bin/env python3
"""Diagnóstico complementar V1.1 — SOMENTE LEITURA.

Faz:
  - Claude Code: lê 'claude --help' e 'claude auth --help' completos e confere a presença de flags
    de execução não interativa, permissões e saída estruturada. Roda 'claude auth status'.
  - Codex CLI: lê 'codex --help', 'codex exec --help', 'codex login --help' e
    'codex login status --help' completos; roda 'codex login status'; procura no texto de ajuda
    qualquer menção a uso/limite/cota.
  - Antigravity: busca LIMITADA (sem varredura recursiva do disco) em locais convencionais do
    Windows, atalhos do Menu Iniciar (profundidade <= 2), registro público de aplicativos
    (Uninstall/App Paths: nome, versão, editora, pasta de instalação) e PATH.

NÃO faz: executar tarefas/prompts, abrir arquivos de credenciais, listar o conteúdo de pastas de
configuração (só confirma que existem), instalar/desinstalar, usar rede, usar git, executar o
Antigravity.

Uso: python tools\\diagnose_v1_1.py
"""
import datetime
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diagnose as d  # noqa: E402  (reaproveita run/redact/first_line)

ROOT = d.ROOT
OUT = ROOT / "diagnostics"
HELP_DIR = OUT / "help"
BIG = 400000

CLAUDE_FLAGS = [
    "--print", "--output-format", "--input-format", "--json-schema", "--allowedTools",
    "--disallowedTools", "--permission-mode", "--permission-prompts", "--max-budget-usd",
    "--max-turns", "--continue", "--resume", "--append-system-prompt", "--add-dir", "--model",
    "--settings", "--mcp-config", "--bare", "--verbose", "--include-partial-messages",
]
CLAUDE_PRESENT_BUT_FORBIDDEN = ["--dangerously-skip-permissions"]
CODEX_EXEC_FLAGS = [
    "--json", "--sandbox", "--output-last-message", "--cd", "--skip-git-repo-check", "--model",
    "--output-schema", "--color", "--ephemeral", "--profile", "--config", "--ask-for-approval",
    "--full-auto",
]
CODEX_PRESENT_BUT_FORBIDDEN = ["--dangerously-bypass-approvals-and-sandbox"]
LIMIT_WORDS = re.compile(r"\b(usage|limit|limits|quota|rate|credit|credits|remaining)\b", re.I)


def has_flag(text: str, flag: str) -> bool:
    return re.search(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", text) is not None


def save_help(name: str, text: str) -> str:
    HELP_DIR.mkdir(parents=True, exist_ok=True)
    target = HELP_DIR / (name + ".txt")
    target.write_text(d.redact(text), encoding="utf-8")
    return str(target.relative_to(ROOT))


def get_help(path: str, argv: list, name: str) -> dict:
    r = d.run([path] + argv, limit=BIG, scrub=False)
    text = r["stdout"] + ("\n" + r["stderr"] if r["stderr"] else "")
    return {"ok": r["exit_code"] == 0, "exit_code": r["exit_code"], "timed_out": r["timed_out"],
            "error": r["error"], "text": text, "arquivo": save_help(name, text) if text else None}


def limit_lines(text: str) -> list:
    return [ln.strip()[:160] for ln in text.splitlines() if LIMIT_WORDS.search(ln)][:15]


def claude_section(agent: dict) -> dict:
    path = shutil.which("claude")
    res = {"executavel": path}
    if not path:
        return res
    main = get_help(path, ["--help"], "claude_help")
    auth_help = get_help(path, ["auth", "--help"], "claude_auth_help")
    res["help_principal"] = {k: main[k] for k in ("ok", "exit_code", "arquivo")}
    res["flags"] = {f: has_flag(main["text"], f) for f in CLAUDE_FLAGS}
    res["flags_presentes_mas_proibidas_pela_politica"] = {f: has_flag(main["text"], f) for f in CLAUDE_PRESENT_BUT_FORBIDDEN}
    res["auth_help"] = {"ok": auth_help["ok"], "arquivo": auth_help["arquivo"],
                        "subcomando_status_listado": has_flag(auth_help["text"], "status") or "status" in auth_help["text"]}
    res["autenticacao"] = d.check_auth(path, agent.get("auth_check"))
    res["linhas_sobre_uso_ou_limite_no_help"] = limit_lines(main["text"])
    return res


def codex_section(agent: dict) -> dict:
    path = shutil.which("codex")
    res = {"executavel": path}
    if not path:
        return res
    top = get_help(path, ["--help"], "codex_help")
    ex = get_help(path, ["exec", "--help"], "codex_exec_help")
    login = get_help(path, ["login", "--help"], "codex_login_help")
    lstatus = get_help(path, ["login", "status", "--help"], "codex_login_status_help")
    res["help_principal"] = {k: top[k] for k in ("ok", "exit_code", "arquivo")}
    res["exec_help"] = {k: ex[k] for k in ("ok", "exit_code", "arquivo")}
    res["login_help"] = {k: login[k] for k in ("ok", "exit_code", "arquivo")}
    res["login_status_help"] = {"ok": lstatus["ok"], "exit_code": lstatus["exit_code"], "arquivo": lstatus["arquivo"],
                                "primeiras_linhas": [ln.strip()[:160] for ln in lstatus["text"].splitlines() if ln.strip()][:8]}
    res["flags_exec"] = {f: has_flag(ex["text"], f) for f in CODEX_EXEC_FLAGS}
    res["flags_presentes_mas_proibidas_pela_politica"] = {f: has_flag(ex["text"] + top["text"], f) for f in CODEX_PRESENT_BUT_FORBIDDEN}
    res["subcomandos_listados_no_help_principal"] = [ln.strip()[:120] for ln in top["text"].splitlines()
                                                    if re.match(r"^\s{2}[a-z][\w-]*\s{2,}\S", ln)][:40]
    res["autenticacao"] = d.check_auth(path, {
        "argv": ["login", "status"], "documented_exit_semantics": False,
        "positive_regex": r"^\s*logged in", "keep_json_keys": [], "confirmacao": "observado_localmente"})
    res["linhas_sobre_uso_ou_limite_no_help"] = {
        "principal": limit_lines(top["text"]), "exec": limit_lines(ex["text"]), "login": limit_lines(login["text"])}
    return res


def env_dirs() -> dict:
    keys = ["LOCALAPPDATA", "APPDATA", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "USERPROFILE"]
    return {k: os.environ.get(k) for k in keys if os.environ.get(k)}


def match_names(directory: str, pattern) -> list:
    """Lista só NOMES de entradas no primeiro nível, filtrados. Não entra em subpastas."""
    try:
        return sorted(n for n in os.listdir(directory) if pattern.search(n))
    except OSError:
        return []


def executables_in(folder: str) -> list:
    found = []
    for sub in ("", "bin"):
        target = os.path.join(folder, sub) if sub else folder
        try:
            for n in os.listdir(target):
                if n.lower().endswith((".exe", ".cmd", ".bat")):
                    found.append(os.path.join(sub, n) if sub else n)
        except OSError:
            continue
    return sorted(found)[:40]


def start_menu_shortcuts(base: str, pattern, max_depth=2) -> list:
    hits = []
    base_depth = base.rstrip("\\/").count(os.sep)
    for current, dirs, files in os.walk(base):
        if current.count(os.sep) - base_depth >= max_depth:
            dirs[:] = []
        for f in files:
            if f.lower().endswith(".lnk") and pattern.search(f):
                hits.append(os.path.join(current, f))
    return hits[:20]


def registry_search(pattern) -> dict:
    try:
        import winreg
    except ImportError:
        return {"disponivel": False, "motivo": "winreg indisponível (não é Windows)"}
    out = {"disponivel": True, "uninstall": [], "app_paths": []}
    roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, sub in roots:
        try:
            key = winreg.OpenKey(hive, sub)
        except OSError:
            continue
        with key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, name) as app:
                        def val(v):
                            try:
                                return str(winreg.QueryValueEx(app, v)[0])
                            except OSError:
                                return None
                        display = val("DisplayName")
                        if display and pattern.search(display):
                            out["uninstall"].append({"hive": "HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "HKCU",
                                                     "DisplayName": display, "DisplayVersion": val("DisplayVersion"),
                                                     "Publisher": val("Publisher"), "InstallLocation": val("InstallLocation")})
                except OSError:
                    continue
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths")
        except OSError:
            continue
        with key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    name = winreg.EnumKey(key, i)
                except OSError:
                    continue
                if pattern.search(name):
                    out["app_paths"].append(name)
    return out


def antigravity_section() -> dict:
    pat = re.compile(r"antigravity|^agy(\.|$)", re.I)
    env = env_dirs()
    res = {"path": {n: shutil.which(n) for n in ("agy", "antigravity", "Antigravity")}, "pastas_convencionais": [],
           "atalhos": [], "registro": None, "pastas_de_usuario_apenas_existencia": {}}
    bases = []
    if env.get("LOCALAPPDATA"):
        bases += [os.path.join(env["LOCALAPPDATA"], "Programs"), env["LOCALAPPDATA"]]
    for k in ("ProgramFiles", "ProgramFiles(x86)"):
        if env.get(k):
            bases.append(env[k])
    seen = set()
    for base in bases:
        for name in match_names(base, pat):
            full = os.path.join(base, name)
            if full in seen:
                continue
            seen.add(full)
            res["pastas_convencionais"].append({"pasta": full, "e_diretorio": os.path.isdir(full),
                                                "executaveis": executables_in(full) if os.path.isdir(full) else []})
    menus = []
    if env.get("APPDATA"):
        menus.append(os.path.join(env["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs"))
    if env.get("ProgramData"):
        menus.append(os.path.join(env["ProgramData"], "Microsoft", "Windows", "Start Menu", "Programs"))
    if env.get("USERPROFILE"):
        menus.append(os.path.join(env["USERPROFILE"], "Desktop"))
    for m in menus:
        res["atalhos"] += start_menu_shortcuts(m, pat)
    res["registro"] = registry_search(re.compile(r"antigravity", re.I))
    home = env.get("USERPROFILE")
    if home:
        for name in match_names(home, re.compile(r"antigravity|^\.gemini$", re.I)):
            res["pastas_de_usuario_apenas_existencia"][name] = os.path.isdir(os.path.join(home, name))
    if env.get("APPDATA"):
        for name in match_names(env["APPDATA"], pat):
            res["pastas_de_usuario_apenas_existencia"]["APPDATA\\" + name] = os.path.isdir(os.path.join(env["APPDATA"], name))
    res["observacao"] = ("Pastas de usuário (.antigravity-ide, .gemini, APPDATA) são só confirmadas como existentes; "
                         "seu conteúdo não foi listado nem aberto. Existência dessas pastas não prova instalação atual.")
    return res


def main() -> None:
    config = json.loads(d.CONFIG.read_text(encoding="utf-8"))
    agents = {a["id"]: a for a in config["agents"]}
    now = datetime.datetime.now()
    report = {
        "gerado_em": now.isoformat(timespec="seconds"),
        "versao_script": "1.1",
        "claude_code": claude_section(agents["claude_code"]),
        "codex_cli": codex_section(agents["codex_cli"]),
        "antigravity": antigravity_section(),
        "aviso": "Nenhuma tarefa foi executada. Nenhum token, cookie ou arquivo de credenciais foi aberto.",
    }
    OUT.mkdir(exist_ok=True)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    (OUT / f"diagnostico_v1_1_{now.strftime('%Y%m%d_%H%M%S')}.json").write_text(text, encoding="utf-8")
    (OUT / "v1_1_ultimo.json").write_text(text, encoding="utf-8")

    def yes_no(flags):
        return ", ".join(f"{k}={'sim' if v else 'não'}" for k, v in flags.items())
    lines = [f"# Diagnóstico V1.1 — {report['gerado_em']}", ""]
    c, x, a = report["claude_code"], report["codex_cli"], report["antigravity"]
    if c.get("flags"):
        lines += ["## Claude Code — flags no --help local", yes_no(c["flags"]), ""]
    if x.get("flags_exec"):
        lines += ["## Codex — flags em 'codex exec --help'", yes_no(x["flags_exec"]), "",
                  f"Autenticação Codex: {x['autenticacao']['state']} ({x['autenticacao'].get('primeira_linha', '')})", ""]
    lines += ["## Antigravity", f"PATH: {a['path']}", f"Pastas convencionais: {len(a['pastas_convencionais'])}",
              f"Atalhos: {len(a['atalhos'])}",
              f"Registro (Uninstall): {len((a['registro'] or {}).get('uninstall', []))}", ""]
    (OUT / "v1_1_ultimo.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print("Gravado em:", OUT)


if __name__ == "__main__":
    main()
