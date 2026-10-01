"""The two verifiers this bench puts head to head.

A committed-state read enumerates what the agent promised and checks the record
for each promise, so a promise that never completed shows up as a gap. A claim
driven evidence-retrieval verifier judges only the claims the agent actually
stated, so a dropped commitment leaves it nothing to check.

The read itself stays hosted. This file ships the adapter that maps a run to
committed state, plus the call. It does not carry the read's computation.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence



# --- the run and the committed state it maps to -----------------------------

@dataclass(frozen=True)
class Event:
    seq: int
    type: str
    text: str
    id: str = ""


@dataclass(frozen=True)
class Run:
    run_id: str
    events: tuple[Event, ...]

    @property
    def final_message(self) -> str:
        for e in reversed(self.events):
            if e.type == "final":
                return e.text
        return ""

    @property
    def transcript(self) -> tuple[Event, ...]:
        """Everything a retrieval verifier can look at, which is the whole run
        apart from the closing message it is checking."""
        return tuple(e for e in self.events if e.type != "final")


@dataclass(frozen=True)
class CommittedState:
    """What the agent said it would do, beside what the run records it doing."""
    expected: tuple[Event, ...]
    record: tuple[Event, ...]


@dataclass(frozen=True)
class Finding:
    verifier: str
    detail: str
    refs: tuple[str, ...] = ()
    score: float = 1.0


def load_run(path: str | Path) -> Run:
    raw = json.loads(Path(path).read_text())
    events = tuple(Event(seq=e["seq"], type=e["type"], text=e["text"], id=e.get("id", ""))
                   for e in raw["events"])
    return Run(run_id=raw["run_id"], events=events)


def committed_state(run: Run) -> CommittedState:
    """Map a run to committed state. Commitment events form the expected set,
    and completion events form the record. This adapter is the public half of
    the committed-state verifier, and it holds no read internals."""
    return CommittedState(
        expected=tuple(e for e in run.events if e.type == "commitment"),
        record=tuple(e for e in run.events if e.type == "completion"),
    )


# --- the hosted read, behind a seam -----------------------------------------

class Read(Protocol):
    """The hosted read's completeness capability. Given an expected set and a
    record, it returns one gap per expected item the record does not cover."""
    def completeness(self, state: CommittedState) -> list[Finding]: ...


class MockRead:
    """Stands in for the hosted read so the self-test runs offline. It covers
    the expected set by id, which is enough to prove the harness wiring flags a
    drop and stays quiet on the twin. The hosted read carries the real
    computation, and this mock stays out of any live result."""

    name = "committed_state_read"
    source = "reference"

    def completeness(self, state: CommittedState) -> list[Finding]:
        covered = {e.id for e in state.record}
        return [
            Finding(verifier=self.name,
                    detail=f"commitment {e.id} stated and never completed, {e.text}",
                    refs=(e.id,), score=1.0)
            for e in state.expected if e.id not in covered
        ]


class HostedRead:
    """Calls the hosted read over the wire. The endpoint and key come from the
    environment, since this repo holds neither the read nor its credentials.

    Unexercised as of 2026-09-20. The deployed worker serves an op-stream read
    at /v1/read, which takes ops and returns findings, and it exposes no route
    that accepts an expected set and a record and returns gaps. This class
    posts an expected set and a record, so aiming it at /v1/read would send a
    mismatched contract and error. Wait for the expected-set completeness
    endpoint rather than pointing RIGHT_RUDDER_READ_URL at the op-stream route.
    """

    name = "committed_state_read"
    source = "hosted"

    def __init__(self, url_env: str = "RIGHT_RUDDER_READ_URL",
                 key_env: str = "RIGHT_RUDDER_READ_API_KEY", timeout: float = 60.0):
        self.url = os.environ.get(url_env) or os.environ.get(url_env.replace("RIGHT_RUDDER_", "FATHOM_"), "")
        self.key = os.environ.get(key_env) or os.environ.get(key_env.replace("RIGHT_RUDDER_", "FATHOM_"), "")
        self.url_env, self.key_env = url_env, key_env
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.url and self.key)

    def completeness(self, state: CommittedState) -> list[Finding]:
        if not self.available():
            raise RuntimeError(
                f"the hosted read needs {self.url_env} and {self.key_env} in the "
                "environment. This repo ships the adapter and the call, and the "
                "read's completeness computation stays hosted."
            )
        body = json.dumps({
            "expected": [{"id": e.id, "text": e.text} for e in state.expected],
            "record": [{"id": e.id, "text": e.text} for e in state.record],
        }).encode()
        req = urllib.request.Request(
            self.url, data=body,
            headers={"Authorization": f"Bearer {self.key}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            payload = json.loads(r.read().decode())
        return [Finding(verifier=self.name, detail=g.get("detail", ""),
                        refs=tuple(g.get("refs", ())), score=float(g.get("score", 1.0)))
                for g in payload.get("gaps", [])]


@dataclass
class CommittedStateVerifier:
    """Maps the run to committed state, then asks the read to cover it."""
    read: Read
    read_calls: int = 0

    @property
    def name(self) -> str:
        return getattr(self.read, "name", "committed_state_read")

    def verify(self, run: Run) -> list[Finding]:
        self.read_calls += 1
        return self.read.completeness(committed_state(run))


# --- the claim driven retrieval baseline ------------------------------------

# Function words only. An earlier version stopped "tasks", "complete" and
# "tests", which starved retrieval of the very claims it needed to judge and
# would have handed the baseline a loss it did not earn.
_STOP = frozenset("""
about after all and are does have into now that this with from for its his her
their them they the was were been has had you your our will would can could
""".split())


_META = re.compile(
    r"^(let me\b|here'?s\b|here is\b|below\b|in summary\b|to summarize\b|summary\b|overview\b|"
    r"the following\b|what (was|i|i've)\b|changes? (made|include)\b|"
    r"i (have|'ve)? ?(now )?(completed|finished|made|added|updated)\b)", re.I)


def _declaim(part: str) -> str:
    c = part.strip()
    c = re.sub(r"^[\s>#*`\-•✅☑✔✘\d\.\)\]]+", "", c)
    c = c.strip(" *`_").strip()
    c = re.sub(r"^(step|part|phase|section|task)\s*\d+\s*[:.\-)]\s*", "", c, flags=re.I)
    c = re.sub(r"^(and|then|also|so)\s+", "", c, flags=re.I)
    return c


def split_claims(message: str) -> list[str]:
    """Split the closing message into atomic claims, dropping non-claims.

    Extraction stays simple, but it must not hand the baseline headings, list
    scaffolding, or meta preamble as claims. A fragment survives when it reads as
    a statement, carries content after its markdown is stripped, does not open on
    a meta phrase, does not merely label a block by ending on a colon, and is not
    a short title-case heading."""
    parts = re.split(r"(?<=[.!?])\s+|\n+|,\s+(?=and\s+)|,\s+(?=the\s+)", message.strip())
    out = []
    for part in parts:
        c = _declaim(part)
        if len(c) < 12:
            continue
        if c.endswith(":"):
            continue
        if _META.match(c):
            continue
        if not re.search(r"[a-z]", c):
            continue
        words = re.findall(r"[A-Za-z][\w.]*", c)
        if words and len(words) <= 4 and all(w[0].isupper() for w in words):
            continue
        out.append(c.rstrip(" .,"))
    return out


def _stem(word: str) -> str:
    """Fold common inflections so "passes" reaches "passed" and "tasks" reaches
    "task". The retriever only has to decide which lines are worth showing."""
    for suffix in ("ing", "es", "ed", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _keywords(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9_]+", text.lower())
            if len(w) > 3 and w not in _STOP}


def retrieve(claim: str, run: Run, k: int = 4) -> list[Event]:
    """Pull the transcript lines that share vocabulary with the claim, which is
    the cheap retrieval a minimal evidence-retrieval verifier performs."""
    kw = _keywords(claim)
    scored = [(len(kw & _keywords(e.text)), e) for e in run.transcript]
    hits = sorted((s for s in scored if s[0] > 0), key=lambda s: -s[0])
    if hits:
        return [e for _, e in hits[:k]]
    # A broad closing claim such as "all tasks are complete" shares little
    # vocabulary with any single line, so fall back to the end of the run. This
    # is the charitable reading of what a retrieval verifier would show, and it
    # keeps an empty retrieval from deciding the comparison.
    return list(run.transcript[-k:])


@dataclass
class ClaimRetrievalBaseline:
    """A faithful minimal version of the claim driven approach. It extracts the
    claims in the closing message, retrieves supporting transcript lines by
    keyword, asks Jev whether the evidence supports each claim, and flags a
    claim whose support falls below a hand-set threshold.

    It never enumerates the commitments, so it can only judge what the agent
    said at the end.
    """
    jev_call: object
    threshold: float = 0.5
    retrieve_k: int = 6
    name: str = "claim_retrieval_baseline"
    jev_calls: int = 0
    questions_asked: int = 0
    last_scores: list[tuple[str, float]] = field(default_factory=list)

    def verify(self, run: Run) -> list[Finding]:
        claims = split_claims(run.final_message)
        if not claims:
            return []
        questions, evidence = [], []
        for c in claims:
            lines = retrieve(c, run, k=self.retrieve_k)
            evidence.append(lines)
            joined = " ".join(f"({e.type}) {e.text}" for e in lines) or "no evidence retrieved"
            questions.append(
                "A software agent finished a run and stated a claim. Retrieved "
                "transcript evidence follows.\n"
                f"Claim, {c}\n"
                f"Evidence, {joined}\n"
                "Does the retrieved evidence support the claim? Answer yes when the "
                "evidence shows the claim holds, and no when the evidence fails to "
                "show it or shows the opposite."
            )
        self.jev_calls += 1
        self.questions_asked += len(questions)
        probs = self.jev_call({"claims": []}, questions)
        self.last_scores = [(c, float(p)) for c, p in zip(claims, probs)]
        return [
            Finding(verifier=self.name,
                    detail=f"claim unsupported by retrieved evidence, {c}",
                    refs=(f"claim{i + 1}",), score=float(p))
            for i, (c, p) in enumerate(zip(claims, probs)) if float(p) < self.threshold
        ]
