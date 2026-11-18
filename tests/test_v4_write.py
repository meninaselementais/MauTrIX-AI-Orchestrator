#!/usr/bin/env python3
"""Testes V4 (escrita controlada com Git) com agentes SIMULADOS. Nunca toca agentes reais nem o jogo.
Usa uma cópia temporária do orquestrador e um repositório Git descartável criado na cópia (exige 'git' no PATH).
Uso: python tests/test_v4_write.py [--json saida.json]"""
import glob, hashlib, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="mxv4_"))
ROOT, BIN = TMP / "root", TMP / "bin"
LOG, PIDS = TMP / "fake.log", TMP / "hang_pids.txt"
LAB = ROOT / "lab" / "git_lab"
results = []
HEAD0 = None
os.environ.update(MAUTRIX_ROOT=str(ROOT), MAUTRIX_TEST_MODE="1", MAUTRIX_TEST_BIN=str(BIN))
sys.path.insert(0, str(SRC / "src"))


def rmtree_force(path):
    """No Windows os objetos do Git são somente leitura; remove com chmod."""
    import stat
    def onerr(func, p, _exc):
        os.chmod(p, stat.S_IWRITE); func(p)
    shutil.rmtree(path, onerror=onerr) if Path(path).exists() else None


def env(**modes):
    e = dict(os.environ, MAUTRIX_ROOT=str(ROOT), MAUTRIX_TEST_MODE="1", MAUTRIX_TEST_BIN=str(BIN), FAKE_LOG=str(LOG),
             PATH=f"{BIN}{os.pathsep}{os.environ['PATH']}", FAKE_CLAUDE_MODE="ok", FAKE_CODEX_MODE="ok",
             MX_PY=sys.executable, PYTHONIOENCODING="utf-8", FAKE_PIDFILE=str(PIDS), FAKE_REAL_REPO=str(LAB))
    e.update(modes)
    return e


def sh(*args, **modes):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, encoding="utf-8", env=env(**modes))


def setup():
    shutil.copytree(SRC, ROOT, ignore=shutil.ignore_patterns("reports", "runs", "logs", "locks", "state", "handoffs",
                    "diagnostics", "__pycache__", "tests", "workspaces", "backups", "manifests", "patches", ".git", "errata"))
    BIN.mkdir()
    shutil.copy(SRC / "tests/fakes/fake_agent.py", BIN / "fake_agent.py")
    for n in ("claude", "codex"):
        if os.name == "nt":
            (BIN / f"{n}.cmd").write_text(f'@"%MX_PY%" "%~dp0fake_agent.py" {n} %*\r\n', encoding="ascii")
        else:
            shutil.copy(SRC / "tests/fakes/fake_agent.py", BIN / n); (BIN / n).chmod(0o755)


def agents(**codex):
    (ROOT / "config/agents.json").write_text(json.dumps({"agents": [
        {"id": "claude_code", "commands": ["claude"], "version_args": ["--version"], "enabled": True},
        {"id": "codex_cli", "commands": ["codex"], "version_args": ["--version"], "enabled": True, **codex},
        {"id": "antigravity_cli", "commands": ["agy"], "enabled": False}]}), encoding="utf-8")


def fresh(init=True):
    for d in ("reports", "runs", "logs", "locks", "state", "handoffs", "workspaces", "backups", "manifests", "patches"):
        rmtree_force(ROOT / d); (ROOT / d).mkdir()
    rmtree_force(LAB)
    # Somente os arquivos de exemplo do commit-base: o lab\\git_lab de origem pode conter artefatos de execução
    # (rascunho_local.txt, cache_local.tmp, .git) que NÃO devem entrar no laboratório temporário.
    from mautrix_orq.common import LAB_BASELINE_FILES
    for rel in LAB_BASELINE_FILES:
        (LAB / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SRC / "lab/git_lab" / rel, LAB / rel)
    agents(); LOG.write_text(""); PIDS.write_text("")
    if init:
        p = sh(ROOT / "tools/lab_git.py", "init", "--confirm", "LAB-GIT-INIT")
        assert p.returncode == 0, p.stdout + p.stderr
    global HEAD0
    HEAD0 = git("rev-parse", "HEAD").strip() if init else None


def wtask(name="W", **over):
    t = json.loads((SRC / "instructions/TASK-1001_write_claude_lab.json").read_text(encoding="utf-8"))
    t["project_path"] = str(LAB)
    t["limits"] = {**t["limits"], "timeout_seconds": 6}
    lim = over.pop("limits", {})
    t["limits"].update(lim)
    t.update(over)
    f = ROOT / "instructions" / f"{name}.json"
    f.write_text(json.dumps(t), encoding="utf-8")
    return f


def wrun(task_file, cmd="write-run", confirm="TASK-1001", **modes):
    args = [ROOT / "tools/supervisor.py", cmd, task_file] + (["--confirm", confirm] if confirm else [])
    p = sh(*args, **modes)
    try:
        return json.loads(p.stdout)
    except ValueError:
        return {"status": "CLI_ERROR", "summary": (p.stdout + p.stderr)[-600:], "errors": [], "write": {}}


def calls():
    return [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]


def tree():
    from mautrix_orq.writescope import tree_snapshot
    return tree_snapshot(LAB)


def git(*args):
    return subprocess.run(["git", "-C", str(LAB), *args], capture_output=True, text=True, encoding="utf-8").stdout


def read(rel):
    return (LAB / rel).read_text(encoding="utf-8")


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:1500]}]" if detail and not cond else ""))


def kinds(rep):
    return sorted({v["kind"] for v in rep.get("write", {}).get("violations", [])})


def run_all():
    setup()
    # ---------------------------------------------------------------- 1. laboratório Git e estado inicial
    # L1 (parte 1): origem "suja" — arquivos pré-existentes não podem entrar no commit-base nem ser sobrescritos
    from mautrix_orq.common import LAB_BASELINE_FILES
    fresh(init=False)
    (LAB / "estranho_pre_init.txt").write_text("arquivo pré-existente\n", encoding="utf-8")
    (LAB / "rascunho_local.txt").write_text("meu rascunho anterior\n", encoding="utf-8")
    pi = sh(ROOT / "tools/lab_git.py", "init", "--confirm", "LAB-GIT-INIT")
    dirty_ok = (pi.returncode == 0 and set(git("ls-files").split()) == set(LAB_BASELINE_FILES)
                and "?? estranho_pre_init.txt" in git("status", "--porcelain")
                and read("rascunho_local.txt") == "meu rascunho anterior\n")
    dirty_detail = (pi.returncode, git("ls-files").split(), git("status", "--porcelain").splitlines())
    fresh()
    base = tree()
    st = json.loads((ROOT / "reports/GITLAB_BASELINE.json").read_text(encoding="utf-8"))
    check("L1 Laboratório Git criado e estado inicial registrado (branch, HEAD, não rastreados)",
          st["branch"] == "main" and len(st["head"]) == 40 and st["untracked"] == ["rascunho_local.txt"]
          and not st["tracked_changes"] and (ROOT / "reports/GITLAB_BASELINE.md").exists()
          and st["files"]["cache_local.tmp"]["ignored_or_untracked"] and dirty_ok,
          {"esperado": {"untracked": ["rascunho_local.txt"], "tracked": sorted(LAB_BASELINE_FILES)},
           "observado": {k: st[k] for k in ("branch", "head", "untracked", "tracked_changes")},
           "pre_init_sujo": dirty_detail})
    check("L2 O commit-base é o ÚNICO commit e não há tags", git("rev-list", "--count", "HEAD").strip() == "1"
          and git("tag").strip() == "", git("log", "--oneline"))
    from mautrix_orq import gitops
    from mautrix_orq.common import PolicyError
    bad = []
    for sub in ("reset", "clean", "merge", "rebase", "push", "tag", "commit", "checkout", "stash", "add"):
        try:
            gitops._git(LAB, sub, "--hard"); bad.append(sub)
        except PolicyError:
            pass
    check("G0 gitops recusa reset/clean/merge/rebase/push/tag/commit/checkout/stash/add", not bad, bad)

    # ---------------------------------------------------------------- 2. dry-run e comandos (controles preventivos)
    fresh(); tf = wtask("A")
    rep = wrun(tf, "write-dry-run", confirm=None)
    cmd = rep["command"]
    allow = cmd[cmd.index("--allowedTools") + 1]
    check("D1 Dry-run: nada criado, repositório intacto, Git registrado", rep["status"] == "completed" and tree() == base
          and not list((ROOT / "workspaces").iterdir()) and not list((ROOT / "runs").iterdir())
          and rep["write"]["git_before"]["head"] == HEAD0 and not calls(), rep.get("summary"))
    check("D2 Claude: workspace isolado, --restricted, sem shell/rede, permissões por arquivo, sem Bash permitido",
          "--restricted" in cmd and "--disallowedTools" in cmd and "Bash" not in allow.replace("Bash,PowerShell", "")
          and "Edit(./notas.txt)" in allow and "Write(./resultado.txt)" in allow and "--dangerously" not in " ".join(cmd)
          and cmd[cmd.index("--permission-mode") + 1] == "dontAsk", cmd)
    rep = wrun(wtask("A2", agent="codex_cli"), "write-dry-run", confirm=None)
    cmd = rep["command"]
    check("D3 Codex: continua read-only, sem bypass e sem workspace-write; escrita só por proposta",
          "read-only" in cmd and not any(x in " ".join(cmd) for x in ("workspace-write", "danger", "full-auto", "approve-for-me"))
          and rep["write"]["strategy"] == "proposal", cmd)
    agents(write_strategy="workspace_edit")
    rep = wrun(wtask("A3", agent="codex_cli"), "write-dry-run", confirm=None)
    check("D4 Codex NÃO pode ser configurado para editar diretamente (sem contornar o shell bloqueado)",
          rep["status"] == "rejected_by_policy" and "estratégia" in rep["summary"], rep["summary"])

    # ---------------------------------------------------------------- 3. alteração e criação autorizadas
    fresh(); old_report = ROOT / "reports/RUN-antigo.json"; old_report.write_text('{"historico":1}', encoding="utf-8")
    cfg_h = hashlib.sha256((LAB / "config.json").read_bytes()).hexdigest()
    rep = wrun(tf := wtask("A"), FAKE_CLAUDE_MODE="w_ok")
    st = git("status", "--porcelain").splitlines()
    W = rep["write"]
    check("A1 Alteração e criação autorizadas: TASK_ACCEPTED, completed, promovidas",
          rep["status"] == "completed" and rep["task_verdict"] == "TASK_ACCEPTED" and W["promoted"]
          and "Linha 4:" in read("notas.txt") and read("resultado.txt").startswith("Resultado"), rep["summary"])
    check("A2 Não rastreado e ignorado preservados; config.json e demais arquivos idênticos",
          read("rascunho_local.txt").startswith("Rascunho local") and (LAB / "cache_local.tmp").exists()
          and hashlib.sha256((LAB / "config.json").read_bytes()).hexdigest() == cfg_h
          and {k: v for k, v in tree().items() if k not in ("notas.txt", "resultado.txt")}
          == {k: v for k, v in base.items() if k != "notas.txt"}, rep["write"])
    check("A3 Git: HEAD/branch/refs iguais, nenhum commit, nenhuma tag; diff mostra só notas.txt",
          git("rev-parse", "HEAD").strip() == HEAD0 and git("rev-list", "--count", "HEAD").strip() == "1" and git("tag").strip() == ""
          and " M notas.txt" in st and "?? resultado.txt" in st and "?? rascunho_local.txt" in st and len(st) == 3, st)
    check("A4 Backup, manifesto de preservação, patch (git diff) e relatório gravados",
          Path(W["backup_dir"], "files/notas.txt").exists() and Path(W["manifest"]).exists()
          and "Linha 4:" in Path(W["patch"]).read_text(encoding="utf-8") and "diff --git" in Path(W["patch"]).read_text(encoding="utf-8")
          and glob.glob(str(ROOT / "reports/RUN-*TASK-1001-claude_code.json")), W)
    check("A5 Locks liberados e histórico (relatório antigo) preservado", not list((ROOT / "locks").iterdir())
          and old_report.read_text() == '{"historico":1}', list((ROOT / "locks").iterdir()))
    ws_files = sorted(str(q.relative_to(W["workspace"])).replace("\\", "/") for q in Path(W["workspace"]).rglob("*") if q.is_file())
    ws_expected = sorted(set(LAB_BASELINE_FILES) | {"resultado.txt"})   # rastreados + o arquivo criado pelo agente
    check("A6 Workspace NÃO contém .git nem arquivos não rastreados/ignorados (conjunto exato = rastreados + criado)",
          ws_files == ws_expected and not (Path(W["workspace"]) / ".git").exists(),
          {"esperado": ws_expected, "observado": ws_files})
    # recuperação
    run_id = rep["run_id"]
    r0 = sh(ROOT / "tools/supervisor.py", "write-restore", run_id, "--confirm", "nada")
    check("J0 Restauração exige confirmação exata", r0.returncode == 1 and "Linha 4:" in read("notas.txt"), r0.stdout[-200:])
    r1 = sh(ROOT / "tools/supervisor.py", "write-restore", run_id, "--confirm", f"RESTORE-{run_id}")
    check("J1 Recuperação sem perda: restaura o original, remove o criado, preserva não rastreados",
          r1.returncode == 0 and tree() == base and read("rascunho_local.txt").startswith("Rascunho"), r1.stdout[-300:])

    # ---------------------------------------------------------------- 4. violações de escopo (nada é promovido)
    cases = [("B1 Alteração PROIBIDA (config.json)", "w_mod_forbidden", "modify_not_allowed"),
             ("B2 Exclusão PROIBIDA (README.txt)", "w_del_forbidden", "delete_forbidden"),
             ("B3 Criação PROIBIDA (intruso.txt)", "w_create_forbidden", "create_not_allowed"),
             ("B4 Mais arquivos que o limite", "w_ok", "too_many_files"),
             ("B5 Conteúdo grande demais", "w_toobig", None),
             ("B6 Conteúdo binário", "w_binary", "binary_content")]
    for name, mode, kind in cases:
        fresh(); b = tree()
        lim = {"max_files_changed": 1} if kind == "too_many_files" else {}
        rep = wrun(wtask("B", limits=lim), FAKE_CLAUDE_MODE=mode)
        ok_kind = (kind in kinds(rep)) if kind else bool({"file_too_large", "too_many_bytes"} & set(kinds(rep)))
        check(f"{name}: VIOLATION, status violation_review_required, nada promovido, repositório intacto",
              rep["outcome"] == "VIOLATION" and rep["status"] == "violation_review_required" and ok_kind
              and not rep["write"]["promoted"] and tree() == b and git("rev-parse", "HEAD").strip() == HEAD0
              and Path(rep["write"]["workspace"]).exists(), (rep["status"], kinds(rep), rep["summary"]))
    # ---------------------------------------------------------------- 5. escrita fora do workspace (agente malicioso)
    for name, mode, fname in (("B7 Escrita no repositório real (rastreado)", "w_outside", "notas.txt"),
                              ("B8 Escrita em arquivo NÃO rastreado do repositório real", "w_outside_untracked", "rascunho_local.txt")):
        fresh(); rep = wrun(wtask("B"), FAKE_CLAUDE_MODE=mode)
        check(f"{name}: detectada, VIOLATION, nada promovido, sem restauração automática (revisão humana)",
              rep["outcome"] == "VIOLATION" and "real_repo_changed_during_run" in kinds(rep) and not rep["write"]["promoted"]
              and ("INVASAO" in read(fname) or "ALTERADO" in read(fname)) and not Path(rep["write"]["backup_dir"] or "/nao").exists(), (kinds(rep), rep["status"]))
    # ---------------------------------------------------------------- 6. falhas de validação, interrupção, timeout
    fresh(); b = tree(); rep = wrun(wtask("B"), FAKE_CLAUDE_MODE="w_badvalid")
    check("F1 Falha de validação: EXECUTION_SUCCESS + TASK_REJECTED, nada promovido, repositório intacto",
          rep["status"] == "task_rejected" and rep["task_verdict"] == "TASK_REJECTED" and not rep["write"]["promoted"]
          and tree() == b and any("Validações" in c for c in [r["criterion"] for r in rep["acceptance_result"] if r["met"] == "no"]), rep["summary"])
    fresh(); b = tree(); rep = wrun(wtask("B"), FAKE_CLAUDE_MODE="w_then_kill")
    check("E1 Interrupção durante a edição: erro técnico, alterações só no workspace, repositório intacto",
          rep["outcome"] == "TECHNICAL_ERROR" and rep["write"]["workspace_changed"] and not rep["write"]["promoted"]
          and tree() == b and "Linha 4:" in (Path(rep["write"]["workspace"]) / "notas.txt").read_text(encoding="utf-8"), rep["summary"])
    fresh(); b = tree(); rep = wrun(wtask("B"), FAKE_CLAUDE_MODE="w_then_hang")
    time.sleep(1.0)
    pids = [int(x) for x in PIDS.read_text().split()]
    def alive(pid):
        if os.name == "nt":
            return str(pid) in subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        try:
            os.kill(pid, 0); return True
        except OSError:
            return False
    check("T1 Timeout após escrita: TIMEOUT, alterações parciais só no workspace, repositório intacto, processo encerrado, locks livres",
          rep["outcome"] == "TIMEOUT" and rep["write"]["workspace_changed"] and not rep["write"]["promoted"] and tree() == b
          and pids and not any(alive(p) for p in pids) and not list((ROOT / "locks").iterdir()), (rep["outcome"], pids))
    # ---------------------------------------------------------------- 7. Codex em modo proposta
    fresh(); rep = wrun(wtask("C", agent="codex_cli"), FAKE_CODEX_MODE="p_ok")
    check("C1 Codex (read-only) propõe, o orquestrador valida e aplica: TASK_ACCEPTED e promovido",
          rep["status"] == "completed" and rep["write"]["promoted"] and "Linha 4: proposta" in read("notas.txt")
          and rep["write"]["strategy"] == "proposal" and not rep["write"]["workspace_changed"] is False, rep["summary"])
    for name, mode, kind in (("C2 Proposta fora do escopo (config.json)", "p_forbidden", "proposal_path_not_allowed"),
                             ("C3 Proposta com '..' (travessia)", "p_traversal", "proposal_invalid"),
                             ("C4 Codex escreveu no workspace apesar de read-only", "p_writes", "agent_wrote_in_readonly")):
        fresh(); b = tree(); rep = wrun(wtask("C", agent="codex_cli"), FAKE_CODEX_MODE=mode)
        check(f"{name}: VIOLATION, nada promovido, repositório intacto",
              rep["outcome"] == "VIOLATION" and kind in kinds(rep) and tree() == b, (kinds(rep), rep["summary"]))
    fresh(); b = tree(); rep = wrun(wtask("C", agent="codex_cli"), FAKE_CODEX_MODE="p_badvalid")
    check("C5 Proposta que falha na validação: TASK_REJECTED, nada promovido", rep["status"] == "task_rejected" and tree() == b, rep["summary"])
    # ---------------------------------------------------------------- 8. pré-condições Git e caminhos inseguros
    fresh(); (LAB / "notas.txt").write_text("alteração humana pendente\n", encoding="utf-8")
    rep = wrun(wtask("B"), FAKE_CLAUDE_MODE="w_ok")
    check("P1 Alteração pendente no arquivo autorizado: recusada, nada sobrescrito, agente nem iniciou",
          rep["status"] == "rejected_by_policy" and read("notas.txt") == "alteração humana pendente\n" and not calls(), rep["errors"])
    fresh(); (LAB / "config.json").write_text('{"humano": true}\n', encoding="utf-8")
    rep = wrun(wtask("B"), FAKE_CLAUDE_MODE="w_ok")
    check("P2 Alteração pendente em OUTRO arquivo: registrada e preservada; tarefa segue",
          rep["status"] == "completed" and read("config.json") == '{"humano": true}\n'
          and rep["write"]["pending_changes"] and rep["write"]["pending_changes"][0]["path"] == "config.json", rep["summary"])
    fresh(); (LAB / ".git/MERGE_HEAD").write_text("0" * 40 + "\n")
    rep = wrun(wtask("B"), FAKE_CLAUDE_MODE="w_ok")
    check("P3 Operação Git em andamento (merge): recusada", rep["status"] == "rejected_by_policy" and not calls(), rep["errors"])
    fresh(); rmtree_force(LAB / ".git")  # objetos do Git são somente leitura no Windows
    rep = wrun(wtask("B"), FAKE_CLAUDE_MODE="w_ok")
    check("P4 Pasta sem repositório Git: recusada", rep["status"] == "rejected_by_policy" and not calls(), rep["errors"])
    fresh()
    for bad in (["../fora.txt"], [".git/config"], ["C:/x.txt"], ["a\\b.txt"], ["con.txt"], ["/abs.txt"], [".gitignore"]):
        rep = wrun(wtask("B", allowed_modify=bad), FAKE_CLAUDE_MODE="w_ok")
        check(f"K Caminho inseguro {bad} é recusado antes de qualquer agente", rep["status"] == "rejected_by_policy" and not calls(), rep["errors"])
    t = json.loads((ROOT / "instructions/B.json").read_text()); t["project_path"] = str(ROOT / "lab/projeto_descartavel")
    (ROOT / "instructions/B2.json").write_text(json.dumps(t))
    rep = wrun(ROOT / "instructions/B2.json", FAKE_CLAUDE_MODE="w_ok")
    check("K2 Escrita fora de lab\\git_lab (outro projeto) é recusada", rep["status"] == "rejected_by_policy" and not calls(), rep["errors"])
    t = json.loads((ROOT / "instructions/B.json").read_text()); t["git_policy"]["commit"] = True
    (ROOT / "instructions/B3.json").write_text(json.dumps(t))
    rep = wrun(ROOT / "instructions/B3.json", FAKE_CLAUDE_MODE="w_ok")
    check("K3 git_policy com commit=true é recusada", rep["status"] == "rejected_by_policy" and not calls(), rep["errors"])
    rep = wrun(wtask("B"), confirm="TASK-9999", FAKE_CLAUDE_MODE="w_ok")
    check("K4 Sem confirmação correta nada executa", rep["status"] == "rejected_by_policy" and not calls(), rep["errors"])

    # ---------------------------------------------------------------- 9. execução simultânea
    fresh(); b = tree()
    bg = subprocess.Popen([sys.executable, str(ROOT / "tools/supervisor.py"), "write-run", str(wtask("B")), "--confirm", "TASK-1001"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env(FAKE_CLAUDE_MODE="w_then_hang"))
    time.sleep(2.0)
    rep2 = wrun(wtask("B"), FAKE_CLAUDE_MODE="w_ok")
    bg.communicate(timeout=60)
    check("S1 Execução simultânea bloqueada (BUSY); a primeira não promove; repositório intacto",
          rep2["outcome"] == "BUSY" and len(calls()) == 1 and tree() == b, (rep2["outcome"], len(calls())))
    fresh(); (ROOT / "locks/_global_agent.lock").write_text('{"task_id":"OUTRA"}')
    rep = wrun(wtask("B"), FAKE_CLAUDE_MODE="w_ok")
    check("S2 Lock existente impede a escrita e não é removido", rep["outcome"] == "BUSY" and (ROOT / "locks/_global_agent.lock").exists() and not calls(), rep["outcome"])

    # ---------------------------------------------------------------- 10. failover de escrita
    def wf(**modes):
        p = sh(ROOT / "tools/supervisor.py", "write-failover", wtask("F", agent="any_available"), "--confirm", "TASK-1001", **modes)
        try:
            return json.loads(p.stdout)
        except ValueError:
            return {"state": "CLI_ERROR", "final_reason": (p.stdout + p.stderr)[-400:], "steps": []}
    fresh(); r = wf(FAKE_CLAUDE_MODE="quota", FAKE_CODEX_MODE="p_ok"); cs = calls()
    check("V1 Limite ANTES de modificar arquivos: transferência segura Claude -> Codex (proposta) e promoção",
          r["state"] == "completed_after_transfer" and [c["agent"] for c in cs] == ["claude", "codex"] and cs[1]["handoff"]
          and "Linha 4: proposta" in read("notas.txt"), r)
    fresh(); b = tree(); r = wf(FAKE_CLAUDE_MODE="w_then_quota", FAKE_CODEX_MODE="p_ok")
    check("V2 Limite DEPOIS de modificar arquivos: interrompe, exige revisão, NÃO transfere, repositório intacto",
          r["state"] == "changes_present_review_required" and [c["agent"] for c in calls()] == ["claude"] and tree() == b, r)
    r2 = wf(FAKE_CLAUDE_MODE="ok", FAKE_CODEX_MODE="p_ok")
    check("V3 Nova tentativa fica bloqueada até revisão humana", r2["state"] == "rejected" and "bloqueia" in r2["final_reason"] and len(calls()) == 1, r2)
    fresh(); b = tree(); r = wf(FAKE_CLAUDE_MODE="w_mod_forbidden", FAKE_CODEX_MODE="p_ok")
    check("V4 Violação de escopo interrompe a cadeia (sem transferir)", r["state"] == "violation_review_required"
          and len(calls()) == 1 and tree() == b, r)
    fresh(); b = tree(); r = wf(FAKE_CLAUDE_MODE="w_then_kill", FAKE_CODEX_MODE="p_ok")
    check("V5 Interrupção durante a edição (processo morto): não transfere e exige revisão", r["state"] == "changes_present_review_required"
          and len(calls()) == 1 and tree() == b, r)
    fresh(); r = wf(FAKE_CLAUDE_MODE="quota", FAKE_CODEX_MODE="quota")
    check("V6 Ambos no limite sem alterações: para (nenhum agente elegível) e repositório intacto", r["state"] == "stopped_no_agent"
          and tree() == base_after_fresh(), r)
    fresh(); r = wf(FAKE_CLAUDE_MODE="w_ok")
    check("V7 Sem transferência: Claude conclui e promove", r["state"] == "completed" and [c["agent"] for c in calls()] == ["claude"], r)
    # impressão digital: um segundo agente nunca sobrescreve alterações desconhecidas
    fresh(); os.environ.update({k: v for k, v in env().items() if k.startswith(("MAUTRIX", "FAKE", "MX_"))}); os.environ["PATH"] = env()["PATH"]
    from mautrix_orq import write_executor
    import importlib; importlib.reload(write_executor)
    fp_old = write_executor.current_fingerprint(LAB)
    (LAB / "rascunho_local.txt").write_text("alterado por outro processo\n", encoding="utf-8")
    rep = write_executor.execute_write(task=json.loads(wtask("B").read_text()), confirm="TASK-1001", held_locks=True, expect_fingerprint=fp_old)
    check("V8 Repositório mudou entre passos: o passo seguinte é recusado, agente não inicia, nada sobrescrito",
          rep["outcome"] == "VIOLATION" and not calls() and read("rascunho_local.txt") == "alterado por outro processo\n", rep["summary"])

    # ---------------------------------------------------------------- 11. repositório de leitura (V3) intacto
    check("Z Projeto de leitura lab/projeto_descartavel não foi tocado pela V4",
          hashlib.sha256((ROOT / "lab/projeto_descartavel/texto_exemplo.txt").read_bytes()).hexdigest()
          == hashlib.sha256((SRC / "lab/projeto_descartavel/texto_exemplo.txt").read_bytes()).hexdigest())


def base_after_fresh():
    return tree()


if __name__ == "__main__":
    import traceback
    EXPECTED_CHECKS = 56   # total implementado; uma execução que termine com menos é INCOMPLETA (nunca "aprovada")
    crashed = False
    try:
        run_all()
    except BaseException:  # noqa: BLE001 - registra qualquer exceção e marca a suíte como incompleta
        traceback.print_exc()
        crashed = True
    finally:
        ok = sum(1 for _, c, _ in results if c)
        print(f"\n{ok}/{len(results)} verificações passaram (agentes SIMULADOS; esperadas {EXPECTED_CHECKS})")
        incomplete = crashed or len(results) != EXPECTED_CHECKS
        if incomplete:
            print(f"SUITE INCOMPLETA: executadas {len(results)} de {EXPECTED_CHECKS}" + (" (exceção acima)" if crashed else ""))
        if len(sys.argv) > 2 and sys.argv[1] == "--json":
            Path(sys.argv[2]).write_text(json.dumps({"python": sys.version, "platform": sys.platform, "expected": EXPECTED_CHECKS,
                                                     "executed": len(results), "crashed": crashed,
                                                     "results": [{"name": n, "ok": c} for n, c, _ in results]}, indent=2), encoding="utf-8")
        rmtree_force(TMP)
    sys.exit(0 if results and not incomplete and all(c for _, c, _ in results) else 1)
