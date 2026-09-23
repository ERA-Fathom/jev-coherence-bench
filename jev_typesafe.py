"""Bring-your-own TypeSafe Jev client for the claim-verifier arm.

The harness reaches Jev through one function, jev_call(state, questions), which
returns a probability of yes per question in the order given. This client posts
directly to TypeSafe's System One endpoint with the caller's own key, so the repo
depends on nothing private and no gateway sits in the path.

Set TYPESAFE_API_KEY in the environment. TYPESAFE_BASE, TYPESAFE_ENDPOINT, and
JEV_MODEL override the target when TypeSafe changes it, or point the client at a
gateway instead. A missing key raises, so the caller skips the Jev arm rather
than scoring a silent zero.

Contract, per docs.typesafe.ai. POST {base}{endpoint} with an Authorization
bearer header and a body of {"model", "state", "questions"}, where each question
is {"type": "noul", "instructions": "..."}. A boolean answer returns its
probability of true in the noul field.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Sequence

BASE = os.environ.get("TYPESAFE_BASE", "https://api.typesafe.ai")
ENDPOINT = os.environ.get("TYPESAFE_ENDPOINT", "/v1/systemone")
MODEL = os.environ.get("JEV_MODEL", "jev-latest")
BATCH = int(os.environ.get("JEV_BATCH", "20"))
TIMEOUT = float(os.environ.get("JEV_TIMEOUT", "60"))


class JevError(RuntimeError):
    pass


def _require_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise JevError("TYPESAFE_API_KEY is not set. Put your own TypeSafe key in "
                       "the environment to run the Jev arm.")
    return key


def _prob_of(ans: dict) -> float:
    """A boolean answer carries its probability of true under noul on the native
    API, or under probability on a gateway that normalizes to that name."""
    for k in ("noul", "probability", "value"):
        v = ans.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0


def _answers_of(payload: dict) -> dict:
    """Answers ride under an answers key, or at the top level keyed by name."""
    if isinstance(payload.get("answers"), dict):
        return payload["answers"]
    return {k: v for k, v in payload.items() if isinstance(v, dict) and "type" in v}


def _post(state, batch: Sequence[str]) -> list[float]:
    key = _require_key()
    spec = {f"q{i}": {"type": "noul", "instructions": q} for i, q in enumerate(batch)}
    body = json.dumps({"model": MODEL, "state": state, "questions": spec}).encode()
    req = urllib.request.Request(
        BASE.rstrip("/") + ENDPOINT, data=body,
        headers={"authorization": f"Bearer {key}", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            payload = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise JevError(f"TypeSafe HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from e
    except urllib.error.URLError as e:
        raise JevError(f"TypeSafe unreachable: {e}") from e
    ans = _answers_of(payload)
    return [_prob_of(ans.get(f"q{i}", {})) for i in range(len(batch))]


def _resilient(state, batch: Sequence[str], depth: int = 0) -> list[float]:
    """One failed batch must not cost the run. A timeout is usually the batch
    being too big, so halve and retry. An unreachable endpoint is a broken run,
    so raise rather than turn it into a page of confident zeros."""
    try:
        return _post(state, batch)
    except JevError as e:
        if "unreachable" in str(e).lower():
            raise
        if len(batch) == 1 or depth >= 5:
            print(f"  jev, gave up on {len(batch)} question(s), scoring 0.0, {e}")
            return [0.0] * len(batch)
        mid = len(batch) // 2
        print(f"  jev, batch of {len(batch)} failed, splitting and retrying")
        return (_resilient(state, batch[:mid], depth + 1)
                + _resilient(state, batch[mid:], depth + 1))


def jev_call(state, questions: Sequence[str]) -> list[float]:
    out: list[float] = []
    batches = [questions[i:i + BATCH] for i in range(0, len(questions), BATCH)]
    if len(batches) > 1:
        print(f"  jev, {len(questions)} questions in {len(batches)} batches of {BATCH}")
    for batch in batches:
        out.extend(_resilient(state, batch))
    return out
