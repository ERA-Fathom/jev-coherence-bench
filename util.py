"""Small harness utilities, an env loader and the clear-head invocation.

Neither depends on anything private. load_env reads a .env into the process
without overwriting an existing value. run_clearhead shells the third-party
clear-head Stop hook when the caller supplies its path, and reports not_run
otherwise, so the clear-head arm stays optional.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def load_env(path: Path) -> None:
    """Read KEY=VALUE lines into the environment without overwriting a value
    already set, so an explicit export still wins."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def run_clearhead(stop_verify: Path, transcript: Path, session_id: str,
                  logdir: Path, live: bool) -> tuple[str, list[str], int]:
    """Invoke the third-party clear-head Stop hook against its native input.

    clear-head reads the session transcript named in the hook payload and prints
    a block decision when it finds a claim contradicted by or absent from what
    the session read. Silence is a pass. This ships no clear-head code, it only
    shells a hook the user points at, so the arm is bring-your-own.
    """
    if not live:
        return "not_run", [], 0
    payload = json.dumps({"session_id": session_id,
                          "transcript_path": str(transcript),
                          "stop_hook_active": False})
    env = dict(os.environ)
    env["JEV_HOOK"] = "on"
    env.pop("JEV_FAIL_CLOSED", None)
    proc = subprocess.run([sys.executable, str(stop_verify)], input=payload,
                          capture_output=True, text=True, env=env,
                          cwd=str(stop_verify.parent), timeout=600)
    out = proc.stdout.strip()
    (logdir / "clearhead_stdout.txt").write_text(out + "\n")
    if proc.stderr.strip():
        (logdir / "clearhead_stderr.txt").write_text(proc.stderr)
    if not out:
        return "pass", [], 2
    try:
        reason = json.loads(out).get("reason", "")
    except json.JSONDecodeError:
        return "unparsed", [out], 2
    blocked = [ln.strip()[2:].strip() for ln in reason.splitlines()
               if ln.strip().startswith("- [")]
    return "block", blocked, 2
