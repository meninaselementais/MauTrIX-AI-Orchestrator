#!/usr/bin/env python3
"""Testes V3 com agentes SIMULADOS (Linux/macOS). Cria uma cópia temporária do orquestrador; nunca toca no
estado real, no jogo nem em agentes reais (MAUTRIX_TEST_MODE=1 restringe executáveis à pasta de fakes).
Uso: python3 tests/test_v3_simulated.py"""
import glob, hashlib, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="mxv3_"))
ROOT, BIN = TMP / "root", TMP / "bin"
LOG = TMP / "fake.log"
PIDS = TMP / "hang_pids.txt"
results = []


def setup():
    shutil.copytree(SRC, ROOT, ignore=shutil.ignore_patterns("reports", "runs", "logs", "locks", "state", "handoffs",
                                                            "diagnostics", "__pycache__", "tests", ".git"))
    for d in ("reports", "runs", "logs", "locks", "state", "handoffs"):
        (ROOT / d).mkdir(exist_ok=True)
    BIN.mkdir()
    shutil.copy(SRC / "tests/fakes/fake_agent.py", BIN / "fake_agent.py")
    for n in ("claude", "codex"):
        if os.name == "nt":  # shim .cmd; MX_PY aponta para o Python em uso
            (BIN / f"{n}.cmd").write_text(f'@"%MX_PY%" "%~dp0fake_agent.py" {n} %*\r\n', encoding="ascii")
        else:
            shutil.copy(SRC / "tests/fakes/fake_agent.py", BIN / n); (BIN / n).chmod(0o755)
    (ROOT / "config/agents.json").write_text(json.dumps({"agents": [
        {"id": "claude_code", "commands": ["claude"], "version_args": ["--version"], "enabled": True},
        {"id": "codex_cli", "commands": ["codex"], "version_args": ["--version"], "enabled": True},
        {"id": "antigravity_cli", "commands": ["agy"], "enabled": False}]}), encoding="utf-8")
    task = json.loads((SRC / "instructions/TASK-0001_claude_lab.json").read_text(encoding="utf-8"))
    task.update(task_id="TASK-0003", agent="any_available", project_path=str(ROOT / "lab/projeto_descartavel"))
    task["limits"] = {"timeout_seconds": 4, "max_attempts": 1}
    (ROOT / "instructions/T3.json").write_text(json.dumps(task), encoding="utf-8")
    (ROOT / "instructions/TASK-0003_failover_lab.json").write_text(json.dumps(task), encoding="utf-8")
    t4 = {**task, "task_id": "TASK-0004", "agent": "codex_cli"}
    (ROOT / "instructions/T4.json").write_text(json.dumps(t4), encoding="utf-8")


def env(**modes):
    e = dict(os.environ, MAUTRIX_ROOT=str(ROOT), MAUTRIX_TEST_MODE="1", MAUTRIX_TEST_BIN=str(BIN), FAKE_LOG=str(LOG),
             PATH=f"{BIN}{os.pathsep}{os.environ['PATH']}", FAKE_CLAUDE_MODE="ok", FAKE_CODEX_MODE="ok",
             MX_PY=sys.executable, PYTHONIOENCODING="utf-8", FAKE_PIDFILE=str(PIDS))
    e.update({k: v for k, v in modes.items()})
    return e


CODEX_CFG = {}


def write_agents(**codex_extra):
    CODEX_CFG.clear(); CODEX_CFG.update(codex_extra)
    (ROOT / "config/agents.json").write_text(json.dumps({"agents": [
        {"id": "claude_code", "commands": ["claude"], "version_args": ["--version"], "enabled": True},
        {"id": "codex_cli", "commands": ["codex"], "version_args": ["--version"], "enabled": True, **codex_extra},
        {"id": "antigravity_cli", "commands": ["agy"], "enabled": False}]}), encoding="utf-8")


def reset(priority=("codex_cli", "claude_code")):
    write_agents()
    for d in ("reports", "runs", "logs", "locks", "state", "handoffs"):
        shutil.rmtree(ROOT / d, ignore_errors=True); (ROOT / d).mkdir()
    for f in (ROOT / "lab/projeto_descartavel").iterdir():
        if f.name not in ("texto_exemplo.txt", "LEIA-ME.txt"):
            f.unlink()
    cfg = json.loads((SRC / "config/failover.json").read_text(encoding="utf-8")); cfg["priority"] = list(priority)
    (ROOT / "config/failover.json").write_text(json.dumps(cfg), encoding="utf-8")
    LOG.write_text("")


def failover(**modes):
    p = subprocess.run([sys.executable, str(ROOT / "tools/supervisor.py"), "failover", str(ROOT / "instructions/T3.json"),
                        "--confirm", "TASK-0003"], capture_output=True, text=True, encoding="utf-8", env=env(**modes))
    try:
        return json.loads(p.stdout)
    except ValueError:
        return {"state": "CLI_ERROR", "final_reason": (p.stdout + p.stderr)[-500:], "steps": []}


def calls():
    return [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]


def avail(agent):
    f = ROOT / "state/availability.json"
    return json.loads(f.read_text()).get(agent, {}).get("state") if f.exists() else None


def labhash():
    h = {}
    for f in sorted((ROOT / "lab").rglob("*")):
        if f.is_file():
            h[str(f.relative_to(ROOT))] = hashlib.sha256(f.read_bytes()).hexdigest()
    return h


def pid_list():
    return [int(x) for x in PIDS.read_text().split()] if PIDS.exists() else []


def pid_alive(pid):
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def run_all():
    setup()
    base = labhash()
    # A
    reset(); r = failover()
    check("A Codex disponível e tarefa concluída", r["state"] == "completed" and [c["agent"] for c in calls()] == ["codex"]
          and avail("codex_cli") == "AVAILABLE_VERIFIED", r)
    # B
    reset(); r = failover(FAKE_CODEX_MODE="quota"); cs = calls()
    check("B Codex limite -> transfere ao Claude", r["state"] == "completed_after_transfer"
          and [c["agent"] for c in cs] == ["codex", "claude"] and cs[1]["handoff"] and avail("codex_cli") == "QUOTA_LIMITED"
          and avail("claude_code") == "AVAILABLE_VERIFIED" and len(r["handoffs"]) == 1, r)
    # C
    reset(priority=("claude_code", "codex_cli")); r = failover(FAKE_CLAUDE_MODE="quota"); cs = calls()
    check("C Claude limite -> transfere ao Codex", r["state"] == "completed_after_transfer"
          and [c["agent"] for c in cs] == ["claude", "codex"] and avail("claude_code") == "QUOTA_LIMITED", r)
    # D
    reset(); r = failover(FAKE_CODEX_MODE="quota", FAKE_CLAUDE_MODE="quota"); n1 = len(calls())
    r2 = failover(FAKE_CODEX_MODE="ok", FAKE_CLAUDE_MODE="ok")
    check("D Ambos indisponíveis: interrompe", r["state"] == "stopped_no_agent" and n1 == 2, r)
    check("D2 Segunda tentativa não reexecuta agentes em QUOTA_LIMITED válido", r2["state"] == "stopped_no_agent"
          and len(calls()) == n1, r2)
    # E
    reset(); r = failover(FAKE_CODEX_MODE="technical")
    check("E Erro técnico NÃO é limite e NÃO transfere", r["state"] == "stopped_unknown_result"
          and [c["agent"] for c in calls()] == ["codex"] and avail("codex_cli") == "TECHNICAL_ERROR", r)
    reset(); r = failover(FAKE_CODEX_MODE="overloaded")
    check("E2 overloaded/529 é técnico, não limite", avail("codex_cli") == "TECHNICAL_ERROR"
          and len(calls()) == 1, r)
    # F
    reset(); r = failover(FAKE_CODEX_MODE="garbage")
    check("F Saída inválida (código 0): sem transferir", r["state"] == "stopped_unknown_result" and len(calls()) == 1, r)
    r2 = failover(); n = len(calls())
    check("F2 Mesma tarefa bloqueada até revisão humana", r2["state"] == "rejected" and "bloqueia" in r2["final_reason"]
          and n == 1, r2)
    reset(); r = failover(FAKE_CODEX_MODE="killed")
    check("F3 Processo morto no meio: sem transferir", r["state"] == "stopped_unknown_result" and len(calls()) == 1, r)
    reset(); rec = {"transfer_id": "TRANSFER-x", "task_id": "TASK-0003", "state": "in_progress"}
    (ROOT / "reports/TRANSFER-x-TASK-0003.json").write_text(json.dumps(rec)); r = failover()
    check("F4 Transferência interrompida (in_progress) bloqueia reexecução", r["state"] == "rejected" and not calls(), r)
    # G
    reset(); (ROOT / "locks/_global_agent.lock").write_text('{"task_id":"OUTRA"}'); r = failover()
    check("G Lock existente impede execução e não é removido", r["state"] == "stopped_busy" and not calls()
          and (ROOT / "locks/_global_agent.lock").exists(), r)
    reset()
    bg = subprocess.Popen([sys.executable, str(ROOT / "tools/supervisor.py"), "failover", str(ROOT / "instructions/T3.json"),
                           "--confirm", "TASK-0003"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          encoding="utf-8", env=env(FAKE_CODEX_MODE="hang"))
    time.sleep(1.5); r = failover()
    out, _ = bg.communicate(timeout=60)
    check("G2 Execução simultânea recusada enquanto outra roda", r["state"] == "stopped_busy", r)
    check("G3 Primeira execução terminou por timeout e liberou locks", "stopped_unknown_result" in out
          and not list((ROOT / "locks").iterdir()), out[-300:])
    # H
    reset(); r = failover(FAKE_CODEX_MODE="hang")
    rep = json.loads(Path(sorted(glob.glob(str(ROOT / "reports/RUN-*codex*.json")))[0]).read_text(encoding="utf-8"))
    check("H Timeout: outcome TIMEOUT, parada segura, locks liberados", rep["outcome"] == "TIMEOUT"
          and r["state"] == "stopped_unknown_result" and not list((ROOT / "locks").iterdir()) and len(calls()) == 1, rep["outcome"])
    time.sleep(1.0); alive = [p for p in pid_list() if pid_alive(p)]
    check("H2 Processo do agente foi encerrado", alive == [] and pid_list() != [], alive)
    (ROOT / "reports/resolved").mkdir(); [shutil.move(p, ROOT / "reports/resolved" / Path(p).name)
                                          for p in glob.glob(str(ROOT / "reports/TRANSFER-*"))]
    shutil.rmtree(ROOT / "state"); (ROOT / "state").mkdir()
    r = failover(); check("H3 Recuperação: após revisão, nova execução funciona", r["state"] == "completed", r)
    # I
    reset(); r = failover(FAKE_CODEX_MODE="writes"); rep = json.loads(Path(sorted(glob.glob(str(ROOT / "reports/RUN-*codex*.json")))[0]).read_text(encoding="utf-8"))
    check("I Escrita indevida detectada, sem transferir e sem apagar", rep["outcome"] == "VIOLATION"
          and "projeto_descartavel/criado_pelo_agente.txt" in rep["files_created"] and len(calls()) == 1
          and (ROOT / "lab/projeto_descartavel/criado_pelo_agente.txt").exists(), rep["outcome"])
    reset()
    check("I2 Arquivos originais do laboratório intactos após todos os cenários",
          {k: v for k, v in labhash().items()} == base, "hash divergente")
    # ---- V3.2: sucesso técnico != tarefa aprovada
    def runs(agent):
        return [json.loads(Path(f).read_text(encoding="utf-8")) for f in sorted(glob.glob(str(ROOT / f"reports/RUN-*{agent}.json")))]
    reset(); r = failover(); rep = runs("codex_cli")[0]
    check("Q1 Exit 0 + todos os critérios: EXECUTION_SUCCESS + TASK_ACCEPTED + completed",
          rep["execution_result"] == "EXECUTION_SUCCESS" and rep["task_verdict"] == "TASK_ACCEPTED"
          and rep["status"] == "completed" and r["state"] == "completed", rep["status"])
    for name, mode in (("Q2 Exit 0 com um critério reprovado (line_count errado)", "wrongcount"),
                       ("Q3 JSON válido com dados incorretos (zeros, resposta real da V3.1)", "placeholder")):
        reset(); r = failover(FAKE_CODEX_MODE=mode); rep = runs("codex_cli")[0]
        check(name + ": EXECUTION_SUCCESS + TASK_REJECTED, nunca 'completed'",
              rep["execution_result"] == "EXECUTION_SUCCESS" and rep["task_verdict"] == "TASK_REJECTED"
              and rep["status"] == "task_rejected" and r["state"] == "task_rejected_review_required"
              and r["state"] not in ("completed", "completed_after_transfer"), (rep["status"], r["state"]))
        check(name + ": NÃO transfere e NÃO é tratada como cota",
              [c["agent"] for c in calls()] == ["codex"] and not r["handoffs"] and avail("codex_cli") is None
              and rep["limit"]["kind"] is None, (calls(), avail("codex_cli")))
        n = len(calls()); r2 = failover()
        check(name + ": não repete; bloqueada até revisão", r2["state"] == "rejected" and len(calls()) == n, r2)
    reset(); r = failover(FAKE_CODEX_MODE="empty"); rep = runs("codex_cli")[0]
    check("Q4 Resposta ausente: UNKNOWN_RESULT, sem aprovação e sem transferência",
          rep["outcome"] == "UNKNOWN_RESULT" and rep["task_verdict"] == "NOT_EVALUATED"
          and r["state"] == "stopped_unknown_result" and len(calls()) == 1, rep["outcome"])
    # V2 direto (agente fixo) também separa execução de aprovação
    reset(); p = subprocess.run([sys.executable, str(ROOT / "tools/supervisor.py"), "run", str(ROOT / "instructions/T4.json"),
                                 "--confirm", "TASK-0004"], capture_output=True, text=True, encoding="utf-8",
                                env=env(FAKE_CODEX_MODE="wrongcount"))
    check("Q5 'run' com critério reprovado: status task_rejected e código de saída != 0",
          p.returncode != 0 and '"status": "task_rejected"' in p.stdout, p.stdout[-200:])
    # script de evidências nunca declara sucesso quando a tarefa foi rejeitada
    def evidence(**modes):
        reset(); pr = subprocess.run([sys.executable, str(ROOT / "tools/real_failover_test.py")], capture_output=True,
                                     text=True, encoding="utf-8", env=env(**modes))
        ev = json.loads((ROOT / "diagnostics/v3_1_real_evidence.json").read_text(encoding="utf-8"))
        return pr.returncode, ev["verdict"]
    (ROOT / "diagnostics").mkdir(exist_ok=True)
    rc, v = evidence(FAKE_CODEX_MODE="placeholder")
    check("Q6 Evidência: tarefa rejeitada NÃO vira A_CODEX_EXECUTOU_COM_SUCESSO", rc == 1 and v == "EXECUCAO_OK_MAS_TAREFA_REJEITADA", (rc, v))
    rc, v = evidence()
    check("Q6b Evidência: aprovação real = veredito A", rc == 0 and v == "A_CODEX_EXECUTOU_COM_SUCESSO", (rc, v))
    rc, v = evidence(FAKE_CODEX_MODE="quota")
    check("Q6c Evidência: limite real + transferência aprovada = veredito B", rc == 0 and v.startswith("B_"), (rc, v))
    # registro AVAILABLE_VERIFIED antigo (pré-V3.2) é ignorado
    reset(); (ROOT / "state/availability.json").write_text(json.dumps({"codex_cli": {
        "state": "AVAILABLE_VERIFIED", "since": "2026-01-01T00:00:00-03:00", "expires_at": "2999-01-01T00:00:00-03:00"}}))
    pr = subprocess.run([sys.executable, str(ROOT / "tools/supervisor.py"), "status"], capture_output=True, text=True,
                        encoding="utf-8", env=env())
    check("Q7 Registro AVAILABLE_VERIFIED anterior à V3.2 é tratado como UNKNOWN",
          json.loads(pr.stdout)["codex_cli"]["state"] == "UNKNOWN", pr.stdout[:200])
    # J
    reset(); r = failover(FAKE_CODEX_MODE="auth")
    check("J Erro de autenticação em execução -> transfere (sem efeitos)", r["state"] == "completed_after_transfer"
          and avail("codex_cli") == "AUTH_ERROR", r)
    # ---- V3.3: política x codificação x saída correta (Codex sem shell utilizável)
    def last_run(agent):
        return json.loads(Path(sorted(glob.glob(str(ROOT / f"reports/RUN-*{agent}.json")))[-1]).read_text(encoding="utf-8"))
    reset(); r = failover(FAKE_CODEX_MODE="noshell"); rep = last_run("codex_cli")
    check("R1 Bloqueio de política: diagnóstico 'policy', TASK_REJECTED, sem transferir, sem cota",
          rep["diagnosis"]["kind"] == "policy" and rep["task_verdict"] == "TASK_REJECTED" and rep["limit"]["kind"] is None
          and r["state"] == "task_rejected_review_required" and [c["agent"] for c in calls()] == ["codex"]
          and "bloqueio de política" in rep["summary"], (rep["diagnosis"], rep["summary"][:120]))
    reset(); r = failover(FAKE_CODEX_MODE="encoding_error"); rep = last_run("codex_cli")
    check("R2 Erro de codificação: diagnóstico 'encoding' (distinto de política), TASK_REJECTED, sem transferir",
          rep["diagnosis"]["kind"] == "encoding" and rep["task_verdict"] == "TASK_REJECTED"
          and "Causa provável: erro de codificação" in rep["summary"] and "Causa provável: bloqueio" not in rep["summary"]
          and r["state"] == "task_rejected_review_required" and len(calls()) == 1, (rep["diagnosis"], rep["summary"][:120]))
    reset(); write_agents(context_delivery="embedded"); r = failover(FAKE_CODEX_MODE="noshell"); rep = last_run("codex_cli")
    check("R3 Saída correta com entrega embutida (sem depender do shell): TASK_ACCEPTED + completed",
          rep["task_verdict"] == "TASK_ACCEPTED" and rep["status"] == "completed" and r["state"] == "completed"
          and rep["diagnosis"]["kind"] is None, (rep["status"], rep["diagnosis"], rep.get("rejected_criteria"), rep.get("acceptance_result")))
    # R3c regressão Windows: o prompt chega ao agente com CRLF (reproduzido aqui em qualquer SO)
    pr_lf = Path(glob.glob(str(ROOT / "runs/RUN-*codex_cli/prompt.txt"))[0]).read_bytes().decode("utf-8").replace("\r\n", "\n")
    crlf_out = TMP / "crlf_out.json"
    pc = subprocess.run([sys.executable, str(BIN / "fake_agent.py"), "codex", "exec", "--output-last-message",
                         str(crlf_out), "-"], input=pr_lf.replace("\n", "\r\n").encode("utf-8"), capture_output=True,
                        env=env(FAKE_CODEX_MODE="noshell"))
    got = json.loads(crlf_out.read_text(encoding="utf-8")) if crlf_out.exists() else {}
    check("R3c Prompt com CRLF (como no Windows) é lido pelo agente simulado: line_count 12, sem 'blocked by policy'",
          got.get("line_count") == 12 and b"blocked by policy" not in pc.stderr, (got, pc.stderr[-200:]))
    check("R3b Prompt embutido contém o arquivo como DADOS e o sandbox continua read-only",
          "<<<ARQUIVO texto_exemplo.txt" in Path(glob.glob(str(ROOT / "runs/RUN-*codex_cli/prompt.txt"))[0]).read_text(encoding="utf-8")
          and rep["command"][rep["command"].index("--sandbox") + 1] == "read-only", rep["command"][:6])
    check("R4 Arquivos do laboratório preservados após os cenários R1-R3", labhash() == base, "hash divergente")
    # R5 classificação em processo
    sys.path.insert(0, str(ROOT / "src")); os.environ["MAUTRIX_ROOT"] = str(ROOT)
    from mautrix_orq import outcomes as _oc
    kinds = {k: _oc.classify_text(v)["kind"] for k, v in {
        "pol": 'CreateProcess { message: "Rejected(... rejected: blocked by policy)" }',
        "enc": "UnicodeDecodeError: 'charmap' codec can't decode byte",
        "quo": "You\u2019ve hit your usage limit. Upgrade to Pro", "aut": "Error: Not logged in",
        "tec": "read ECONNRESET network error", "nul": "tudo certo"}.items()}
    check("R5 Classificação de textos: política, codificação, cota, autenticação, técnico e nenhum são distintos",
          kinds == {"pol": "policy", "enc": "encoding", "quo": "quota", "aut": "auth", "tec": "transient", "nul": None}, kinds)
    # R6 arquivo de contexto que não é UTF-8
    reset(); write_agents(context_delivery="embedded")
    (ROOT / "lab/projeto_descartavel/latin1.txt").write_bytes("fictícia\n".encode("cp1252"))
    t5 = json.loads((ROOT / "instructions/T4.json").read_text()); t5.update(task_id="TASK-0005", context_files=["latin1.txt"])
    (ROOT / "instructions/T5.json").write_text(json.dumps(t5))
    p = subprocess.run([sys.executable, str(ROOT / "tools/supervisor.py"), "run", str(ROOT / "instructions/T5.json"),
                        "--confirm", "TASK-0005"], capture_output=True, text=True, encoding="utf-8", env=env())
    rep = last_run("codex_cli")
    check("R6 Arquivo não-UTF-8: erro de ENCODING (não política), agente não iniciado, sem transferência",
          rep["failure_kind"] == "input_encoding" and rep["agent_started"] is False and not calls()
          and any("ENCODING" in e for e in rep["errors"]) and rep["outcome"] == "TECHNICAL_ERROR"
          and not _oc.can_transfer(rep)[0], (rep["failure_kind"], rep["errors"]))
    (ROOT / "lab/projeto_descartavel/latin1.txt").unlink()
    # R7 argumentos extras do Codex: só windows.sandbox="unelevated"
    def dry(**cfg):
        reset(); write_agents(**cfg)
        pr = subprocess.run([sys.executable, str(ROOT / "tools/supervisor.py"), "dry-run", str(ROOT / "instructions/T4.json")],
                            capture_output=True, text=True, encoding="utf-8", env=env())
        try:
            return json.loads(pr.stdout)
        except ValueError:
            return {"status": "crash", "errors": [pr.stderr[-800:]], "command": []}
    d = dry(exec_extra_args=["-c", 'windows.sandbox="unelevated"'])
    check("R7 Extra permitido (windows.sandbox=unelevated) entra no comando e mantém --sandbox read-only",
          'windows.sandbox="unelevated"' in d["command"] and d["command"][d["command"].index("--sandbox") + 1] == "read-only", d)
    d = dry(exec_extra_args=["-c", 'sandbox_mode="danger-full-access"'])
    check("R7b Qualquer outro extra (sandbox mais permissivo) é recusado", d["status"] == "rejected_by_policy"
          and any("exec_extra_args" in e for e in d["errors"]), d["errors"])
    reset()
    check("R8 Laboratório ainda idêntico ao original no fim dos cenários V3.3", labhash() == base, "hash divergente")

    # ---- V3.3: script de validação da TASK-0004 (Codex com contexto embutido)
    t04 = json.loads((SRC / "instructions/TASK-0004_codex_embedded_lab.json").read_text(encoding="utf-8"))
    t04["project_path"] = str(ROOT / "lab/projeto_descartavel")
    t04["limits"] = {"timeout_seconds": 30, "max_attempts": 1}
    (ROOT / "instructions/TASK-0004_codex_embedded_lab.json").write_text(json.dumps(t04), encoding="utf-8")

    def v04(*args, **modes):
        pr = subprocess.run([sys.executable, str(ROOT / "tools/validar_task0004.py"), *args], capture_output=True,
                            text=True, encoding="utf-8", env=env(**modes))
        ev = ROOT / "diagnostics" / ("task0004_dryrun.json" if args[0] == "dry-run" else "task0004_evidence.json")
        return pr.returncode, (json.loads(ev.read_text(encoding="utf-8")) if ev.exists() else {}), pr
    (ROOT / "diagnostics").mkdir(exist_ok=True)
    reset(); write_agents(context_delivery="embedded"); rc, ev, _ = v04("dry-run")
    check("S1 Dry-run TASK-0004: aprovado, nenhum agente iniciado, sandbox read-only, conteúdo embutido (12 linhas)",
          rc == 0 and ev["verdict"] == "DRY_RUN_OK" and ev["agent_started"] is False and not calls()
          and ev["sandbox"] == "read-only" and ev["prompt"]["embeds_file_content"]
          and ev["prompt"]["embedded_non_empty_lines"] == 12 and ev["prompt"]["tells_agent_no_commands_needed"]
          and not ev["prompt"]["tells_agent_to_use_shell"], (rc, ev.get("problems")))
    reset(); write_agents(); rc, ev, _ = v04("dry-run")
    check("S2 Dry-run recusa configuração sem 'embedded' (agent_reads)",
          rc == 1 and any("context_delivery" in x for x in ev["problems"]) and not calls(), (rc, ev.get("problems")))
    reset(); write_agents(context_delivery="embedded")
    (ROOT / "reports/RUN-20000101_000000000-TASK-0003-codex_cli.json").write_text('{"historico": true}', encoding="utf-8")
    (ROOT / "logs/executor.log").write_text('{"antigo": 1}\n', encoding="utf-8")
    old = {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest()
           for f in ("reports/RUN-20000101_000000000-TASK-0003-codex_cli.json",)}
    rc, ev, _ = v04("run", "--confirm", "TASK-0004", FAKE_CODEX_MODE="noshell")
    check("S3 Execução (simulada) aprovada: line_count 12, JSON válido, TASK_ACCEPTED, arquivos e locks preservados",
          rc == 0 and ev["verdict"] == "VALIDACAO_APROVADA" and all(ev["criteria"].values())
          and [c["agent"] for c in calls()] == ["codex"] and ev["run"]["task_verdict"] == "TASK_ACCEPTED"
          and ev["agent_output"]["line_count"] == 12, (rc, ev.get("verdict"), ev.get("criteria"), ev.get("problems")))
    rep04 = json.loads(Path(sorted(glob.glob(str(ROOT / "reports/RUN-*TASK-0004-codex_cli.json")))[-1]).read_text(encoding="utf-8"))
    check("S3c Regressão: agent_started da evidência = True e igual ao relatório da execução real/simulada",
          ev["agent_started"] is True and rep04["agent_started"] is True and ev["run"]["agent_started"] is True
          and ev["criteria"]["agent_started consistente com a execução"], (ev.get("agent_started"), rep04.get("agent_started")))
    check("S3b Histórico de TASK-0003 e log antigo preservados; relatório novo é de TASK-0004",
          all(hashlib.sha256((ROOT / f).read_bytes()).hexdigest() == h for f, h in old.items())
          and (ROOT / "logs/executor.log").read_text(encoding="utf-8").startswith('{"antigo": 1}')
          and "TASK-0004" in ev["run"]["run_id"] and not ev["locks_after"], ev.get("history_problems"))
    n = len(calls()); rc, ev2, _ = v04("run", "--confirm", "TASK-0004", FAKE_CODEX_MODE="noshell")
    check("S4 Segunda execução de TASK-0004 é recusada antes de iniciar o agente (execução única)",
          rc == 1 and ev2["verdict"] == "INTERROMPIDO_NA_PRE_VERIFICACAO" and ev2["agent_started"] is False and len(calls()) == n, (rc, ev2.get("problems")))
    n = len(calls()); rc, _, pr = v04("run", "--confirm", "TASK-0003")
    check("S5 Confirmação errada é recusada sem iniciar o agente", rc == 2 and len(calls()) == n, pr.stdout[-200:])
    reset(); write_agents(context_delivery="embedded"); rc, ev, _ = v04("run", "--confirm", "TASK-0004", FAKE_CODEX_MODE="wrongcount")
    check("S6 Contagem errada do agente: VALIDACAO_REPROVADA (nunca aprovada), sem nova tentativa",
          rc == 1 and ev["verdict"].startswith("VALIDACAO_REPROVADA") and not ev["criteria"]["line_count = 12"]
          and len(calls()) == 1, (rc, ev.get("verdict")))
    reset()
    check("S7 Laboratório idêntico ao original após a validação TASK-0004", labhash() == base, "hash divergente")

    # K: políticas
    bad = []
    for c in calls():
        for frag in ("--dangerously", "--full-auto", "danger-full-access", "bypassPermissions", "reset", "clean", "commit", "push"):
            if any((x == frag) if frag in ("reset", "clean", "commit", "push") else (frag in x) for x in c["args"]):
                bad.append(frag)
    check("K Nenhum argumento proibido/git nas chamadas simuladas", not bad, bad)
    t = json.loads((ROOT / "instructions/T3.json").read_text()); t["project_path"] = "/tmp"
    (ROOT / "instructions/T3b.json").write_text(json.dumps(t))
    p = subprocess.run([sys.executable, str(ROOT / "tools/supervisor.py"), "failover", str(ROOT / "instructions/T3b.json"),
                        "--confirm", "TASK-0003"], capture_output=True, text=True, encoding="utf-8", env=env())
    check("K2 Projeto fora do laboratório é rejeitado", '"rejected"' in p.stdout, p.stdout[-200:])


if __name__ == "__main__":
    hang_seen = []
    try:
        run_all()
    finally:
        hang_seen = [{"pid": p, "alive_at_end": pid_alive(p)} for p in pid_list()]
        shutil.rmtree(TMP, ignore_errors=True)
    failed = [n for n, ok, _ in results if not ok]
    if len(sys.argv) > 2 and sys.argv[1] == "--json":
        Path(sys.argv[2]).write_text(json.dumps({"python": sys.version, "platform": sys.platform,
            "results": [{"name": n, "pass": ok} for n, ok, _ in results],
            "hang_pids_seen": hang_seen}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(results) - len(failed)}/{len(results)} verificações passaram (agentes SIMULADOS)")
    sys.exit(1 if failed else 0)
