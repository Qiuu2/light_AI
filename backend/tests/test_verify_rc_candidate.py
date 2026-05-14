from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "verify_rc_candidate.py"


def _load_verify_module():
    spec = importlib.util.spec_from_file_location("verify_rc_candidate", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bundle_manifest() -> dict:
    return {
        "bundle": "ai-speaker-kylin-v10-x86_64",
        "entrypoint": "backend.api_public:app",
        "verification": {
            "required_bundle_paths": [
                "kylininstall.sh",
                "kylininstall-ai-speaker.sh",
                "systemd/ai-speaker.service",
                "systemd/ai-speaker.env.example",
                "docs/README.md",
                "docs/ACCEPTANCE_CHECKLIST.md",
                "docs/RC_CANDIDATE_BASELINE.md",
                "docs/LOCAL_RELEASE_REHEARSAL.md",
                "docs/verify_rc_candidate.py",
            ],
            "required_model_paths": [
                "models/config.json",
                "models/pytorch_model.bin",
                "models/tokenizer.json",
                "models/tokenizer_config.json",
                "models/vocab.txt",
                "models/joint_rbt3/joint_model.pt",
            ],
            "forbidden_runtime_data_paths": [
                "runtime-data/assistant_command_logs.json",
                "runtime-data/remote_sync_meta.json",
            ],
        },
        "files": [
            {"path": "kylininstall.sh", "size": 1, "sha256": "a"},
            {"path": "kylininstall-ai-speaker.sh", "size": 1, "sha256": "b"},
            {"path": "systemd/ai-speaker.service", "size": 1, "sha256": "c"},
            {"path": "systemd/ai-speaker.env.example", "size": 1, "sha256": "d"},
            {"path": "docs/README.md", "size": 1, "sha256": "e"},
            {"path": "docs/ACCEPTANCE_CHECKLIST.md", "size": 1, "sha256": "f"},
            {"path": "docs/RC_CANDIDATE_BASELINE.md", "size": 1, "sha256": "g"},
            {"path": "docs/LOCAL_RELEASE_REHEARSAL.md", "size": 1, "sha256": "h"},
            {"path": "docs/verify_rc_candidate.py", "size": 1, "sha256": "i"},
            {"path": "models/config.json", "size": 1, "sha256": "j"},
            {"path": "models/pytorch_model.bin", "size": 1, "sha256": "k"},
            {"path": "models/tokenizer.json", "size": 1, "sha256": "l"},
            {"path": "models/tokenizer_config.json", "size": 1, "sha256": "m"},
            {"path": "models/vocab.txt", "size": 1, "sha256": "n"},
            {"path": "models/joint_rbt3/joint_model.pt", "size": 1, "sha256": "o"},
            {"path": "wheelhouse/psutil.whl", "size": 1, "sha256": "p"},
            {"path": "runtime-data/broadcast_schedules.json", "size": 1, "sha256": "q"},
        ],
    }


def _bundle_files(bundle_dir: Path) -> dict[str, str]:
    manifest = _bundle_manifest()
    return {
        (bundle_dir / "docs" / "README.md").as_posix(): """
# Offline README

## Runtime Hardening Addendum

- `/readyz`
- `/ops/status`
""".strip(),
        (bundle_dir / "docs" / "RC_CANDIDATE_BASELINE.md").as_posix(): """
# RC Baseline

## Baseline Snapshot

- Backend test collection baseline: `999 collected`
- Backend test execution baseline: `998 passed, 1 skipped`
- Primary backend entrypoint: `backend.api_public:app`

## Acceptance Interfaces

- `GET /healthz`
- `GET /readyz`
- `GET /ops/status`

## Deployment Constraints

- single process
""".strip(),
        (bundle_dir / "docs" / "LOCAL_RELEASE_REHEARSAL.md").as_posix(): """
# Local Release Rehearsal

## 1. Freeze the Candidate

python -m pytest --collect-only -q -p no:cacheprovider backend/tests
python -m pytest -q -p no:cacheprovider backend/tests

## 2. Verify Deployment Assets

python scripts/verify_rc_candidate.py
backend.api_public:app

## 3. Exercise the Runtime Locally

curl /healthz
curl /readyz
curl /ops/status
systemctl restart ai-speaker
journalctl -u ai-speaker -n 100
""".strip(),
        (bundle_dir / "docs" / "ACCEPTANCE_CHECKLIST.md").as_posix(): """
# Acceptance Checklist

## Install and Service Checks

bash kylininstall-ai-speaker.sh

## Runtime Endpoint Checks

bundle structure verified
runtime endpoints verified
/healthz
/readyz
/ops/status
kylininstall-ai-speaker.sh

## Recovery Checks

systemctl restart ai-speaker
journalctl -u ai-speaker -n 100
python docs/verify_rc_candidate.py --bundle-dir . --base-url http://127.0.0.1:5018
""".strip(),
        (bundle_dir / "docs" / "verify_rc_candidate.py").as_posix(): "print('ok')\n",
        (bundle_dir / "systemd" / "ai-speaker.service").as_posix(): """
[Service]
EnvironmentFile=-/etc/ai-speaker/ai-speaker.env
ExecStart=python -m uvicorn backend.api_public:app --host 0.0.0.0 --port 5018
LimitNOFILE=65535
UMask=0027
""".strip(),
        (bundle_dir / "systemd" / "ai-speaker.env.example").as_posix(): """
REMOTE_BASE_URL=
REMOTE_USERNAME=admin
REMOTE_PASSWORD=123456
REMOTE_TIMEOUT=15
REMOTE_AUTO_SYNC_SECONDS=180
DEBUG_REMOTE=0
CORS_ALLOW_ORIGINS=
""".strip(),
        (bundle_dir / "manifest.json").as_posix(): json.dumps(manifest, ensure_ascii=False, indent=2),
        (bundle_dir / "checksums.txt").as_posix(): "\n".join(
            [
                "a  kylininstall.sh",
                "b  kylininstall-ai-speaker.sh",
                "c  systemd/ai-speaker.service",
                "d  systemd/ai-speaker.env.example",
                "e  docs/README.md",
                "f  docs/ACCEPTANCE_CHECKLIST.md",
                "g  docs/RC_CANDIDATE_BASELINE.md",
                "h  docs/LOCAL_RELEASE_REHEARSAL.md",
                "i  docs/verify_rc_candidate.py",
                "j  models/config.json",
                "k  models/pytorch_model.bin",
                "l  models/tokenizer.json",
                "m  models/tokenizer_config.json",
                "n  models/vocab.txt",
                "o  models/joint_rbt3/joint_model.pt",
            ]
        )
        + "\n",
        (bundle_dir / "kylininstall.sh").as_posix(): "#!/bin/bash\n",
        (bundle_dir / "kylininstall-ai-speaker.sh").as_posix(): """
#!/bin/bash
ENV_EXAMPLE_FILE="${MEDIA_ROOT}/systemd/ai-speaker.env.example"
ENV_DIR="/etc/ai-speaker"
ENV_TARGET="${ENV_DIR}/ai-speaker.env"
install_runtime_env_file() {
  ${SUDO} mkdir -p "${ENV_DIR}"
  if [[ -f "${ENV_TARGET}" ]]; then
    echo "Keeping existing runtime env file"
    return
  fi
  ${SUDO} cp "${ENV_EXAMPLE_FILE}" "${ENV_TARGET}"
  echo "Created runtime env file from installer template"
}
main() {
    install_runtime_env_file
    install_systemd_unit
}
""".strip(),
        (bundle_dir / "wheelhouse" / "psutil.whl").as_posix(): "wheel\n",
        (bundle_dir / "runtime-data" / "broadcast_schedules.json").as_posix(): "{}\n",
        (bundle_dir / "models" / "config.json").as_posix(): "{}\n",
        (bundle_dir / "models" / "pytorch_model.bin").as_posix(): "bin\n",
        (bundle_dir / "models" / "tokenizer.json").as_posix(): "{}\n",
        (bundle_dir / "models" / "tokenizer_config.json").as_posix(): "{}\n",
        (bundle_dir / "models" / "vocab.txt").as_posix(): "vocab\n",
        (bundle_dir / "models" / "joint_rbt3" / "joint_model.pt").as_posix(): "pt\n",
    }


def _install_virtual_paths(monkeypatch, module, *, files: dict[str, str], dirs: set[str]) -> None:
    def normalize(path: Path) -> str:
        return path.as_posix()

    monkeypatch.setattr(module, "_read_text", lambda path: files[normalize(path)])
    monkeypatch.setattr(module.Path, "is_file", lambda self: normalize(self) in files)
    monkeypatch.setattr(module.Path, "is_dir", lambda self: normalize(self) in dirs)
    monkeypatch.setattr(module.Path, "exists", lambda self: normalize(self) in files or normalize(self) in dirs)
    monkeypatch.setattr(
        module.Path,
        "iterdir",
        lambda self: iter(
            Path(name) for name in sorted(files) if Path(name).parent.as_posix() == normalize(self)
        ),
    )


def test_service_errors_rejects_workers_and_wrong_entrypoint(monkeypatch) -> None:
    module = _load_verify_module()
    service_file = Path("/virtual/ai-speaker.service")
    monkeypatch.setattr(module.Path, "is_file", lambda self: self == service_file)
    monkeypatch.setattr(
        module,
        "_read_text",
        lambda path: "\n".join(
            [
                "[Service]",
                "EnvironmentFile=-/etc/ai-speaker/ai-speaker.env",
                "ExecStart=python -m uvicorn backend.app:app --workers 2",
            ]
        ),
    )

    errors = module._service_errors(service_file)

    assert any("missing backend.api_public:app" in error for error in errors)
    assert any("must stay single-process" in error for error in errors)
    assert any("LimitNOFILE=65535" in error for error in errors)
    assert any("UMask=0027" in error for error in errors)


def test_env_example_errors_requires_core_remote_keys(monkeypatch) -> None:
    module = _load_verify_module()
    env_file = Path("/virtual/ai-speaker.env.example")
    monkeypatch.setattr(module.Path, "is_file", lambda self: self == env_file)
    monkeypatch.setattr(
        module,
        "_read_text",
        lambda path: "\n".join(
            [
                "REMOTE_BASE_URL=",
                "REMOTE_TIMEOUT=15",
            ]
        ),
    )

    errors = module._env_example_errors(env_file)

    assert errors
    joined = "\n".join(errors)
    assert "REMOTE_USERNAME" in joined
    assert "REMOTE_PASSWORD" in joined
    assert "REMOTE_AUTO_SYNC_SECONDS" in joined
    assert "CORS_ALLOW_ORIGINS" in joined


def test_baseline_doc_errors_accepts_changed_counts(monkeypatch) -> None:
    module = _load_verify_module()
    doc = Path("/virtual/RC_CANDIDATE_BASELINE.md")
    monkeypatch.setattr(module.Path, "is_file", lambda self: self == doc)
    monkeypatch.setattr(
        module,
        "_read_text",
        lambda path: """
# RC

## Baseline Snapshot

- Backend test collection baseline: `999 collected`
- Backend test execution baseline: `998 passed, 1 skipped`
- Primary backend entrypoint: `backend.api_public:app`

## Acceptance Interfaces

- `/healthz`

## Deployment Constraints

- single process
""".strip(),
    )

    assert module._baseline_doc_errors(doc, strict=True) == []


def test_http_errors_allows_readyz_503_when_requested(monkeypatch) -> None:
    module = _load_verify_module()

    def fake_probe_json(base_url: str, path: str, timeout: float) -> tuple[int, object]:
        payloads = {
            "/healthz": (200, {"status": "ok"}),
            "/ops/status": (
                200,
                {
                    "status": "ok",
                    "service": "ai-speaker-api",
                    "uptime_seconds": 12,
                    "remote_sync": {},
                    "current_remote_base_url": "",
                },
            ),
            "/readyz": (503, {"status": "not_ready", "remote_status": "disabled", "degraded": False}),
        }
        return payloads[path]

    monkeypatch.setattr(module, "_probe_json", fake_probe_json)

    assert module._http_errors("http://127.0.0.1:5018", 5.0, allow_readyz_503=True) == []
    strict_errors = module._http_errors("http://127.0.0.1:5018", 5.0, allow_readyz_503=False)
    assert len(strict_errors) == 1
    assert "/readyz" in strict_errors[0]


def test_http_errors_reports_connection_failure_without_traceback(monkeypatch) -> None:
    module = _load_verify_module()

    def fake_probe_json(base_url: str, path: str, timeout: float) -> tuple[int, object]:
        raise RuntimeError("http://127.0.0.1:5018/healthz: connection failed (refused)")

    monkeypatch.setattr(module, "_probe_json", fake_probe_json)

    errors = module._http_errors("http://127.0.0.1:5018", 5.0, allow_readyz_503=False)

    assert errors
    assert all("traceback" not in error.lower() for error in errors)
    assert "connection failed" in errors[0]


def test_bundle_asset_errors_accepts_minimal_valid_bundle(monkeypatch) -> None:
    module = _load_verify_module()
    bundle_dir = Path("C:/virtual/bundle")
    files = _bundle_files(bundle_dir)
    dirs = {
        bundle_dir.as_posix(),
        (bundle_dir / "docs").as_posix(),
        (bundle_dir / "systemd").as_posix(),
        (bundle_dir / "wheelhouse").as_posix(),
        (bundle_dir / "runtime-data").as_posix(),
        (bundle_dir / "models").as_posix(),
        (bundle_dir / "models" / "joint_rbt3").as_posix(),
    }
    _install_virtual_paths(monkeypatch, module, files=files, dirs=dirs)

    assert module._bundle_asset_errors(bundle_dir, strict_docs=True) == []


def test_bundle_asset_errors_rejects_missing_manifest_and_runtime_state(monkeypatch) -> None:
    module = _load_verify_module()
    bundle_dir = Path("C:/virtual/bundle")
    files = _bundle_files(bundle_dir)
    files.pop((bundle_dir / "manifest.json").as_posix())
    files[(bundle_dir / "runtime-data" / "assistant_command_logs.json").as_posix()] = "{}\n"
    dirs = {
        bundle_dir.as_posix(),
        (bundle_dir / "docs").as_posix(),
        (bundle_dir / "systemd").as_posix(),
        (bundle_dir / "wheelhouse").as_posix(),
        (bundle_dir / "runtime-data").as_posix(),
        (bundle_dir / "models").as_posix(),
        (bundle_dir / "models" / "joint_rbt3").as_posix(),
    }
    _install_virtual_paths(monkeypatch, module, files=files, dirs=dirs)

    errors = module._bundle_asset_errors(bundle_dir, strict_docs=False)

    assert any("missing bundle manifest" in error for error in errors)
    assert any("runtime-state files must not be pre-bundled" in error for error in errors)


def test_bundle_asset_errors_rejects_missing_checksum_for_required_model(monkeypatch) -> None:
    module = _load_verify_module()
    bundle_dir = Path("C:/virtual/bundle")
    files = _bundle_files(bundle_dir)
    files[(bundle_dir / "checksums.txt").as_posix()] = "\n".join(
        [
            "a  kylininstall.sh",
            "b  kylininstall-ai-speaker.sh",
            "c  systemd/ai-speaker.service",
            "d  systemd/ai-speaker.env.example",
            "e  docs/README.md",
            "f  docs/ACCEPTANCE_CHECKLIST.md",
            "g  docs/RC_CANDIDATE_BASELINE.md",
            "h  docs/LOCAL_RELEASE_REHEARSAL.md",
            "i  docs/verify_rc_candidate.py",
            "j  models/config.json",
        ]
    )
    dirs = {
        bundle_dir.as_posix(),
        (bundle_dir / "docs").as_posix(),
        (bundle_dir / "systemd").as_posix(),
        (bundle_dir / "wheelhouse").as_posix(),
        (bundle_dir / "runtime-data").as_posix(),
        (bundle_dir / "models").as_posix(),
        (bundle_dir / "models" / "joint_rbt3").as_posix(),
    }
    _install_virtual_paths(monkeypatch, module, files=files, dirs=dirs)

    errors = module._bundle_asset_errors(bundle_dir, strict_docs=False)

    assert any("missing checksum for models/pytorch_model.bin" in error for error in errors)
