"""Lean 4 / Mathlib interface: challenge indexing, safe proof assembly, sandboxed checking.

Safety model (the model's text is untrusted code):
  * the model returns ONLY a tactic block; the theorem statement is spliced in from the repository file,
    so a proof can never change what is being proved;
  * metaprogramming / new declarations / sorry / axioms are rejected before Lean runs;
  * Lean runs as an unprivileged user with an empty environment (no API keys), under a timeout;
  * success requires `#print axioms <theorem>` to list only propext, Classical.choice, Quot.sound.
"""
from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import subprocess
import time

ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
_BANNED_WORDS = re.compile(r"\b(admit|axiom|native_decide|unsafe|implemented_by|extern|macro|macro_rules|syntax|elab|run_cmd|run_tac|"
                           r"initialize|opaque|import|namespace|set_option|attribute|instance|theorem|lemma|def|abbrev|structure|inductive|"
                           r"class|noncomputable|private|protected|partial)\b")
_BANNED_SYMBOLS = ("#", "@[", "/-", "-/")
_ATTR = re.compile(r"@\[category research open[^\]]*\]\s*(?:theorem|lemma)\s+([^\s:(\[{]+)")
_TERMINAL = re.compile(r":=\s*by\s*sorry")


def cfg():
    return {"project": os.environ.get("RSI_LEAN_PROJECT", "/home/rsi/formal-conjectures"), "user": os.environ.get("RSI_LEAN_USER", "rsi"),
            "timeout": int(os.environ.get("RSI_LEAN_TIMEOUT", "900")), "bin": os.environ.get("RSI_LEAN_BIN")}


def lean_available():
    c = cfg()
    return bool(c["bin"]) or os.path.isdir(c["project"])


# ---------- indexing ----------
def parse_file(text: str) -> list[dict]:
    out = []
    for m in _ATTR.finditer(text):
        name = m.group(1)
        t = _TERMINAL.search(text, m.end())
        if not t:
            continue
        stmt_start = m.end()
        statement = text[stmt_start:t.start()].strip()
        if "theorem " in statement or "lemma " in statement:      # ran into the next declaration
            continue
        ns, stack = [], []
        for line in text[:m.start()].splitlines():
            a = re.match(r"\s*namespace\s+(\S+)", line)
            b = re.match(r"\s*end\s+(\S+)", line)
            if a:
                stack.append(a.group(1))
            elif b and stack and stack[-1] == b.group(1):
                stack.pop()
        ns = ".".join(stack)
        out.append({"name": name, "full_name": f"{ns}.{name}" if ns else name, "statement": statement,
                    "terminal": [t.start(), t.end()], "has_answer": "answer(sorry)" in statement,
                    "context": text[:m.start()][-3500:]})
    return out


def index_repo(repo: str, out_json: str, subdir="FormalConjectures/ErdosProblems") -> int:
    base = os.path.join(repo, subdir)
    items = []
    for fn in sorted(os.listdir(base), key=lambda s: (len(s), s)):
        if not fn.endswith(".lean"):
            continue
        path = os.path.join(base, fn)
        text = open(path, encoding="utf-8").read()
        for c in parse_file(text):
            items.append({"id": f"{fn[:-5]}:{c['name']}", "file": os.path.relpath(path, repo), **c,
                          "file_sha": hashlib.sha256(text.encode()).hexdigest()[:16]})
    os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
    with open(out_json, "w") as f:
        json.dump({"repo": repo, "challenges": items}, f)
    return len(items)


# ---------- assembly ----------
def sanitize_tactics(tactics: str, allow_sorry: bool = False) -> str:
    t = tactics.strip("\n")
    if not allow_sorry and re.search(r"\bsorry\b", t):
        raise ValueError("forbidden word 'sorry'")
    if not t.strip() or len(t) > 20000:
        raise ValueError("empty or oversized proof")
    for s in _BANNED_SYMBOLS:
        if s in t:
            raise ValueError(f"forbidden symbol {s!r}")
    m = _BANNED_WORDS.search(t)
    if m:
        raise ValueError(f"forbidden word {m.group(0)!r}")
    return t


def splice(text: str, challenge: dict, tactics: str, answer: str | None = None) -> str:
    a, b = challenge["terminal"]
    body = "\n".join("  " + ln if ln.strip() else ln for ln in tactics.splitlines())
    new = text[:a] + ":= by\n" + body + text[b:]
    if answer is not None:
        # the answer(sorry) placeholder lives in the statement, which precedes `a`
        head_end = a
        new = new[:head_end].replace("answer(sorry)", f"answer({answer})", 1) + new[head_end:]
    return new


def extract_tactics(model_text: str) -> str:
    m = re.search(r"```(?:lean4?|lean)?\s*\n(.*?)```", model_text, re.S)
    t = m.group(1) if m else model_text
    t = re.sub(r"^\s*ANSWER:.*\n", "", t, flags=re.M)
    hdr = re.search(r"^(?:theorem|lemma)\b.*?:=\s*by[ \t]*\n?", t, re.S | re.M)
    if hdr:
        t = t[hdr.end():]
    t = re.sub(r"^[ \t]*by[ \t]*\n", "", t)
    lines = t.splitlines()
    ind = min((len(l) - len(l.lstrip()) for l in lines if l.strip()), default=0)
    return "\n".join(l[ind:] for l in lines).strip("\n")


def extract_answer(model_text: str) -> str | None:
    m = re.search(r"ANSWER:\s*(True|False)", model_text)
    return m.group(1) if m else None


# ---------- running Lean ----------
def _run(path_rel: str) -> tuple[int, str]:
    c = cfg()
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": f"/home/{c['user']}" if os.path.isdir(f"/home/{c['user']}") else os.environ.get("HOME", "/tmp")}
    if c["bin"]:
        argv = [c["bin"], os.path.join(c["project"], path_rel)]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=c["timeout"], env=env)
        return r.returncode, (r.stdout + r.stderr)[-20000:]
    shell = f"cd {c['project']} && timeout {c['timeout']} $HOME/.elan/bin/lake env lean {path_rel}"
    argv = ["bash", "-c", shell]
    try:
        pwd.getpwnam(c["user"])
        if os.geteuid() == 0:
            argv = ["runuser", "-u", c["user"], "--", "env", "-i", f"HOME={env['HOME']}", f"PATH={env['HOME']}/.elan/bin:/usr/local/bin:/usr/bin:/bin", "bash", "-c", shell]
    except KeyError:
        pass
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=c["timeout"] + 60, env=env if argv[0] == "bash" else None)
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    return r.returncode, (r.stdout + r.stderr)[-20000:]


def write_attempt(text: str, tag: str) -> str:
    c = cfg()
    d = os.path.join(c["project"], "Attempts")
    os.makedirs(d, exist_ok=True)
    rel = os.path.join("Attempts", re.sub(r"[^A-Za-z0-9_]", "_", tag) + ".lean")
    with open(os.path.join(c["project"], rel), "w", encoding="utf-8") as f:
        f.write(text)
    try:
        u = pwd.getpwnam(c["user"])
        if os.geteuid() == 0:
            os.chown(d, u.pw_uid, u.pw_gid)
            os.chown(os.path.join(c["project"], rel), u.pw_uid, u.pw_gid)
    except KeyError:
        pass
    return rel


def check(text: str, full_name: str, tag: str, allow_sorry=False) -> dict:
    """Compile `text` (+ #print axioms).  ok => accepted by the Lean kernel with only standard axioms."""
    t0 = time.time()
    rel = write_attempt(text + f"\n\n#print axioms {full_name}\n", tag)
    rc, out = _run(rel)
    errors = [out[max(0, m.start() - 200): m.end() + 500] for m in re.finditer(r":\s*error", out)][:5]
    am = re.search(r"depends on axioms:\s*\[([^\]]*)\]", out)
    axioms = [a.strip() for a in am.group(1).split(",") if a.strip()] if am else ([] if "does not depend on any axioms" in out else None)
    if allow_sorry:
        ok = rc == 0 and not errors
    else:
        ok = rc == 0 and not errors and axioms is not None and set(axioms) <= ALLOWED_AXIOMS
    return {"ok": ok, "errors": errors, "axioms": axioms, "seconds": round(time.time() - t0, 1), "tail": out[-1500:], "rc": rc}


def recheck_saved(evidence: dict, challenge: dict, repo_text: str) -> list[tuple[str, bool, dict]]:
    """Independent audit of a saved proof: statement fidelity + a fresh kernel check."""
    saved = open(evidence["lean_file"], encoding="utf-8").read()
    rebuilt = splice(repo_text, challenge, sanitize_tactics(evidence["tactics"]), evidence.get("answer"))
    fidelity = saved == rebuilt
    res = check(saved, challenge["full_name"], "recheck_" + hashlib.sha256(saved.encode()).hexdigest()[:10])
    return [("statement_fidelity", fidelity, {"saved_equals_spliced_original": fidelity}),
            ("lean_kernel_recheck", res["ok"], {"axioms": res["axioms"], "errors": res["errors"][:1]})]
