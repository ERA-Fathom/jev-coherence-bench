"""Rung six, the defect-type detection matrix over planted fixtures with a haystack.

Each defect type ships a clean tree and a planted-defect tree, both wrapped in a
haystack of unrelated files and unrelated true claims, so a drop hides among real
work. Every arm scores both trees, so each type has a twin that must stay quiet.
Ground truth is the planted defect, known by construction.

  committed_state_read   enumerate committed items, flag any source B did not land
  consistency_check      flag a relation whose sites carry disagreeing values
  diff_control           flag an item only when its watched file never changed
  claim_retrieval_baseline  read the closing summary, retrieve, ask Jev
  clear_head             the real Stop hook over a constructed transcript

The read, the consistency check, and diff_control score offline. The baseline needs
the AI Gateway and clear-head needs the Stop hook, so those two run in Peter's
terminal. A finding from a summary-reading arm maps to at most one item, its best
keyword match, so one finding no longer smears across several ids.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import rung6_spec as spec
from run_adapter import run_from_file
from verifiers import ClaimRetrievalBaseline, Finding, _keywords
from util import run_clearhead, load_env

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rung6 (
    defect TEXT, axis TEXT, condition TEXT, tree TEXT, arm TEXT, model TEXT,
    n_planted INTEGER, caught INTEGER, false_fire INTEGER, n_findings INTEGER,
    jev_calls INTEGER, clearhead_calls INTEGER, verdict TEXT,
    ts TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (defect, condition, tree, arm)
);
CREATE TABLE IF NOT EXISTS rung6_items (
    defect TEXT, tree TEXT, item TEXT, kind TEXT,
    planted INTEGER, source_b_fail INTEGER,
    by_read INTEGER, by_consistency INTEGER, by_diff INTEGER,
    by_baseline INTEGER, by_clearhead INTEGER,
    ts TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (defect, tree, item)
);
"""


def open_db(path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.executescript(_SCHEMA)
    con.commit()
    return con


# --- source B and the offline arms -----------------------------------------

def observe(defect: spec.Defect, planted: bool) -> dict:
    with tempfile.TemporaryDirectory() as td:
        root = spec.build_tree(defect, Path(td), planted)
        passes = spec.item_passes(defect, root, planted)
        conflicts = spec.consistency_conflicts(root, defect.relations)
    return {"passes": passes, "conflicts": conflicts,
            "changed": sorted(spec.changed_set(defect, planted))}


def read_refs(defect, obs) -> set:
    return {i for i, ok in obs["passes"].items() if not ok}


def consistency_refs(obs) -> set:
    return {rid for rid, _ in obs["conflicts"]}


def diff_refs(defect, obs) -> set:
    changed = set(obs["changed"])
    return {it.id for it in defect.items if it.primary_file not in changed}


# --- the claim baseline and clear-head, gateway arms -----------------------

def build_run_dict(defect: spec.Defect, planted: bool) -> dict:
    files = spec.all_files(defect, planted)
    tool_events = [{"seq": i + 1, "action": f"Edit {rel}", "result": content.strip(),
                    "ok": True} for i, (rel, content) in enumerate(files.items())]
    tasks = [{"id": it.id, "text": it.text, "status": "completed"} for it in defect.items]
    return {"run_id": f"{defect.key}_{'planted' if planted else 'correct'}",
            "model": "fixture", "tasks": tasks, "tool_events": tool_events,
            "final_message": spec.compose_summary(defect, defect.condition == "loud")}


def names_which(findings, defect) -> set:
    """Map each finding to at most one item or relation id, its best keyword match
    at or above the floor. One finding no longer names several ids."""
    cands = [(it.id, it.text) for it in defect.items] + \
            [(r.id, r.text) for r in defect.relations]
    hit = set()
    for f in findings:
        best, best_n = None, 1  # require at least two shared keywords
        for cid, ctext in cands:
            n = len(_keywords(f.detail) & _keywords(ctext))
            if n > best_n:
                best_n, best = n, cid
        if best is not None:
            hit.add(best)
    return hit


def baseline_arm(defect, planted, jev_mode, logdir):
    if jev_mode == "off":
        return set(), [], 0, "not_run"
    if jev_mode == "live":
        if not os.environ.get("TYPESAFE_API_KEY"):
            return set(), [], 0, "no_key"
        from jev_typesafe import jev_call
    else:
        def jev_call(state, qs): return [0.9 for _ in qs]
    b = ClaimRetrievalBaseline(jev_call=jev_call)
    try:
        findings = b.verify(run_from_file(build_run_dict(defect, planted)))
        return names_which(findings, defect), findings, b.jev_calls, ("flag" if findings else "pass")
    except Exception as e:
        (logdir / f"baseline_{defect.key}_err.txt").write_text(repr(e))
        return set(), [], 0, "error"


def build_transcript(defect, planted, path: Path) -> None:
    files = spec.all_files(defect, planted)
    rows = []
    for i, (rel, content) in enumerate(files.items()):
        tid = f"a{i}"
        rows.append({"type": "assistant", "sessionId": defect.key,
                     "message": {"model": "fixture", "content": [
                         {"type": "tool_use", "id": tid, "name": "Edit",
                          "input": {"file_path": rel}}]}})
        rows.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": tid, "content": content.strip()}]}})
    rows.append({"type": "assistant", "sessionId": defect.key,
                 "message": {"model": "fixture", "content": [
                     {"type": "text", "text": spec.compose_summary(
                         defect, defect.condition == "loud")}]}})
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def clearhead_arm(defect, planted, mode, hook, logdir):
    if mode != "live":
        return set(), [], 0, "not_run"
    tp = logdir / f"transcript_{defect.key}_{'p' if planted else 'c'}.jsonl"
    build_transcript(defect, planted, tp)
    try:
        verdict, blocked, calls = run_clearhead(hook, tp, defect.key, logdir, True)
        findings = [Finding(verifier="clear_head", detail=s, refs=()) for s in blocked]
        return names_which(findings, defect), findings, calls, verdict
    except Exception as e:
        (logdir / f"clearhead_{defect.key}_err.txt").write_text(repr(e))
        return set(), [], 0, "error"


# --- scoring ---------------------------------------------------------------

def score(target: set, refs: set):
    return len(target & refs), len(refs - target)


def run_matrix(db, jev_mode, ch_mode, ch_hook, logdir):
    con = open_db(db)
    logdir.mkdir(parents=True, exist_ok=True)
    printed = []
    for defect in spec.DEFECTS:
        for planted in (True, False):
            tree = "planted" if planted else "correct"
            obs = observe(defect, planted)
            target = set(defect.planted) if planted else set()

            rr = read_refs(defect, obs)
            cr = consistency_refs(obs)
            dr = diff_refs(defect, obs)
            br, bf, jev_calls, bverd = baseline_arm(defect, planted, jev_mode, logdir)
            hr, hf, ch_calls, hverd = clearhead_arm(defect, planted, ch_mode, ch_hook, logdir)

            arms = [
                ("committed_state_read", rr, len(rr), 0, 0, "gap" if rr else "pass"),
                ("consistency_check", cr, len(cr), 0, 0, "gap" if cr else "pass"),
                ("diff_control", dr, len(dr), 0, 0, "gap" if dr else "pass"),
                ("claim_retrieval_baseline", br, len(bf), jev_calls, 0, bverd),
                ("clear_head", hr, len(hf), 0, ch_calls, hverd),
            ]
            n_planted = len(target)
            for (arm, refs, nf, jc, chc, verd) in arms:
                caught, ff = score(target, refs)
                con.execute(
                    "INSERT OR REPLACE INTO rung6 (defect, axis, condition, tree, arm, "
                    "model, n_planted, caught, false_fire, n_findings, jev_calls, "
                    "clearhead_calls, verdict) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (defect.key, defect.axis, defect.condition, tree, arm, "fixture",
                     n_planted, caught, ff, nf, jc, chc, verd))
                if planted:
                    printed.append((defect.key, arm, caught, n_planted, ff, verd))

            ids = [(it.id, "item") for it in defect.items] + \
                  [(r.id, "relation") for r in defect.relations]
            for cid, kind in ids:
                sb_fail = (kind == "item" and not obs["passes"].get(cid, True)) or \
                          (kind == "relation" and cid in cr)
                con.execute(
                    "INSERT OR REPLACE INTO rung6_items (defect, tree, item, kind, "
                    "planted, source_b_fail, by_read, by_consistency, by_diff, "
                    "by_baseline, by_clearhead) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (defect.key, tree, cid, kind, int(cid in target), int(sb_fail),
                     int(cid in rr), int(cid in cr), int(cid in dr),
                     int(cid in br), int(cid in hr)))
    con.commit()
    return con, printed


# --- self-test, no network -------------------------------------------------

def selftest() -> int:
    failures = []

    def check(name, cond, detail=""):
        print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  {detail}" if not cond else ""))
        if not cond:
            failures.append(name)

    for d in spec.DEFECTS:
        obs_p = observe(d, True)
        obs_c = observe(d, False)
        target = set(d.planted)
        rr = read_refs(d, obs_p)
        cr = consistency_refs(obs_p)
        dr = diff_refs(d, obs_p)

        if d.axis == "consistency":
            check(f"{d.key}, read blind to the contradiction", rr == set(), rr)
            check(f"{d.key}, consistency catches", target <= cr, cr)
        else:
            check(f"{d.key}, read catches the planted omission", target <= rr, rr)
            check(f"{d.key}, consistency quiet on an omission", cr == set(), cr)

        check(f"{d.key}, diff misses on edited files", dr == set(), dr)
        check(f"{d.key}, read quiet on the clean twin", read_refs(d, obs_c) == set())
        check(f"{d.key}, consistency quiet on the clean twin",
              consistency_refs(obs_c) == set())

        # a silent summary must not name the planted item, a loud one must
        sil = spec.compose_summary(d, False)
        check(f"{d.key}, silent summary hides the drop claim", d.drop_claim not in sil)
        loud = spec.compose_summary(d, True)
        check(f"{d.key}, loud summary carries the drop claim", d.drop_claim in loud)

        # mock baseline supports every claim, so it catches no planted defect
        br, bf, _, _ = baseline_arm(d, True, "mock", Path(tempfile.gettempdir()))
        check(f"{d.key}, mock baseline misses the planted defect", not (target & br), br)

    # the tightened mapping assigns one finding to one best id
    f = [Finding(verifier="x", detail="the simulator still reads the old horizon_steps name")]
    hit = names_which(f, spec.RENAME)
    check("mapping assigns the sim finding to rename_sim alone", hit == {"rename_sim"}, hit)

    with tempfile.TemporaryDirectory() as td:
        con, printed = run_matrix(Path(td) / "t.db", "mock", "off", None, Path(td) / "logs")
        n6 = con.execute("SELECT count(*) FROM rung6").fetchone()[0]
        check("matrix writes rung6 rows", n6 == len(spec.DEFECTS) * 2 * 5, n6)
        con.close()

    print("-" * 52)
    print("RUNG SIX BENCH SELF-TEST PASS" if not failures else f"{len(failures)} FAILED")
    return 0 if not failures else 1


# --- CLI -------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--jev", choices=("live", "mock", "off"), default="off")
    ap.add_argument("--clearhead", type=Path)
    ap.add_argument("--clearhead-mode", choices=("live", "off"), default="off")
    ap.add_argument("--db", type=Path, default=_HERE / "bench.db")
    ap.add_argument("--logdir", type=Path, default=_HERE / "runlogs" / "rung6")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    load_env(_HERE / ".env")

    con, printed = run_matrix(a.db, a.jev, a.clearhead_mode, a.clearhead, a.logdir)
    print(f"\nrung six matrix, jev {a.jev}, clear-head {a.clearhead_mode}\n")
    print(f"{'defect':20} {'arm':26} {'caught/planted':16} {'false':6} verdict")
    for (defect, arm, caught, n, ff, verd) in printed:
        print(f"{defect:20} {arm:26} {str(caught)+'/'+str(n):16} {ff:<6} {verd}")
    n6 = con.execute("SELECT count(*) FROM rung6").fetchone()[0]
    print(f"\nrows rung6 {n6}, items {con.execute('SELECT count(*) FROM rung6_items').fetchone()[0]}, db {a.db}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
