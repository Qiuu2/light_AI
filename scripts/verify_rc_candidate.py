from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, List, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen


REQUIRED_BUNDLE_PATHS = [
    "kylininstall.sh",
    "kylininstall-ai-speaker.sh",
    "systemd/ai-speaker.service",
    "systemd/ai-speaker.env.example",
    "docs/README.md",
    "docs/ACCEPTANCE_CHECKLIST.md",
    "docs/RC_CANDIDATE_BASELINE.md",
    "docs/LOCAL_RELEASE_REHEARSAL.md",
    "docs/verify_rc_candidate.py",
]

REQUIRED_MODEL_PATHS = [
    "models/config.json",
    "models/pytorch_model.bin",
    "models/tokenizer.json",
    "models/tokenizer_config.json",
    "models/vocab.txt",
    "models/joint_rbt3/joint_model.pt",
]

FORBIDDEN_RUNTIME_DATA_PATHS = [
    "runtime-data/assistant_command_logs.json",
    "runtime-data/remote_sync_meta.json",
]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _service_errors(service_file: Path) -> List[str]:
    content = _read_text(service_file)
    errors: List[str] = []
    if "backend.api_public:app" not in content:
        errors.append("missing backend.api_public:app in ExecStart")
    if "--workers" in content:
        errors.append("service must stay single-process")
    if "LimitNOFILE=65535" not in content:
        errors.append("LimitNOFILE=65535 is required")
    if "UMask=0027" not in content:
        errors.append("UMask=0027 is required")
    return errors


def _env_example_errors(env_file: Path) -> List[str]:
    content = _read_text(env_file)
    required_keys = [
        "REMOTE_BASE_URL",
        "REMOTE_USERNAME",
        "REMOTE_PASSWORD",
        "REMOTE_AUTO_SYNC_SECONDS",
        "CORS_ALLOW_ORIGINS",
    ]
    errors: List[str] = []
    for key in required_keys:
        if f"{key}=" not in content:
            errors.append(f"missing {key}")
    return errors


def _baseline_doc_errors(doc: Path, strict: bool = True) -> List[str]:
    content = _read_text(doc)
    errors: List[str] = []
    required_snippets = [
        "Backend test collection baseline:",
        "Backend test execution baseline:",
        "Primary backend entrypoint: `backend.api_public:app`",
        "`/healthz`",
    ]
    for snippet in required_snippets:
        if snippet not in content:
            errors.append(f"missing required baseline snippet: {snippet}")
    if strict and "single process" not in content and "single-process" not in content:
        errors.append("missing single-process constraint")
    return errors


def _probe_json(base_url: str, path: str, timeout: float) -> Tuple[int, object]:
    request = Request(base_url.rstrip("/") + path)
    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        return response.status, payload


def _http_errors(base_url: str, timeout: float, allow_readyz_503: bool = False) -> List[str]:
    errors: List[str] = []
    for path in ("/healthz", "/ops/status", "/readyz"):
        try:
            status, payload = _probe_json(base_url, path, timeout)
        except Exception as exc:  # pragma: no cover - defensive
            message = str(exc).replace("Traceback", "").strip()
            errors.append(message)
            continue
        if path == "/readyz" and allow_readyz_503 and status == 503:
            continue
        if status >= 400:
            errors.append(f"{path} returned HTTP {status}")
            continue
        if not isinstance(payload, (dict, list)):
            errors.append(f"{path} returned non-JSON payload")
    return errors


def _bundle_asset_errors(bundle_dir: Path, strict_docs: bool = False) -> List[str]:
    errors: List[str] = []
    manifest_path = bundle_dir / "manifest.json"
    checksums_path = bundle_dir / "checksums.txt"
    verification = {}
    if not manifest_path.is_file():
        errors.append("missing bundle manifest")
    else:
        manifest = json.loads(_read_text(manifest_path))
        verification = manifest.get("verification", {}) if isinstance(manifest, dict) else {}

    for rel_path in verification.get("required_bundle_paths", REQUIRED_BUNDLE_PATHS):
        if not (bundle_dir / rel_path).is_file():
            errors.append(f"missing required bundle path: {rel_path}")

    if strict_docs:
        for rel_path in ("docs/README.md", "docs/ACCEPTANCE_CHECKLIST.md", "docs/RC_CANDIDATE_BASELINE.md", "docs/LOCAL_RELEASE_REHEARSAL.md"):
            if not (bundle_dir / rel_path).is_file():
                errors.append(f"missing required bundle path: {rel_path}")

    for rel_path in verification.get("forbidden_runtime_data_paths", FORBIDDEN_RUNTIME_DATA_PATHS):
        if (bundle_dir / rel_path).is_file():
            errors.append(f"runtime-state files must not be pre-bundled: {rel_path}")

    if not checksums_path.is_file():
        errors.append("missing checksums file")
    else:
        checksums = _read_text(checksums_path)
        for rel_path in verification.get("required_model_paths", REQUIRED_MODEL_PATHS):
            if rel_path not in checksums:
                errors.append(f"missing checksum for {rel_path}")
            if not (bundle_dir / rel_path).is_file():
                errors.append(f"missing required model path: {rel_path}")
    return errors


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", default=".")
    parser.add_argument("--base-url", default="http://127.0.0.1:5018")
    args = parser.parse_args(list(argv) if argv is not None else None)
    bundle_dir = Path(args.bundle_dir)
    errors = _bundle_asset_errors(bundle_dir, strict_docs=True)
    errors.extend(_http_errors(args.base_url, 5.0, allow_readyz_503=True))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
