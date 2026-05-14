# AI Speaker RC Candidate Baseline

This document freezes the current repository baseline for the release-candidate
handoff cycle.

## Baseline Snapshot

- Date: `2026-04-08`
- Backend test collection baseline: `487 collected`
- Backend test execution baseline: `486 passed, 1 skipped`
- Primary backend entrypoint: `backend.api_public:app`
- Deployment shape: single host, single process, single instance

This file records the current RC baseline. The verifier checks that the
baseline section and pytest commands are documented; it does not require these
exact counts to stay frozen forever.

## Acceptance Interfaces

The following endpoints are part of the formal acceptance contract for this RC:

- `GET /healthz`: liveness only
- `GET /readyz`: readiness and degraded remote-sync status
- `GET /ops/status`: runtime diagnostics for operations

## Deployment Constraints

- Keep `uvicorn` in single-process mode.
- Do not add `--workers` while pending actions, session state, and runtime
  caches remain process-local.
- Keep `/debug/*` and `/data/calendar_holidays` behind the current auth model.
- Keep `backend.api_public:app` as the only supported service entrypoint for
  this RC.

## Known Non-Blocking Items

- One backend test is currently skipped by design and is not treated as a
  release blocker.
- FastAPI `@app.on_event(...)` emits deprecation warnings. This is tracked as a
  follow-up hardening task and does not block the RC handoff.
