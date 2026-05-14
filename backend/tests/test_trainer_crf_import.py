from __future__ import annotations

from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import trainer as trainer_module


def test_load_crf_class_accepts_uppercase_module_name(monkeypatch) -> None:
    class _DummyCRF:
        pass

    uppercase_module = types.SimpleNamespace(CRF=_DummyCRF)

    def fake_import_module(name: str):
        if name == "torchcrf":
            raise ModuleNotFoundError(name)
        if name == "TorchCRF":
            return uppercase_module
        raise AssertionError(name)

    monkeypatch.setattr(trainer_module.importlib, "import_module", fake_import_module)

    assert trainer_module._load_crf_class() is _DummyCRF


def test_load_crf_class_returns_none_when_crf_module_missing(monkeypatch) -> None:
    def fake_import_module(name: str):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(trainer_module.importlib, "import_module", fake_import_module)

    assert trainer_module._load_crf_class() is None
