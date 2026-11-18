#!/usr/bin/env python3
"""Agente SIMULADO (claude/codex falsos) para testes da V3. Nunca contacta serviço algum.
Comportamento via FAKE_CLAUDE_MODE / FAKE_CODEX_MODE:
ok, quota, auth, technical, garbage, killed, hang, writes
Formatos de erro do Codex replicam a mensagem REAL capturada na V2; os do Claude são SUPOSIÇÕES (não observados)."""
import json, os, re, sys, time
name = os.path.basename(sys.argv[0])
a = sys.argv[1:]
if a[:1] in (["claude"], ["codex"]):  # shim .cmd do Windows passa o tipo como 1o argumento
    kind, a = a[0], a[1:]
else:
    kind = "codex" if "codex" in name else "claude"
mode = os.environ.get(f"FAKE_{kind.upper()}_MODE", "ok")
log = os.environ.get("FAKE_LOG")
if a[:1] == ["--version"]:
    print(f"{kind} 9.9.9 (simulado)"); sys.exit(0)
if kind == "claude" and a[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": True, "authMethod": "simulado"})); sys.exit(0)
if kind == "codex" and a[:2] == ["login", "status"]:
    print("Logged in using ChatGPT"); sys.exit(0)
prompt = sys.stdin.buffer.read().decode("utf-8", "replace")
# No Windows o executor entrega o prompt com CRLF (Popen em modo texto traduz \n -> \r\n); normaliza como um leitor real faria.
prompt = re.sub(r"\r+\n", "\n", prompt)
if log:
    open(log, "a").write(json.dumps({"agent": kind, "args": a, "handoff": "CONTEXTO DE TRANSFERÊNCIA" in prompt}) + "\n")
GOOD = {"summary": "s", "line_count": 12, "word_count": 99, "key_points": ["a"], "next_action": "n"}
if mode == "wrongcount":
    GOOD = {**GOOD, "line_count": 7}
if mode == "placeholder":  # reproduz a resposta real do Codex na V3.1: JSON válido com zeros
    GOOD = {"summary": "Não foi possível ler o arquivo.", "line_count": 0, "word_count": 0,
            "key_points": ["não acessado"], "next_action": "enviar o conteúdo"}
QMSG = "You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit https://chatgpt.com/settings/usage to purchase more credits or try again at 3:53 AM."
if mode in ("noshell", "encoding_error"):
    # Codex sem shell utilizável (política) ou com erro de codificação; só enxerga o que vier EMBUTIDO no prompt.
    m = re.search(r"<<<ARQUIVO [^\n]*\[[0-9a-f]{10}\]>>>\n(.*?)\n<<<FIM", prompt, re.S)
    if mode == "noshell" and m:
        txt = m.group(1)
        GOOD = {"summary": "lido do prompt", "line_count": sum(1 for l in txt.splitlines() if l.strip()),
                "word_count": len(txt.split()), "key_points": ["a"], "next_action": "n"}
    else:
        if mode == "noshell":
            sys.stderr.write('ERROR codex_core::tools::router: error=exec_command failed: CreateProcess { message: "Rejected(\\"powershell.exe -Command Get-Content\\" rejected: blocked by policy)" }\n')
        else:
            sys.stderr.write("UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f in position 12\n")
        GOOD = {"summary": "nao foi possivel ler", "line_count": -1, "word_count": -1, "key_points": [], "next_action": "n"}
# ---- V4: modos de ESCRITA (agem no diretório de trabalho = workspace isolado)
def _append(path, text):
    with open(path, "ab") as fh:
        fh.write(text.encode("utf-8"))


if mode.startswith(("w_", "p_")):
    real = os.environ.get("FAKE_REAL_REPO", "")
    changed = []
    if mode.startswith("w_"):
        if mode != "w_badvalid":
            _append("notas.txt", "Linha 4: acrescentada pelo agente simulado.\n"); changed.append("notas.txt")
            open("resultado.txt", "w").write("Resultado do agente simulado.\n"); changed.append("resultado.txt")
        if mode == "w_badvalid":
            _append("notas.txt", "Linha 9: texto sem o marcador esperado.\n"); changed.append("notas.txt")
        if mode == "w_mod_forbidden":
            _append("config.json", " "); changed.append("config.json")
        if mode == "w_del_forbidden":
            os.remove("README.txt")
        if mode == "w_create_forbidden":
            open("intruso.txt", "w").write("x"); changed.append("intruso.txt")
        if mode == "w_toobig":
            _append("notas.txt", "x" * 300000)
        if mode == "w_binary":
            open("notas.txt", "wb").write(b"abc\x00def")
        if mode == "w_outside":
            _append(os.path.join(real, "notas.txt"), "INVASAO DO REPOSITORIO REAL\n")
        if mode == "w_outside_untracked":
            _append(os.path.join(real, "rascunho_local.txt"), "ALTERADO PELO AGENTE\n")
        if mode == "w_then_hang":
            if os.environ.get("FAKE_PIDFILE"):
                open(os.environ["FAKE_PIDFILE"], "a").write(str(os.getpid()) + "\n")
            time.sleep(120)
        if mode == "w_then_quota":
            print(json.dumps({"is_error": True, "result": "Claude AI usage limit reached|1700000000"})); sys.exit(1)
        if mode == "w_then_kill":
            os._exit(137)
        GOOD = {"summary": "editado", "files_changed": changed, "notes": []}
    else:  # p_*: Codex só PROPÕE (read-only); o orquestrador aplica
        old = open("notas.txt", encoding="utf-8").read() if os.path.exists("notas.txt") else ""
        ch = [{"path": "notas.txt", "action": "modify", "content": old + "Linha 4: proposta pelo agente simulado.\n"},
              {"path": "resultado.txt", "action": "create", "content": "Resultado proposto pelo agente simulado.\n"}]
        if mode == "p_forbidden":
            ch.append({"path": "config.json", "action": "modify", "content": "{}"})
        if mode == "p_traversal":
            ch = [{"path": "../escape.txt", "action": "create", "content": "x"}]
        if mode == "p_writes":
            open("intruso.txt", "w").write("x")
        if mode == "p_badvalid":
            ch = [{"path": "notas.txt", "action": "modify", "content": old + "Linha 9: sem marcador.\n"}]
        GOOD = {"summary": "proposta", "changes": ch}

def out_codex_ok():
    o = a[a.index("--output-last-message") + 1]
    open(o, "w").write(json.dumps(GOOD)); print(json.dumps({"type": "turn.completed"}))
if mode == "hang":
    if os.environ.get("FAKE_PIDFILE"):
        open(os.environ["FAKE_PIDFILE"], "a").write(str(os.getpid()) + "\n")
    time.sleep(120)
if mode == "writes":
    open(os.path.join(os.getcwd(), "criado_pelo_agente.txt"), "w").write("x")
if mode == "quota":
    if kind == "codex":
        print(json.dumps({"type": "error", "message": QMSG})); print(json.dumps({"type": "turn.failed", "error": {"message": QMSG}}))
    else:
        print(json.dumps({"is_error": True, "result": "Claude AI usage limit reached|1700000000"}))
    sys.exit(1)
if mode == "auth":
    sys.stderr.write("Error: Not logged in. Please login.\n"); sys.exit(1)
if mode == "technical":
    sys.stderr.write("Error: read ECONNRESET (network error)\n"); sys.exit(1)
if mode == "overloaded":
    sys.stderr.write("API Error: 529 overloaded\n"); sys.exit(1)
if mode == "empty":
    sys.exit(0)
if mode == "garbage":
    print("{\"summary\": \"cortado no meio"); sys.exit(0)
if mode == "killed":
    print("{\"type\":\"turn.started\"}"); sys.stdout.flush(); os._exit(137)
if kind == "codex":
    out_codex_ok()
else:
    print(json.dumps({"is_error": False, "result": "ok", "structured_output": GOOD}))
