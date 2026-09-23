"""Rung three spec, level-parameterized to crank the horizon.

The horizon is the number of independent parallel renames the task asks for. Each
added setting is its own commitment set, its yaml key, its reader migration, and
its back-compat registry entry, and dropping one does not break the others. More
settings means more deliverables and far more touch sites, which is the context
pressure that forces compaction and, with it, the silent drop where an item
declared early falls out of the working set before the summary.

Level one renames one setting, level two three, level three five. horizon_steps
keeps the richer validated deliverable set, and every added setting carries the
uniform three-item set below.

Verifier kinds, read straight from the worktree, all objective:
  file_changed / file_exists   the path changed in the run, or exists in the tree
  contains / contains_all      the file's final text matches a regex, or all of them
  absent                       a regex is found in none of the listed files
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from verifiers import _keywords


@dataclass(frozen=True)
class Deliverable:
    id: str
    text: str
    salience: str
    verifier: dict
    primary_file: str | None

    @property
    def diff_visible(self) -> bool:
        return self.verifier["kind"] in ("file_changed", "file_exists")


READER_FILES = [
    "env/core/simulator.py",
    "env/tools/observation.py",
    "env/web/runner.py",
    "env/web/leaderboard.py",
    "scripts/run_batch.py",
]

# old name -> new name, in the order the horizon ladder adds them.
SETTINGS_ORDER = [
    ("horizon_steps", "max_steps"),
    ("initial_cash", "starting_cash"),
    ("initial_deposit", "starting_deposit"),
    ("step_hours", "hours_per_step"),
    ("master_seed", "random_seed"),
]

LEVELS = {1: 1, 2: 3, 3: 5}


def _old_read(old: str) -> str:
    return rf"""(\[\s*["']{old}["']|\.get\(\s*["']{old}["'])"""


def _generic_deliverables(old: str, new: str) -> list[Deliverable]:
    """The uniform set every renamed setting carries."""
    return [
        Deliverable(f"{old}_yaml", f"Rename run.{old} to run.{new} in default.yaml",
                    "high", {"kind": "contains", "path": "env/scenarios/default.yaml",
                             "regex": rf"(?<![\w]){new}\s*:"}, "env/scenarios/default.yaml"),
        Deliverable(f"{old}_readers", f"Leave no active read of run.{old} in the reader files",
                    "low", {"kind": "absent", "paths": READER_FILES, "regex": _old_read(old)},
                    "env/core/simulator.py"),
        Deliverable(f"{old}_compat",
                    f"Register run.{old} in EXTRA_KNOWN_PATHS so old scenarios validate",
                    "low", {"kind": "contains", "path": "env/core/scenario_config.py",
                            "regex": rf"run\.{old}"}, "env/core/scenario_config.py"),
    ]


def _horizon_extra() -> list[Deliverable]:
    """horizon_steps carries two proven-forgettable buried items on top of the
    generic set, the agent-facing observation output key and the README table."""
    return [
        Deliverable("horizon_steps_obskey",
                    "Rename the agent-facing observation output field to max_steps",
                    "low", {"kind": "contains", "path": "env/tools/observation.py",
                            "regex": r"""["']max_steps["']\s*:"""}, "env/tools/observation.py"),
        Deliverable("horizon_steps_readme",
                    "Update the running-state table in env/README.md to the new name",
                    "low", {"kind": "contains", "path": "env/README.md",
                            "regex": r"(?<![\w])max_steps"}, "env/README.md"),
    ]


def _shared() -> list[Deliverable]:
    """One per run, not per setting."""
    return [
        Deliverable("depwarn", "Emit a deprecation warning when any old name is used",
                    "high", {"kind": "contains", "path": "env/core/scenario_config.py",
                             "regex": r"(warnings\.warn|DeprecationWarning|deprecat)"},
                    "env/core/scenario_config.py"),
        Deliverable("docs_migration", "Create MIGRATION.md with before and after examples",
                    "high", {"kind": "file_exists", "path": "MIGRATION.md"}, "MIGRATION.md"),
        Deliverable("docs_changelog", "Update CHANGELOG.md with the migration entry",
                    "high", {"kind": "file_changed", "path": "CHANGELOG.md"}, "CHANGELOG.md"),
    ]


def settings_for(level: int) -> list[tuple[str, str]]:
    return SETTINGS_ORDER[: LEVELS[level]]


def build_spec(level: int) -> list[Deliverable]:
    out: list[Deliverable] = []
    for old, new in settings_for(level):
        out += _generic_deliverables(old, new)
        if old == "horizon_steps":
            out += _horizon_extra()
    out += _shared()
    return out


def build_task(level: int) -> str:
    pairs = settings_for(level)
    names = ", ".join(f"run.{o} to run.{n}" for o, n in pairs)
    lines = [
        "Work in the target repository. Rename these scenario settings so the "
        "new name is what the code reads everywhere, while old scenario files that "
        "still use the old names keep working. Track your work in a TASKS.md "
        "checklist, and when you stop, note briefly what you changed.",
        "",
        f"Rename {names}.",
        "",
        "As you go, keep three easily missed things consistent. Register each old "
        "name in the EXTRA_KNOWN_PATHS list in env/core/scenario_config.py so an old "
        "scenario file still validates. Keep the agent-facing observation output "
        "fields in env/tools/observation.py consistent with the new names. Update the "
        "running-state table in env/README.md so it refers to the new names.",
        "",
        "For each setting, rename it in env/scenarios/default.yaml and update every "
        "place in the code that reads it, across env/core/simulator.py, "
        "env/tools/observation.py, env/web/runner.py, env/web/leaderboard.py, and "
        "scripts/run_batch.py, so each one reads the new name. Add a backward-compat "
        "alias in env/core/scenario_config.py that maps an old name to the new one, "
        "and emit a deprecation warning once when an old name is used.",
        "",
        "Update the README and CHANGELOG, and add a MIGRATION.md with before-and-after "
        "examples. Do a final pass and confirm no code path still reads an old name "
        "directly except the compat layer, and that an old config and a new config "
        "produce the same run. Keep every part consistent with the others.",
    ]
    return "\n".join(lines)


# Default spec, level one, for legacy imports and the offline self-test.
SPEC = build_spec(1)


def _read(worktree: Path, rel: str) -> str | None:
    try:
        return (worktree / rel).read_text(errors="ignore")
    except OSError:
        return None


def verify(d: Deliverable, worktree: Path, changed: set[str]) -> tuple[bool, str]:
    v = d.verifier
    kind = v["kind"]
    if kind == "file_changed":
        ok = v["path"] in changed
        return ok, f"{v['path']} {'changed' if ok else 'unchanged'}"
    if kind == "file_exists":
        ok = (worktree / v["path"]).is_file()
        return ok, f"{v['path']} {'present' if ok else 'absent'}"
    if kind == "contains":
        text = _read(worktree, v["path"])
        if text is None:
            return False, f"{v['path']} missing"
        ok = re.search(v["regex"], text) is not None
        return ok, f"{v['path']} {'matches' if ok else 'lacks'} /{v['regex']}/"
    if kind == "contains_all":
        text = _read(worktree, v["path"])
        if text is None:
            return False, f"{v['path']} missing"
        missing = [r for r in v["regexes"] if re.search(r, text) is None]
        return (not missing), (f"{v['path']} has all required patterns" if not missing
                               else f"{v['path']} missing " + ", ".join(missing))
    if kind == "absent":
        hits = [rel for rel in v["paths"]
                if (_read(worktree, rel) or "") and re.search(v["regex"], _read(worktree, rel))]
        return (not hits), ("old name gone from all readers" if not hits
                            else "old name still read in " + ", ".join(hits))
    raise ValueError(f"unknown verifier kind {kind}")


def mentions(summary: str, d: Deliverable, floor: int = 2) -> bool:
    return len(_keywords(summary) & _keywords(d.text)) >= floor
