from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "verify_windows_bundle.py"


def _load_verify_module():
    spec = importlib.util.spec_from_file_location("verify_windows_bundle", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_valid_bundle(bundle_dir: Path) -> None:
    manifest = {
        "name": "AI Speaker",
        "version": "1.0.0",
        "platform": "windows-x64",
        "port": 5018,
        "entrypoint": "backend.api_public:app",
    }
    files = {
        "manifest.json": json.dumps(manifest),
        "app/backend/api_public.py": "app = object()\n",
        "python/python.exe": "python",
        "service/ai-speaker-service.exe": "winsw",
        "service/ai-speaker-service.xml": """
<service>
  <executable>%BASE%\\..\\python\\python.exe</executable>
  <arguments>-m uvicorn backend.api_public:app --host 0.0.0.0 --port 5018</arguments>
  <env name="PYTHONPATH" value="%BASE%\\..\\app" />
  <env name="AI_SPEAKER_DATA_DIR" value="%ProgramData%\\AI Speaker\\data" />
  <env name="AI_SPEAKER_NLU_DATA_DIR" value="%BASE%\\..\\data" />
  <env name="AI_SPEAKER_WEB_DIST" value="%BASE%\\..\\web-dist" />
</service>
""".strip(),
        "service/install-service.ps1": "install",
        "service/uninstall-service.ps1": "uninstall",
        "web-dist/index.html": "<html></html>",
        "models/config.json": "{}",
        "models/pytorch_model.bin": "bin",
        "models/tokenizer.json": "{}",
        "models/tokenizer_config.json": "{}",
        "models/vocab.txt": "vocab",
        "models/joint_rbt3/joint_model.pt": "pt",
        "runtime-data/all_audio.json": "{}",
        "runtime-data/all_loc.json": "{}",
        "runtime-data/all_task.json": "{}",
        "runtime-data/broadcast_schedules.json": "{}",
        "runtime-data/templates.json": "{}",
    }
    for rel_path, content in files.items():
        _write(bundle_dir / rel_path, content)
    (bundle_dir / "app" / "src").mkdir(parents=True, exist_ok=True)
    (bundle_dir / "web-dist" / "static").mkdir(parents=True, exist_ok=True)
    checksum_lines = [f"deadbeef  {rel_path}" for rel_path in files if rel_path != "manifest.json"]
    checksum_lines.append("deadbeef  manifest.json")
    _write(bundle_dir / "checksums.txt", "\n".join(checksum_lines) + "\n")


def test_bundle_errors_accepts_complete_windows_bundle(tmp_path: Path) -> None:
    module = _load_verify_module()
    bundle_dir = tmp_path / "windows-x64"
    _write_valid_bundle(bundle_dir)

    assert module.bundle_errors(bundle_dir) == []


def test_bundle_errors_rejects_missing_required_files(tmp_path: Path) -> None:
    module = _load_verify_module()
    bundle_dir = tmp_path / "windows-x64"
    _write_valid_bundle(bundle_dir)
    (bundle_dir / "python" / "python.exe").unlink()
    (bundle_dir / "web-dist" / "index.html").unlink()
    (bundle_dir / "service" / "ai-speaker-service.xml").unlink()
    (bundle_dir / "models" / "joint_rbt3" / "joint_model.pt").unlink()

    errors = module.bundle_errors(bundle_dir)

    joined = "\n".join(errors)
    assert "python/python.exe" in joined
    assert "web-dist/index.html" in joined
    assert "service/ai-speaker-service.xml" in joined
    assert "models/joint_rbt3/joint_model.pt" in joined


def test_bundle_errors_rejects_runtime_state_files(tmp_path: Path) -> None:
    module = _load_verify_module()
    bundle_dir = tmp_path / "windows-x64"
    _write_valid_bundle(bundle_dir)
    _write(bundle_dir / "runtime-data" / "assistant_command_logs.json", "{}")
    _write(bundle_dir / "runtime-data" / "remote_sync_meta.json", "{}")
    _write(bundle_dir / "runtime-data" / "remote_settings.json", json.dumps({"remote_base_url": "http://192.168.3.199"}))

    errors = module.bundle_errors(bundle_dir)

    joined = "\n".join(errors)
    assert "assistant_command_logs.json" in joined
    assert "remote_sync_meta.json" in joined
    assert "remote_base_url" in joined


def test_main_skip_http_probe_does_not_call_http(tmp_path: Path, monkeypatch) -> None:
    module = _load_verify_module()
    bundle_dir = tmp_path / "windows-x64"
    _write_valid_bundle(bundle_dir)

    def fail_http(base_url: str, timeout: float):
        raise AssertionError("HTTP probe should be skipped")

    monkeypatch.setattr(module, "http_errors", fail_http)

    assert module.main(["--bundle-dir", str(bundle_dir), "--skip-http-probe"]) == 0


def test_http_errors_allows_readyz_503_and_requires_index_html(monkeypatch) -> None:
    module = _load_verify_module()

    def fake_probe(base_url: str, path: str, timeout: float):
        payloads = {
            "/healthz": (200, '{"status":"ok"}'),
            "/ops/status": (200, '{"status":"ok"}'),
            "/readyz": (503, '{"status":"not_ready"}'),
            "/": (200, "<html></html>"),
        }
        return payloads[path]

    monkeypatch.setattr(module, "_probe", fake_probe)

    assert module.http_errors("http://127.0.0.1:5018", 5.0) == []


def test_service_xml_errors_reports_wrong_service_shape(tmp_path: Path) -> None:
    module = _load_verify_module()
    bundle_dir = tmp_path / "windows-x64"
    _write(bundle_dir / "service" / "ai-speaker-service.xml", "<service></service>")

    errors = module._service_xml_errors(bundle_dir)

    joined = "\n".join(errors)
    assert "python.exe" in joined
    assert "backend.api_public:app" in joined
    assert "AI_SPEAKER_DATA_DIR" in joined
