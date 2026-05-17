from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, List, Tuple
from urllib.error import HTTPError
from urllib.request import Request, urlopen


REQUIRED_FILE_PATHS = [
    "manifest.json",
    "checksums.txt",
    "app/backend/api_public.py",
    "python/python.exe",
    "service/ai-speaker-service.exe",
    "service/ai-speaker-service.xml",
    "service/install-service.ps1",
    "service/uninstall-service.ps1",
    "web-dist/index.html",
    "models/config.json",
    "models/pytorch_model.bin",
    "models/tokenizer.json",
    "models/tokenizer_config.json",
    "models/vocab.txt",
    "models/joint_rbt3/joint_model.pt",
]

REQUIRED_DIR_PATHS = [
    "app/src",
    "web-dist/static",
]

REQUIRED_CHECKSUM_PATHS = [
    path for path in REQUIRED_FILE_PATHS if path != "checksums.txt"
]

FORBIDDEN_RUNTIME_DATA_PATHS = [
    "runtime-data/assistant_command_logs.json",
    "runtime-data/remote_sync_meta.json",
]


def _read_text(path: Path) -> str:
    # 兼容 BOM：Windows PowerShell 5.x 的 Set-Content -Encoding UTF8 会留 BOM。
    return path.read_text(encoding="utf-8-sig")


def _bundle_path(bundle_dir: Path, rel_path: str) -> Path:
    return bundle_dir / Path(rel_path.replace("/", "\\"))


def _manifest_errors(bundle_dir: Path) -> List[str]:
    manifest_path = _bundle_path(bundle_dir, "manifest.json")
    if not manifest_path.is_file():
        return ["missing manifest.json"]
    try:
        manifest = json.loads(_read_text(manifest_path))
    except json.JSONDecodeError as exc:
        return [f"manifest.json is not valid JSON: {exc}"]
    errors: List[str] = []
    expected = {
        "platform": "windows-x64",
        "entrypoint": "backend.api_public:app",
        "port": 5018,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            errors.append(f"manifest.json {key} must be {value!r}")
    return errors


def _path_errors(bundle_dir: Path) -> List[str]:
    errors: List[str] = []
    for rel_path in REQUIRED_FILE_PATHS:
        if not _bundle_path(bundle_dir, rel_path).is_file():
            errors.append(f"missing required file: {rel_path}")
    for rel_path in REQUIRED_DIR_PATHS:
        if not _bundle_path(bundle_dir, rel_path).is_dir():
            errors.append(f"missing required directory: {rel_path}")
    return errors


def _checksum_errors(bundle_dir: Path) -> List[str]:
    checksums_path = _bundle_path(bundle_dir, "checksums.txt")
    if not checksums_path.is_file():
        return ["missing checksums.txt"]
    checksums = _read_text(checksums_path).replace("\\", "/")
    errors: List[str] = []
    for rel_path in REQUIRED_CHECKSUM_PATHS:
        if rel_path not in checksums:
            errors.append(f"missing checksum for {rel_path}")
    return errors


def _runtime_data_errors(bundle_dir: Path) -> List[str]:
    errors: List[str] = []
    for rel_path in FORBIDDEN_RUNTIME_DATA_PATHS:
        if _bundle_path(bundle_dir, rel_path).is_file():
            errors.append(f"runtime-state file must not be pre-bundled: {rel_path}")

    remote_settings_path = _bundle_path(bundle_dir, "runtime-data/remote_settings.json")
    if remote_settings_path.is_file():
        try:
            payload = json.loads(_read_text(remote_settings_path))
        except json.JSONDecodeError:
            errors.append("runtime-data/remote_settings.json must not contain invalid JSON")
        else:
            remote_base_url = str(payload.get("remote_base_url", "") if isinstance(payload, dict) else "").strip()
            if remote_base_url:
                errors.append("runtime-data/remote_settings.json must not pre-bundle a remote_base_url")
    return errors


def _service_xml_errors(bundle_dir: Path) -> List[str]:
    service_xml_path = _bundle_path(bundle_dir, "service/ai-speaker-service.xml")
    if not service_xml_path.is_file():
        return ["missing service/ai-speaker-service.xml"]
    content = _read_text(service_xml_path)
    required_snippets = [
        "<executable>%BASE%\\..\\python\\python.exe</executable>",
        "-m uvicorn backend.api_public:app --host 0.0.0.0 --port 5018",
        '<env name="PYTHONPATH" value="%BASE%\\..\\app" />',
        '<env name="AI_SPEAKER_DATA_DIR" value="%ProgramData%\\AI Speaker\\data" />',
        '<env name="AI_SPEAKER_NLU_DATA_DIR" value="%BASE%\\..\\data" />',
        '<env name="AI_SPEAKER_WEB_DIST" value="%BASE%\\..\\web-dist" />',
    ]
    errors: List[str] = []
    for snippet in required_snippets:
        if snippet not in content:
            errors.append(f"service XML missing required snippet: {snippet}")
    return errors


def bundle_errors(bundle_dir: Path) -> List[str]:
    return (
        _manifest_errors(bundle_dir)
        + _path_errors(bundle_dir)
        + _checksum_errors(bundle_dir)
        + _runtime_data_errors(bundle_dir)
        + _service_xml_errors(bundle_dir)
    )


def _probe(base_url: str, path: str, timeout: float) -> Tuple[int, str]:
    request = Request(base_url.rstrip("/") + path)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def http_errors(base_url: str, timeout: float) -> List[str]:
    errors: List[str] = []
    for path in ("/healthz", "/ops/status", "/readyz", "/"):
        try:
            status, body = _probe(base_url, path, timeout)
        except Exception as exc:
            message = str(exc).replace("Traceback", "").strip()
            errors.append(message)
            continue
        if path == "/readyz" and status == 503:
            continue
        if status >= 400:
            errors.append(f"{path} returned HTTP {status}")
            continue
        if path == "/" and "<html" not in body.lower():
            errors.append("/ returned non-HTML content")
    return errors


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", default="deploy/out/windows-x64")
    parser.add_argument("--base-url", default="http://127.0.0.1:5018")
    parser.add_argument("--skip-http-probe", action="store_true")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args(list(argv) if argv is not None else None)

    errors = bundle_errors(Path(args.bundle_dir))
    if not args.skip_http_probe:
        errors.extend(http_errors(args.base_url, args.timeout))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
