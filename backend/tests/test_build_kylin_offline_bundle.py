from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "build_kylin_offline_bundle.py"


def _load_bundle_module():
    spec = importlib.util.spec_from_file_location("build_kylin_offline_bundle", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_verify_models_dir_requires_base_model_files(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_bundle_module()
    monkeypatch.setattr(module, "REPO_ROOT", Path("/repo"))

    existing_paths = {
        "/repo/models",
        "/repo/models/joint_rbt3/joint_model.pt",
    }

    def fake_exists(path: Path) -> bool:
        return path.as_posix() in existing_paths

    monkeypatch.setattr(Path, "exists", fake_exists)

    with pytest.raises(FileNotFoundError) as excinfo:
        module._verify_models_dir()

    message = str(excinfo.value)
    assert "config.json" in message
    assert "pytorch_model.bin" in message


def test_copy_models_copies_full_models_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_bundle_module()
    source_dir = Path("/repo/models")
    output_dir = Path("/bundle")
    captured: dict[str, object] = {}

    monkeypatch.setattr(module, "_verify_models_dir", lambda: source_dir)

    def fake_copy_tree(src: Path, dst: Path, *, ignore=None) -> None:
        captured["src"] = src
        captured["dst"] = dst
        captured["ignore"] = ignore

    monkeypatch.setattr(module, "_copy_tree", fake_copy_tree)

    module._copy_models(output_dir)

    assert captured["src"] == source_dir
    assert captured["dst"] == output_dir / "models"
    assert captured["ignore"] is not None


def test_verify_wheelhouse_crf_package_accepts_pytorch_crf(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_bundle_module()
    wheelhouse = Path("/bundle/wheelhouse")

    def fake_iterdir(self: Path):
        if self == wheelhouse:
            return iter(
                [
                    wheelhouse / "pytorch_crf-0.7.2-py3-none-any.whl",
                    wheelhouse / "torch-2.8.0+cpu.whl",
                ]
            )
        return iter(())

    monkeypatch.setattr(Path, "iterdir", fake_iterdir)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    assert module._verify_wheelhouse_crf_package(wheelhouse) == wheelhouse


def test_verify_wheelhouse_crf_package_rejects_missing_or_wrong_crf(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_bundle_module()
    wheelhouse = Path("/bundle/wheelhouse")

    def fake_iterdir(self: Path):
        if self == wheelhouse:
            return iter(
                [
                    wheelhouse / "TorchCRF-1.1.0-py3-none-any.whl",
                    wheelhouse / "torch-2.8.0+cpu.whl",
                ]
            )
        return iter(())

    monkeypatch.setattr(Path, "iterdir", fake_iterdir)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    with pytest.raises(FileNotFoundError):
        module._verify_wheelhouse_crf_package(wheelhouse)


def test_verify_wheelhouse_crf_package_rejects_forbidden_torchcrf(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_bundle_module()
    wheelhouse = Path("/bundle/wheelhouse")

    def fake_iterdir(self: Path):
        if self == wheelhouse:
            return iter(
                [
                    wheelhouse / "pytorch_crf-0.7.2-py3-none-any.whl",
                    wheelhouse / "TorchCRF-1.1.0-py3-none-any.whl",
                ]
            )
        return iter(())

    monkeypatch.setattr(Path, "iterdir", fake_iterdir)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    with pytest.raises(RuntimeError) as excinfo:
        module._verify_wheelhouse_crf_package(wheelhouse)

    assert "TorchCRF-1.1.0-py3-none-any.whl".lower() in str(excinfo.value)


def test_verify_wheelhouse_runtime_packages_requires_psutil(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_bundle_module()
    wheelhouse = Path("/bundle/wheelhouse")

    def fake_iterdir(self: Path):
        if self == wheelhouse:
            return iter(
                [
                    wheelhouse / "psutil-5.9.8-cp39-cp39-manylinux.whl",
                    wheelhouse / "torch-2.8.0+cpu-cp39-cp39-manylinux.whl",
                    wheelhouse / "transformers-4.57.3-py3-none-any.whl",
                    wheelhouse / "datasets-4.4.2-py3-none-any.whl",
                    wheelhouse / "fastapi-0.115.0-py3-none-any.whl",
                    wheelhouse / "uvicorn-0.34.0-py3-none-any.whl",
                ]
            )
        return iter(())

    monkeypatch.setattr(Path, "iterdir", fake_iterdir)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    assert module._verify_wheelhouse_runtime_packages(wheelhouse) == wheelhouse


def test_verify_wheelhouse_runtime_packages_rejects_missing_psutil(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_bundle_module()
    wheelhouse = Path("/bundle/wheelhouse")

    def fake_iterdir(self: Path):
        if self == wheelhouse:
            return iter([wheelhouse / "torch-2.8.0+cpu.whl"])
        return iter(())

    monkeypatch.setattr(Path, "iterdir", fake_iterdir)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    with pytest.raises(FileNotFoundError):
        module._verify_wheelhouse_runtime_packages(wheelhouse)


def test_verify_wheelhouse_runtime_packages_rejects_non_cpu_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_bundle_module()
    wheelhouse = Path("/bundle/wheelhouse")

    def fake_iterdir(self: Path):
        if self == wheelhouse:
            return iter(
                [
                    wheelhouse / "psutil-5.9.8-cp39-cp39-manylinux.whl",
                    wheelhouse / "torch-2.8.0-cp39-cp39-manylinux.whl",
                    wheelhouse / "transformers-4.57.3-py3-none-any.whl",
                    wheelhouse / "datasets-4.4.2-py3-none-any.whl",
                    wheelhouse / "fastapi-0.115.0-py3-none-any.whl",
                    wheelhouse / "uvicorn-0.34.0-py3-none-any.whl",
                ]
            )
        return iter(())

    monkeypatch.setattr(Path, "iterdir", fake_iterdir)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    with pytest.raises(FileNotFoundError) as excinfo:
        module._verify_wheelhouse_runtime_packages(wheelhouse)

    assert "torch (cpu-only)" in str(excinfo.value)


def test_build_bundle_verifies_wheelhouse_when_not_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_bundle_module()
    output_dir = Path("/bundle")
    wheelhouse = output_dir / "wheelhouse"
    calls: list[tuple[str, object]] = []
    requirements_file = Path("/repo/deploy/offline/requirements.runtime.cpu.txt")
    cache_dir = Path("/cache/wheelhouse")

    monkeypatch.setattr(module.Path, "resolve", lambda self: self)
    monkeypatch.setattr(module, "_build_web_dist", lambda skip_web_build: Path("/repo/web/dist"))
    monkeypatch.setattr(module, "_copy_phase_scripts", lambda output: calls.append(("phase", output)))
    monkeypatch.setattr(module, "_copy_python_installer", lambda installer, output: calls.append(("python", output)))
    monkeypatch.setattr(
        module,
        "_build_wheelhouse",
        lambda output, skip_wheelhouse, requirements_file, cache_dir, refresh_wheelhouse: wheelhouse,
    )
    monkeypatch.setattr(module, "_verify_wheelhouse_crf_package", lambda path: calls.append(("wheelhouse", path)))
    monkeypatch.setattr(module, "_verify_wheelhouse_runtime_packages", lambda path: calls.append(("runtime-wheelhouse", path)))
    monkeypatch.setattr(module, "_copy_app_snapshot", lambda output, requirements: calls.append(("app", requirements)))
    monkeypatch.setattr(module, "_copy_models", lambda output: calls.append(("models", output)))
    monkeypatch.setattr(module, "_copy_runtime_data", lambda output: calls.append(("runtime", output)))
    monkeypatch.setattr(module, "_copy_web_dist", lambda web_dist, output: calls.append(("web", web_dist)))
    monkeypatch.setattr(module, "_copy_systemd_assets", lambda output: calls.append(("systemd", output)))
    monkeypatch.setattr(module, "_copy_docs", lambda output: calls.append(("docs", output)))
    monkeypatch.setattr(module, "_write_manifest", lambda output: calls.append(("manifest", output)))
    monkeypatch.setattr(module.shutil, "rmtree", lambda path: calls.append(("rmtree", path)))
    monkeypatch.setattr(module.Path, "mkdir", lambda self, parents=False, exist_ok=False: calls.append(("mkdir", self)))
    monkeypatch.setattr(module.Path, "exists", lambda self: False)

    module.build_bundle(
        output_dir,
        Path("/python.sh"),
        skip_web_build=True,
        skip_wheelhouse=False,
        requirements_file=requirements_file,
        wheelhouse_cache_dir=cache_dir,
        refresh_wheelhouse=False,
    )

    assert ("wheelhouse", wheelhouse) in calls
    assert ("runtime-wheelhouse", wheelhouse) in calls
    assert ("app", requirements_file) in calls


def test_copy_docs_includes_acceptance_and_verification_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_bundle_module()
    output_dir = Path("/bundle")
    docs_dir = output_dir / "docs"
    copied: list[tuple[Path, Path]] = []

    monkeypatch.setattr(module, "_ensure_dir", lambda path: path)
    monkeypatch.setattr(module, "_copy_file", lambda src, dst: copied.append((src, dst)))

    module._copy_docs(output_dir)

    assert (module.REPO_ROOT / "deploy" / "offline" / "README.md", docs_dir / "README.md") in copied
    assert (
        module.REPO_ROOT / "deploy" / "offline" / "ACCEPTANCE_CHECKLIST.md",
        docs_dir / "ACCEPTANCE_CHECKLIST.md",
    ) in copied
    assert (
        module.REPO_ROOT / "deploy" / "RC_CANDIDATE_BASELINE.md",
        docs_dir / "RC_CANDIDATE_BASELINE.md",
    ) in copied
    assert (
        module.REPO_ROOT / "deploy" / "LOCAL_RELEASE_REHEARSAL.md",
        docs_dir / "LOCAL_RELEASE_REHEARSAL.md",
    ) in copied
    assert (
        module.REPO_ROOT / "scripts" / "verify_rc_candidate.py",
        docs_dir / "verify_rc_candidate.py",
    ) in copied


def test_runtime_data_manifest_excludes_template_resources() -> None:
    module = _load_bundle_module()

    assert "schedule_template" not in module.RUNTIME_DATA_FILES
    assert "schedule_templates" not in module.RUNTIME_DATA_DIRS


def test_copy_app_snapshot_keeps_backend_default_data(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_bundle_module()
    output_dir = Path("/bundle")
    captured: list[tuple[Path, Path, object]] = []

    monkeypatch.setattr(module, "_ensure_dir", lambda path: path)
    monkeypatch.setattr(module, "_copy_file", lambda src, dst: None)

    def fake_copy_tree(src: Path, dst: Path, *, ignore=None) -> None:
        captured.append((src, dst, ignore))

    monkeypatch.setattr(module, "_copy_tree", fake_copy_tree)

    module._copy_app_snapshot(output_dir, Path("/repo/deploy/offline/requirements.runtime.cpu.txt"))

    backend_call = next(call for call in captured if call[0] == module.REPO_ROOT / "backend")
    ignore = backend_call[2]
    ignored_names = set(ignore(str(module.REPO_ROOT / "backend"), ["data", "default_data", "tests"]))

    assert "data" in ignored_names
    assert "tests" in ignored_names
    assert "default_data" not in ignored_names


def test_copy_app_snapshot_overwrites_runtime_requirements(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_bundle_module()
    copied_files: list[tuple[Path, Path]] = []

    monkeypatch.setattr(module, "_ensure_dir", lambda path: path)
    monkeypatch.setattr(module, "_copy_tree", lambda src, dst, ignore=None: None)
    monkeypatch.setattr(module, "_copy_file", lambda src, dst: copied_files.append((src, dst)))

    requirements_file = Path("/repo/deploy/offline/requirements.runtime.cpu.txt")
    module._copy_app_snapshot(Path("/bundle"), requirements_file)

    assert (requirements_file, Path("/bundle/app/requirements.txt")) in copied_files


def test_build_wheelhouse_reuses_cache_without_redownload(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_bundle_module()
    output_dir = Path("/bundle")
    cache_dir = Path("/cache")
    requirements_file = Path("/req.txt")
    copied: list[tuple[Path, Path]] = []
    runs: list[list[str]] = []

    monkeypatch.setattr(module, "_ensure_dir", lambda path: path)
    monkeypatch.setattr(module, "_copy_tree", lambda src, dst, ignore=None: copied.append((src, dst)))
    monkeypatch.setattr(module, "_run", lambda command, cwd=None: runs.append(command))
    monkeypatch.setattr(module, "_verify_wheelhouse_crf_package", lambda path: path)
    monkeypatch.setattr(module, "_verify_wheelhouse_runtime_packages", lambda path: path)
    monkeypatch.setattr(module.Path, "iterdir", lambda self: iter([self / "torch-2.8.0+cpu.whl"]) if self == cache_dir else iter(()))
    monkeypatch.setattr(module.Path, "is_file", lambda self: True)

    wheelhouse = module._build_wheelhouse(
        output_dir,
        skip_wheelhouse=False,
        requirements_file=requirements_file,
        cache_dir=cache_dir,
        refresh_wheelhouse=False,
    )

    assert wheelhouse == output_dir / "wheelhouse"
    assert copied == [(cache_dir, output_dir / "wheelhouse")]
    assert runs == []


def test_write_manifest_includes_verification_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_bundle_module()
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "_manifest_entries",
        lambda base_dir: iter([{"path": "docs/README.md", "size": 2, "sha256": "abc"}]),
    )

    def fake_write_text(self: Path, text: str, encoding: str = "utf-8") -> int:
        captured[self.as_posix()] = text
        return len(text)

    monkeypatch.setattr(module.Path, "write_text", fake_write_text)

    module._write_manifest(Path("C:/bundle"))

    manifest = json.loads(captured["C:/bundle/manifest.json"])

    assert manifest["entrypoint"] == "backend.api_public:app"
    assert "verification" in manifest
    assert "required_bundle_paths" in manifest["verification"]
    assert "required_model_paths" in manifest["verification"]
    assert "forbidden_runtime_data_paths" in manifest["verification"]
    assert "docs/README.md" in {entry["path"] for entry in manifest["files"]}
    assert "docs/README.md" in captured["C:/bundle/checksums.txt"]
