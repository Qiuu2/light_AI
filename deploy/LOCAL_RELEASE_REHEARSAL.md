# AI Speaker Local Release Rehearsal

Use this checklist before handing the RC to a real acceptance or deployment
environment.

## 1. Freeze the Candidate

Run the repo-level verification and record the exact result:

```bash
python -m pytest --collect-only -q -p no:cacheprovider backend/tests
python -m pytest -q -p no:cacheprovider backend/tests
```

Expected baseline for this RC:

- `487 collected`
- `486 passed`
- `1 skipped`

## 2. Verify Deployment Assets

Check the service files and delivery docs:

```bash
python scripts/verify_rc_candidate.py
```

The verification must confirm:

- `backend.api_public:app` is the service entrypoint
- both `systemd` units stay single-process and do not add `--workers`
- the environment example contains the required remote settings
- the RC baseline and rehearsal documents are present

For a stricter pre-handoff doc pass, use:

```bash
python scripts/verify_rc_candidate.py --strict-docs
```

## 3. Exercise the Runtime Locally

Start the backend with the production entrypoint:

```bash
python -m uvicorn backend.api_public:app --host 127.0.0.1 --port 5018
```

In another shell, probe the runtime endpoints:

```bash
python scripts/verify_rc_candidate.py --base-url http://127.0.0.1:5018
```

If the runtime is intentionally down and you only want to validate docs and
assets, use:

```bash
python scripts/verify_rc_candidate.py --skip-http-probe --base-url http://127.0.0.1:5018
```

At minimum, confirm:

- `/healthz` returns `200`
- `/ops/status` returns `200`
- `/readyz` returns `200` for a cutover-ready instance

If `/readyz` returns `503`, the service is alive but not ready for handoff.

## 4. Fault and Recovery Drill

Run these checks manually on the rehearsal machine:

```bash
sudo systemctl restart ai-speaker
sudo systemctl stop ai-speaker
sudo systemctl start ai-speaker
sudo systemctl status ai-speaker
sudo journalctl -u ai-speaker -n 200
```

Confirm the following behaviors:

- the service returns to `active (running)` after restart
- remote sync failures do not kill the main API process
- `/readyz` exposes degraded or not-ready state instead of a false healthy
  signal
- runtime JSON data is still readable after restart
- `.history` recovery remains available if runtime data is damaged

## 5. Acceptance Handoff Package

Before formal handoff, make sure the delivery package includes:

- offline bundle or deployment directory
- `systemd` unit and environment example
- RC baseline record
- acceptance and recovery checklist
- startup, stop, restart, and log commands
- health interface verification commands
