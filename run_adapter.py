"""Source A adapter, an agent's own task list into committed state.

Rung two runs a real agent rather than a synthetic event stream. Source A takes
the commitments from the agent's declared task list, so no frontier extractor
sits in the loop. The expected set is every task the agent declared. The record
is every task it marked completed. A task declared and left uncompleted while the
run reports done is the dropped commitment the read catches and a claim reader
misses.

Run file shape:
{
  "run_id": "...",
  "model": "...",
  "tasks": [{"id": "t1", "text": "...", "status": "completed|pending|in_progress"}, ...],
  "tool_events": [{"seq": 1, "action": "...", "result": "...", "ok": true}, ...],
  "final_message": "..."
}

tool_events record what actually ran, kept for the audit and a later value-level
check. This first cut builds the record from the task status the agent set, which
is the right surface for the silent drop. A task marked done that no tool ever
performed is confabulation, the claim baseline's job, and it stays out of scope
here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from verifiers import CommittedState, Event, Run


def load_run_file(path) -> dict:
    return json.loads(Path(path).read_text())


def committed_state_from_tasklist(run: dict) -> CommittedState:
    tasks = run.get("tasks", [])
    expected = tuple(
        Event(seq=i, type="commitment", text=t.get("text", ""), id=str(t.get("id", "")))
        for i, t in enumerate(tasks)
    )
    record = tuple(
        Event(seq=i, type="completion", text=t.get("text", ""), id=str(t.get("id", "")))
        for i, t in enumerate(tasks)
        if str(t.get("status", "")).lower() == "completed"
    )
    return CommittedState(expected=expected, record=record)


def run_from_file(run: dict) -> Run:
    """The transcript the claim baseline reads, task list and tool events as the
    body and the final message as the closing claim."""
    events = []
    seq = 0
    for t in run.get("tasks", []):
        seq += 1
        events.append(Event(seq=seq, type="commitment", text=t.get("text", ""), id=str(t.get("id", ""))))
    for te in run.get("tool_events", []):
        seq += 1
        ok = te.get("ok", True)
        events.append(Event(seq=seq, type="action" if ok else "failed_action",
                            text=f"{te.get('action', '')} -> {te.get('result', '')}"))
    seq += 1
    events.append(Event(seq=seq, type="final", text=run.get("final_message", "")))
    return Run(run_id=run.get("run_id", "run"), events=tuple(events))
