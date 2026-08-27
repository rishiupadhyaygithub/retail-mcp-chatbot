#!/usr/bin/env python3
"""One command that checks every path a change can break.

    python3 scripts/verify_all.py           # everything that runs offline
    python3 scripts/verify_all.py --slow    # also the retrieval harness (needs Chroma)

This exists because of two regressions that reached commits. Bumping
`schema_version` in `eval/ground_truth.json` made `eval/harness.py` refuse to
run, and `client/loop.py` used `NAME_SEPARATOR` without importing it. Both were
caught later by accident. The cause was not carelessness in one edit: it was
that this repo has several independent entry points — the pytest suite, two
harnesses, a demo script, a server, a UI — and editing for one of them does not
exercise the others. Anything verified only by a command typed once is
unverified from the next commit onward.

So the rule is: every claim this repo makes about itself is checked here, and
documentation counts as a claim. A README that says 24 corpus documents when
there are 22 is a defect, because the next person plans work from it.

Exit codes: 0 = all checks passed. 1 = at least one failed.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str]] = []


def record(name: str, ok: bool | None, detail: str = "") -> None:
    results.append((name, PASS if ok else (SKIP if ok is None else FAIL), detail))


def run(cmd: list[str], timeout: int = 900) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True,
                              text=True, timeout=timeout)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except FileNotFoundError as exc:
        return 127, str(exc)


# --------------------------------------------------------------------------
# Code health
# --------------------------------------------------------------------------

def check_compiles() -> None:
    code, out = run([sys.executable, "-m", "compileall", "-q",
                     "client", "server", "data", "eval", "scripts", "tests"])
    record("every Python file compiles", code == 0, out.strip()[:200])


def check_tests() -> None:
    code, out = run([sys.executable, "-m", "pytest", "tests/", "-q"])
    tail = [ln for ln in out.splitlines() if "passed" in ln or "failed" in ln]
    record("pytest suite", code == 0, tail[-1] if tail else out.strip()[:200])


def check_imports_resolve() -> None:
    """Import each entry point. A missing import is invisible to compileall."""
    modules = [
        ("client.loop", "client"),
        ("client.mcp_client", "client"),
        ("client.workflow", "client"),
        ("client.composite", "client"),
        ("client.app", "client"),
        ("server.main", "server"),
        ("server.records", "server"),
        ("server.retrieval", "server"),
    ]
    broken = []
    for module, extra_path in modules:
        code, out = run([
            sys.executable, "-c",
            f"import sys; sys.path[:0]=['.','{extra_path}']; "
            f"__import__('{module}')",
        ], timeout=300)
        if code != 0:
            last = [ln for ln in out.strip().splitlines() if ln.strip()]
            broken.append(f"{module}: {last[-1] if last else 'failed'}")
    record("every module imports", not broken, "; ".join(broken)[:300])


# --------------------------------------------------------------------------
# Cross-file consistency: the failures that slipped through before
# --------------------------------------------------------------------------

def check_ground_truth_readable_by_both_harnesses() -> None:
    """The exact regression: a schema bump one harness accepted and the other did not."""
    gt_path = REPO_ROOT / "eval" / "ground_truth.json"
    try:
        gt = json.loads(gt_path.read_text())
    except Exception as exc:  # noqa: BLE001
        record("ground_truth.json parses", False, str(exc)[:200])
        return
    record("ground_truth.json parses", True)

    version = gt.get("schema_version")
    harness_src = (REPO_ROOT / "eval" / "harness.py").read_text()
    match = re.search(r"schema_version.*?not in \(([\d, ]+)\)", harness_src)
    accepted = {int(v) for v in match.group(1).split(",") if v.strip()} if match else set()
    record(
        "retrieval harness accepts the current ground-truth schema",
        version in accepted,
        f"ground truth is v{version}; harness.py accepts {sorted(accepted) or 'unknown'}",
    )

    labels = {q["number"] for q in gt.get("routing_labels", [])}
    expected = set(range(1, 29))
    record("routing labels cover all 28 questions", labels == expected,
           f"missing {sorted(expected - labels)}" if labels != expected else "")


def check_eval_set_matches_ground_truth() -> None:
    """eval_set.md section C requires the two to change in the same commit."""
    gt = json.loads((REPO_ROOT / "eval" / "ground_truth.json").read_text())
    md = (REPO_ROOT / "eval" / "eval_set.md").read_text()

    mismatches = []
    for question in gt.get("questions", []):
        for doc in question.get("expected_docs", []):
            if doc not in md:
                mismatches.append(f"Q{question['number']} expects {doc}, absent from eval_set.md")
    record("expected documents appear in eval_set.md", not mismatches,
           "; ".join(mismatches)[:300])


def check_documented_counts() -> None:
    """A count stated in prose is a claim, and a wrong one misleads planning."""
    corpus = len(list((REPO_ROOT / "data" / "corpus").rglob("*.md")))
    readme = (REPO_ROOT / "README.md").read_text()
    claimed = {int(n) for n in re.findall(r"(\d+) markdown (?:docs|files)", readme)}
    record(
        "README corpus count matches the corpus",
        not claimed or claimed == {corpus},
        f"README says {sorted(claimed)}, corpus has {corpus}",
    )

    tools = (REPO_ROOT / "server" / "main.py").read_text().count("@mcp.tool")
    tool_claims = {int(n) for n in re.findall(r"(\d+) tools", readme)}
    record("README tool count matches the server",
           not tool_claims or tool_claims == {tools},
           f"README says {sorted(tool_claims)}, server defines {tools}")


def check_prompt_version_docs() -> None:
    """prompts/README claimed v1 was active while loop.py loaded v2."""
    loop_src = (REPO_ROOT / "client" / "loop.py").read_text()
    match = re.search(r"system_prompt_(v\d+)\.md", loop_src)
    active = match.group(1) if match else "?"

    prompt_file = REPO_ROOT / "prompts" / f"system_prompt_{active}.md"
    record(f"the prompt loop.py loads exists ({active})", prompt_file.is_file())

    readme = (REPO_ROOT / "prompts" / "README.md").read_text()
    # `\**` matters: the README writes "— **active**", and without it this
    # pattern matched nothing, `claimed` came back empty, and the check passed on
    # the empty case — it could never fail, whatever the README said.
    claimed = re.findall(r"system_prompt_(v\d+)\.md`?\s*—\s*\**active", readme)
    # An empty match is now a failure, not a pass. A README that marks no prompt
    # active is exactly the drift this check exists to catch.
    record("prompts/README names the prompt actually loaded",
           bool(claimed) and active in claimed,
           f"loop.py loads {active}; README calls {claimed} active")


def check_servers_config() -> None:
    config = json.loads((REPO_ROOT / "client" / "servers.json").read_text())
    servers = config.get("servers", [])
    names = [s["name"] for s in servers]
    record("server names are unique", len(names) == len(set(names)), str(names))
    record("every server declares url and timeout",
           all(s.get("url") and s.get("timeout_seconds") for s in servers))
    # No tool names may be configured: contract v1 §9 requires runtime discovery.
    record("servers.json hardcodes no tool names",
           not any("tool" in k.lower() for s in servers for k in s))

    # An address ending .0 or .255 in a /24 is the network or broadcast address,
    # never a host, so such an entry can never connect however healthy the peer
    # is. `hospitality` was configured as 10.10.180.0 and its failures were read
    # as "teammate's machine is off" for far too long.
    # Contract v1 §7 is the agreed address table and says "update this table
    # immediately if any address changes, other clients depend on it". Drift
    # between it and servers.json means one of the two is lying about where a
    # teammate's server lives, which surfaces as an unexplained timeout on
    # interop day.
    contract = (REPO_ROOT / "contract" / "contract_v1.md").read_text()
    agreed: dict[str, str] = {}
    for row in re.finditer(r"\|\s*\d\s*\|\s*(\w[\w ]*?)\s*\|\s*([\d.]+)\s*\|\s*(\d+)\s*\|", contract):
        agreed[row.group(1).strip().lower()] = f"{row.group(2)}:{row.group(3)}"

    drift = []
    for server in servers:
        want = agreed.get(server["name"].lower())
        if not want:
            continue  # address still pending in the contract
        host = re.search(r"//([^/]+)/", server.get("url", ""))
        # Retail points at loopback locally by design; the contract records the
        # LAN address teammates dial, so only peers are compared.
        if host and server["name"].lower() != "retail" and host.group(1) != want:
            drift.append(f"{server['name']}: servers.json {host.group(1)} vs contract {want}")
    record("peer addresses match contract v1 §7", not drift, "; ".join(drift))

    enabled_bad, disabled_bad = [], []
    for server in servers:
        host_match = re.search(r"//(\d+\.\d+\.\d+\.(\d+))[:/]", server.get("url", ""))
        if host_match and host_match.group(2) in ("0", "255"):
            kind = "network" if host_match.group(2) == "0" else "broadcast"
            entry = f"{server['name']}={host_match.group(1)} ({kind} address)"
            (enabled_bad if server.get("enabled") else disabled_bad).append(entry)
    # Enabled and unroutable breaks this run; disabled and unroutable is a trap
    # waiting for interop day, so it is reported without failing the build.
    record("no ENABLED server on an unroutable address", not enabled_bad,
           "; ".join(enabled_bad))
    record("disabled servers have routable addresses",
           None if disabled_bad else True,
           ("fix before enabling: " + "; ".join(disabled_bad)) if disabled_bad else "")


def check_generated_files_untracked() -> None:
    """Databases are rebuilt by seeding; tracking them churns binaries."""
    code, out = run(["git", "ls-files"])
    tracked = out.splitlines()
    offenders = [f for f in tracked if f.endswith(".db")]
    record("no generated .db files tracked", not offenders, ", ".join(offenders))


def check_slow_retrieval_harness() -> None:
    code, out = run([sys.executable, "eval/harness.py"], timeout=1800)
    if code == 3:
        record("retrieval harness", None, "Chroma collection missing — run data/ingest.py")
        return
    passed = "PASS" in out and code == 0
    recall = re.search(r"Recall@5.*?(\d+\.\d+)%", out)
    record("retrieval harness runs and scores", passed,
           f"Recall@5 {recall.group(1)}%" if recall else out.strip()[-160:])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--slow", action="store_true",
                        help="also run the retrieval harness (needs Chroma running)")
    args = parser.parse_args()

    print("verifying...\n")
    check_compiles()
    check_imports_resolve()
    check_ground_truth_readable_by_both_harnesses()
    check_eval_set_matches_ground_truth()
    check_documented_counts()
    check_prompt_version_docs()
    check_servers_config()
    check_generated_files_untracked()
    check_tests()
    if args.slow:
        check_slow_retrieval_harness()

    width = max(len(name) for name, _, _ in results)
    failures = 0
    for name, status, detail in results:
        if status == FAIL:
            failures += 1
        print(f"  {status:4}  {name.ljust(width)}  {detail}".rstrip())

    print()
    if failures:
        print(f"{failures} check(s) FAILED")
    else:
        print(f"all {len(results)} checks passed"
              + ("" if args.slow else "  (add --slow for the retrieval harness)"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
