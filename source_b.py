"""Source B, the observed record drawn from the worktree, not the agent's ticks.

observe() runs once per run while the worktree still exists, computes the set of
files the run changed from the git status, and checks every deliverable's
verifier against the final tree. The result is the objective record, frozen into
the run file so every arm scores against the same ground truth offline and
repeatably. No self-reported checklist enters here, so a sloppy or dishonest
ledger can neither inflate nor hide a drop.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from rung3_spec import build_spec, verify


def changed_files(worktree: Path, base: str = "pre-v2-base") -> list[str]:
    """Every path the run touched against the base, committed and uncommitted
    alike, plus new untracked files. Diffing against the base commit rather than
    reading only the porcelain status catches a run that committed its work, so
    the record does not miss a committed edit."""
    paths = set()
    diff = subprocess.run(["git", "-C", str(worktree), "diff", "--name-only", base],
                          capture_output=True, text=True)
    if diff.returncode == 0:
        for line in diff.stdout.splitlines():
            if line.strip():
                paths.add(line.strip().strip('"'))
    else:
        # no usable base ref, fall back to the porcelain status
        st = subprocess.run(["git", "-C", str(worktree), "status", "--porcelain"],
                            capture_output=True, text=True).stdout
        for line in st.splitlines():
            body = line[3:] if len(line) > 3 else line.strip()
            if " -> " in body:
                body = body.split(" -> ", 1)[1]
            if body.strip():
                paths.add(body.strip().strip('"'))
    others = subprocess.run(
        ["git", "-C", str(worktree), "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True).stdout
    for line in others.splitlines():
        if line.strip():
            paths.add(line.strip().strip('"'))
    return sorted(paths)


def observe(worktree: Path, base: str = "pre-v2-base", level: int = 1) -> dict:
    """The frozen source-B record for one run at a given horizon level."""
    changed = set(changed_files(worktree, base))
    deliverables = {}
    for d in build_spec(level):
        passed, detail = verify(d, worktree, changed)
        deliverables[d.id] = {"passed": passed, "detail": detail}
    return {"changed": sorted(changed), "level": level, "deliverables": deliverables}


def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description="compute the source-B record for a worktree")
    ap.add_argument("--worktree", type=Path, required=True)
    ap.add_argument("--level", type=int, default=1)
    ap.add_argument("--out", type=Path, help="write the record as JSON")
    a = ap.parse_args(argv)
    rec = observe(a.worktree, level=a.level)
    dropped = [k for k, v in rec["deliverables"].items() if not v["passed"]]
    print(f"changed files {len(rec['changed'])}, deliverables {len(rec['deliverables'])}, "
          f"dropped {len(dropped)} {dropped}")
    if a.out:
        a.out.write_text(json.dumps(rec, indent=2) + "\n")
        print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
