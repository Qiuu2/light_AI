# AI Speaker Project

AI Speaker Project is a campus broadcast assistant that combines NLU, scheduling, remote device control, and a Vue-based admin UI. This README is intentionally short and focused on day-to-day development. For deeper project conventions and intent taxonomy, see `AGENTS.md`.

## Quick Start

### Backend

```bash
pip install -r requirements.txt
python -m uvicorn backend.api_public:app --reload --port 5012
```

Alternative module entry:

```bash
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd web
npm install
npm run dev
```

### Training and Evaluation

```bash
python src/preprocessor.py
python src/trainer.py
python src/evaluate.py
```

## Common Tests

```bash
pytest backend/tests/
python scripts/test_engine_smoke.py
```

Frontend unit tests:

```bash
cd web
npm run test:unit
```

## Directory Guide

| Path | Purpose |
| --- | --- |
| `src/` | Joint RBT3 NLU training, inference, and dialogue management |
| `backend/` | FastAPI service, execution logic, defaults, and tests |
| `web/` | Vue 2 + Element UI frontend |
| `scripts/` | Developer utility scripts and smoke checks |
| `deploy/` | systemd files, offline deployment, and bundle tooling |
| `models/` | Local model directory, ignored by default |
| `data/` | Local training or reference data kept outside normal version control flow in this workspace |
| `backend/default_data/` | Versioned default static data |
| `backend/data/` | Runtime data directory, ignored by default |

## Dev Entry Points and Boundaries

- Daily development happens in `backend/`, `src/`, `web/`, and `scripts/`.
- `kylininstall-ai-speaker.sh` is a Kylin offline installer artifact, not a normal development entry point.
- Files under `deploy/` support packaging and service deployment. They are not the source of truth for application behavior.
- Root-level archives, old notes, and SDK reference files are auxiliary materials. Keep them out of routine debugging unless they are directly relevant.

## Workspace Hygiene

- Source directories: `src/`, `backend/`, `web/src/`
- Versioned defaults: `backend/default_data/`
- Local runtime data: `backend/data/`
- Local cache and temp outputs: `.pytest_cache/`, `.pytest_tmp_*`, `tmp*`, `bundlecheck_*`, `__pycache__/`, `backend/tests/license-tests-*`
- Local dataset area: `data/`
- Local dataset cache: `hf_cache/`, `data/hf_cache/`

Use the cleanup helper below to preview or remove common temporary outputs:

```bash
python scripts/cleanup_workspace.py
python scripts/cleanup_workspace.py --apply
```

## Prerequisites

- Python 3.9+ recommended, ideally 3.10
- Node.js for the frontend toolchain
- Model files prepared under `models/joint_rbt3/`
- Remote API environment variables configured through the example files in `deploy/systemd/` or `deploy/offline/systemd/`

## Further Reading

- Project guide: `AGENTS.md`
- Offline deployment: `deploy/offline/README.md`
- systemd deployment: `deploy/systemd/README.md`
