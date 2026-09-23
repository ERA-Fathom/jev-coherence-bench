"""Rung six spec v2, planted defect types with a haystack around each one.

Rungs two through five measured one failure mode, a silently dropped
reader-consistency rename. Rung six asks whether the read's detection edge holds
across defect types that differ in kind, and where another catcher takes over.

Detection is a property of the verifier, not of how the defect arose, so a planted
defect is a fair probe of what each arm catches. Each type ships a clean tree and a
planted-defect tree, both wrapped in a haystack of unrelated files and unrelated
true claims, so a drop is hidden among real work the way it is in a live run. The
silent summaries never assert the dropped item, so a summary reader has nothing to
retrieve against it, which is what makes the drop silent. The loud type asserts the
dropped item is complete, the one condition that hands a summary reader a false
claim to check.

Five types span three axes.
  rename_omission     an old name still read after a rename, the rung-three control
  addition_omission   a new field wired into some readers and missed at one
  stale_reference     a definition renamed but an old reference left in a doc
  contradiction       two present sites whose values disagree, the consistency axis
  confab_loud         an omission the closing summary asserts as complete, loud

The read enumerates committed items and checks each against source B, so it catches
an omission and stays blind to a contradiction where both items are present. A
consistency relation carries the contradiction check. Both stay measurement
instruments here and hold no hosted policy.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from rung3_spec import verify, _read  # noqa: E402


@dataclass(frozen=True)
class Item:
    id: str
    text: str
    verifier: dict
    primary_file: str


@dataclass(frozen=True)
class Relation:
    id: str
    text: str
    sites: tuple  # ((relpath, regex-with-one-capture-group), ...)


@dataclass(frozen=True)
class Defect:
    key: str
    axis: str
    condition: str            # silent or loud
    files_correct: dict
    mutations: dict
    items: tuple
    relations: tuple
    planted: tuple            # item or relation ids the plant makes fail
    done_claims: dict         # item id -> a true claim, used for items not planted
    drop_claim: str           # the claim asserting the planted item, added only when loud


def _absent(paths, regex):
    return {"kind": "absent", "paths": list(paths), "regex": regex}


def _contains(path, regex):
    return {"kind": "contains", "path": path, "regex": regex}


# --- the haystack, vocabulary kept distinct from every item ----------------

HAYSTACK_MODULES = [
    "ledger", "cache", "retry", "auth", "serializer", "router", "scheduler",
    "metrics", "backoff", "pool", "codec", "limiter", "tracer", "warmup",
    "sharder", "digest", "envelope", "cursor", "batcher", "reaper",
]


def haystack_files() -> dict:
    return {f"pkg/{m}.py": f"def {m}_handle(payload):\n    return payload  # {m} helper\n"
            for m in HAYSTACK_MODULES}


def haystack_claims() -> list:
    return [f"Refactored the {m} helper onto the shared base class." for m in HAYSTACK_MODULES]


# --- rename_omission, the rung-three control -------------------------------

RENAME = Defect(
    key="rename_omission", axis="omission_code", condition="silent",
    files_correct={
        "config.yaml": "run:\n  max_steps: 100\n",
        "sim.py": 'steps = cfg["max_steps"]\n',
        "obs.py": 'out["max_steps"] = cfg["max_steps"]\n',
    },
    mutations={"sim.py": 'steps = cfg["horizon_steps"]\n'},
    items=(
        Item("rename_config", "config.yaml reads the new name max_steps",
             _contains("config.yaml", r"max_steps\s*:"), "config.yaml"),
        Item("rename_sim", "the simulator leaves no read of the old name horizon_steps",
             _absent(["sim.py"], r"horizon_steps"), "sim.py"),
        Item("rename_obs", "the observation output leaves no read of the old name",
             _absent(["obs.py"], r"horizon_steps"), "obs.py"),
    ),
    relations=(),
    planted=("rename_sim",),
    done_claims={
        "rename_config": "Renamed the setting to max_steps in the config file.",
        "rename_obs": "Updated the observation output to read max_steps.",
    },
    drop_claim="Verified the simulator reads max_steps with no old name left anywhere.",
)


# --- addition_omission, incomplete fan-out of a new field ------------------

ADDITION = Defect(
    key="addition_omission", axis="omission_code", condition="silent",
    files_correct={
        "config.yaml": "run:\n  max_steps: 100\n  max_daily_orders: 20\n",
        "sim.py": 'cap = cfg["max_daily_orders"]\n',
        "obs.py": 'out["max_daily_orders"] = cfg["max_daily_orders"]\n',
        "README.md": "max_daily_orders limits the orders placed per day.\n",
    },
    mutations={"obs.py": 'out["status"] = cfg["max_steps"]\n'},
    items=(
        Item("add_config", "config.yaml declares the new field max_daily_orders",
             _contains("config.yaml", r"max_daily_orders"), "config.yaml"),
        Item("add_sim", "the simulator reads the new field max_daily_orders",
             _contains("sim.py", r"max_daily_orders"), "sim.py"),
        Item("add_obs", "the observation output exposes the new field max_daily_orders",
             _contains("obs.py", r"max_daily_orders"), "obs.py"),
        Item("add_readme", "the README documents the new field max_daily_orders",
             _contains("README.md", r"max_daily_orders"), "README.md"),
    ),
    relations=(),
    planted=("add_obs",),
    done_claims={
        "add_config": "Declared max_daily_orders in the config file.",
        "add_sim": "Wired max_daily_orders into the simulator.",
        "add_readme": "Documented max_daily_orders in the README.",
    },
    drop_claim="Exposed max_daily_orders in the observation output as well.",
)


# --- stale_reference, an old reference left in a doc -----------------------

STALE = Defect(
    key="stale_reference", axis="omission_doc", condition="silent",
    files_correct={
        "cli.py": "def run_batch():\n    return 0\n",
        "README.md": "Use run_batch to start a run.\n",
        "docs.md": "The run_batch command starts a run.\n",
    },
    mutations={"README.md": "Use run_bench to start a run.\n"},
    items=(
        Item("stale_cli", "the CLI defines the new command name run_batch",
             _contains("cli.py", r"def run_batch"), "cli.py"),
        Item("stale_readme", "the README leaves no reference to the old command run_bench",
             _absent(["README.md"], r"run_bench"), "README.md"),
        Item("stale_docs", "the docs leave no reference to the old command run_bench",
             _absent(["docs.md"], r"run_bench"), "docs.md"),
    ),
    relations=(),
    planted=("stale_readme",),
    done_claims={
        "stale_cli": "Renamed the command definition to run_batch in the CLI.",
        "stale_docs": "Updated the docs to the run_batch command name.",
    },
    drop_claim="Updated the README to the run_batch command name too.",
)


# --- contradiction, two present sites that disagree -----------------------

CONTRADICTION = Defect(
    key="contradiction", axis="consistency", condition="silent",
    files_correct={
        "sim.py": "max_steps = 100\n",
        "board.py": "max_steps = 100\n",
    },
    mutations={"board.py": "max_steps = 50\n"},
    items=(
        Item("contra_sim", "the simulator states a max_steps default",
             _contains("sim.py", r"max_steps\s*=\s*\d+"), "sim.py"),
        Item("contra_board", "the leaderboard states a max_steps default",
             _contains("board.py", r"max_steps\s*=\s*\d+"), "board.py"),
    ),
    relations=(
        Relation("contra_agree",
                 "the simulator and leaderboard agree on the max_steps default",
                 (("sim.py", r"max_steps\s*=\s*(\d+)"),
                  ("board.py", r"max_steps\s*=\s*(\d+)"))),
    ),
    planted=("contra_agree",),
    done_claims={
        "contra_sim": "Set the simulator max_steps default.",
        "contra_board": "Set the leaderboard max_steps default.",
    },
    drop_claim="Confirmed the simulator and leaderboard use the same max_steps default.",
)


# --- confab_loud, an omission the summary asserts is complete --------------

CONFAB = Defect(
    key="confab_loud", axis="omission_loud", condition="loud",
    files_correct={
        "config.yaml": "run:\n  max_steps: 100\n",
        "sim.py": 'steps = cfg["max_steps"]\n',
        "obs.py": 'out["max_steps"] = cfg["max_steps"]\n',
    },
    mutations={"sim.py": 'steps = cfg["horizon_steps"]\n'},
    items=(
        Item("confab_config", "config.yaml reads the new name max_steps",
             _contains("config.yaml", r"max_steps\s*:"), "config.yaml"),
        Item("confab_sim", "the simulator leaves no read of the old name horizon_steps",
             _absent(["sim.py"], r"horizon_steps"), "sim.py"),
        Item("confab_obs", "the observation output leaves no read of the old name",
             _absent(["obs.py"], r"horizon_steps"), "obs.py"),
    ),
    relations=(),
    planted=("confab_sim",),
    done_claims={
        "confab_config": "Renamed the setting to max_steps in the config file.",
        "confab_obs": "Updated the observation output to read max_steps.",
    },
    drop_claim=("Verified every call site including the simulator and confirmed no read "
                "of the old horizon_steps name remains anywhere in the code."),
)


DEFECTS = (RENAME, ADDITION, STALE, CONTRADICTION, CONFAB)
BY_KEY = {d.key: d for d in DEFECTS}


def all_files(defect: Defect, planted: bool) -> dict:
    files = dict(defect.files_correct)
    if planted:
        files.update(defect.mutations)
    files.update(haystack_files())
    return files


def build_tree(defect: Defect, root: Path, planted: bool) -> Path:
    """Write the clean or planted fixture tree, haystack included."""
    for rel, content in all_files(defect, planted).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root


def changed_set(defect: Defect, planted: bool = True) -> set:
    """Every file counts as touched, the hard case for diff_control."""
    return set(all_files(defect, planted))


def compose_summary(defect: Defect, loud: bool) -> str:
    """Build the closing summary from the haystack claims and the true claims for
    the items that landed. A silent summary never names the planted item. A loud
    summary appends the drop claim, the false assertion the confab type carries."""
    parts = list(haystack_claims())
    for it in defect.items:
        if it.id in defect.planted:
            continue
        if it.id in defect.done_claims:
            parts.append(defect.done_claims[it.id])
    if loud and defect.drop_claim:
        parts.append(defect.drop_claim)
    return " ".join(parts)


def consistency_conflicts(worktree: Path, relations) -> list:
    out = []
    for r in relations:
        vals, seen = [], []
        for rel, rx in r.sites:
            m = re.search(rx, _read(worktree, rel) or "")
            v = m.group(1) if m else None
            vals.append(v)
            if v is not None:
                seen.append(v)
        if len(set(seen)) > 1:
            out.append((r.id, f"{r.text}, sites disagree {vals}"))
    return out


def item_passes(defect: Defect, worktree: Path, planted: bool = True):
    changed = changed_set(defect, planted)
    return {it.id: verify(it, worktree, changed)[0] for it in defect.items}
