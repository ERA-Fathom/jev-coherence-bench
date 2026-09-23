# jev-coherence-bench

A benchmark that puts a committed-state coherence read against Jev, the typed
verifier, on agent runs.

## What it measures

An agent commits to a step, the run proceeds, and the committed state can quietly
lose that item before the run ends while the closing summary reads as complete. A
typed verifier such as Jev scores whether the agent's claims are supported, so it
catches an invented completion and misses a commitment the agent never mentions. A
committed-state read checks what the run actually did against what it set out to do,
so it catches the silent drop. This harness measures that difference across several
defect types.

## The arms

- committed_state_read, enumerate the committed items and check each against the
  record the run produced
- claim_retrieval_baseline, split the closing summary into claims, retrieve
  evidence, and ask Jev whether the evidence supports each one
- consistency_check, flag two committed sites whose values disagree
- diff_control, flag an item only when its watched file never changed
- clear_head, the third-party Stop hook, optional and bring-your-own

## Install and run

Python 3.10 or newer, standard library only.

Offline self-test, no key needed.

```
python3 bench_rung6.py --selftest
```

Run the matrix with the Jev arm live, bringing your own TypeSafe key.

```
cp .env.example .env    # add your TYPESAFE_API_KEY
python3 bench_rung6.py --jev live
```

The read, consistency, and diff arms score offline and deterministically. The Jev
arm needs your TypeSafe key. Results land in a SQLite database, one row per defect
type, condition, and arm.

## What this cut covers

This first cut ships the defect-type matrix, a set of planted defects across five
kinds, a rename left half-done, a new field fanned out incompletely, a stale
reference, a value contradiction, and a loud confabulation. Each defect ships a
clean twin that every arm must leave quiet.

## What stays hosted

The committed-state read's real computation and the re-grounding policy live in the
hosted Fathom service, reached through a call. This repo carries the adapters, the
benchmark, the claim baseline, and the client seams, and it does not carry the
read's mechanism. In this matrix the read arm runs as a local deterministic checker
over the planted fixtures, which is exact by construction. On real agent runs the
hosted read performs the same check robustly, reached through the read client in
verifiers.py.

## Bring your own Jev

The Jev arm posts directly to TypeSafe's System One endpoint with your own key. Set
TYPESAFE_API_KEY, and override JEV_MODEL or TYPESAFE_BASE to point at a different
target. Jev is a product of TypeSafe AI, named here only to identify the verifier
under comparison.
