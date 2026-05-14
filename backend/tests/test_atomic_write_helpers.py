from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services import data_store
from backend.services import file_permissions
import backend.api_public as api_public


class _FakeHandle:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self.flushed = False

    def write(self, text: str) -> None:
        self.writes.append(text)

    def flush(self) -> None:
        self.flushed = True

    def fileno(self) -> int:
        return 321

    def __enter__(self) -> _FakeHandle:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False


def test_data_store_write_json_uses_atomic_replace(monkeypatch) -> None:
    target = Path("C:/virtual/state.json")
    handle = _FakeHandle()
    replaced: dict = {}
    fsync_calls: list[int] = []
    permission_calls: list[Path] = []

    monkeypatch.setattr(data_store, "backup_file", lambda path: None)
    monkeypatch.setattr(data_store, "apply_shared_json_permissions", lambda path: permission_calls.append(path))
    monkeypatch.setattr(Path, "mkdir", lambda self, parents=False, exist_ok=False: None)
    monkeypatch.setattr(data_store.tempfile, "mkstemp", lambda **kwargs: (123, "C:/virtual/.state.json.mock.tmp"))
    monkeypatch.setattr(data_store.os, "fdopen", lambda fd, mode, encoding=None: handle)
    monkeypatch.setattr(data_store.os, "fsync", lambda fd: fsync_calls.append(fd))
    monkeypatch.setattr(
        data_store.os,
        "replace",
        lambda src, dst: replaced.update({"src": src, "dst": dst}),
    )

    data_store.write_json(target, {"new": 2})

    assert json.loads(handle.writes[0]) == {"new": 2}
    assert handle.flushed is True
    assert fsync_calls == [321]
    assert Path(replaced["src"]) == Path("C:/virtual/.state.json.mock.tmp")
    assert Path(replaced["dst"]) == Path("C:/virtual/state.json")
    assert permission_calls == [target]


def test_api_public_write_json_uses_atomic_replace(monkeypatch) -> None:
    target = Path("C:/virtual/runtime.json")
    handle = _FakeHandle()
    replaced: dict = {}
    fsync_calls: list[int] = []
    permission_calls: list[Path] = []

    monkeypatch.setattr(api_public, "_backup_file", lambda path: None)
    monkeypatch.setattr(api_public, "apply_shared_json_permissions", lambda path: permission_calls.append(path))
    monkeypatch.setattr(Path, "mkdir", lambda self, parents=False, exist_ok=False: None)
    monkeypatch.setattr(api_public.tempfile, "mkstemp", lambda **kwargs: (456, "C:/virtual/.runtime.json.mock.tmp"))
    monkeypatch.setattr(api_public.os, "fdopen", lambda fd, mode, encoding=None: handle)
    monkeypatch.setattr(api_public.os, "fsync", lambda fd: fsync_calls.append(fd))
    monkeypatch.setattr(
        api_public.os,
        "replace",
        lambda src, dst: replaced.update({"src": src, "dst": dst}),
    )

    api_public._write_json(target, {"fresh": True})

    assert json.loads(handle.writes[0]) == {"fresh": True}
    assert handle.flushed is True
    assert fsync_calls == [321]
    assert Path(replaced["src"]) == Path("C:/virtual/.runtime.json.mock.tmp")
    assert Path(replaced["dst"]) == Path("C:/virtual/runtime.json")
    assert permission_calls == [target]


def test_shared_json_permission_repair_is_best_effort(monkeypatch) -> None:
    class _FakePath:
        def __init__(self, name: str, parent: _FakePath | None = None) -> None:
            self.name = name
            self.parent = parent or self

        def chmod(self, mode: int) -> None:
            chmod_calls.append((self.name, mode))
            raise OSError("chmod unavailable")

    chmod_calls: list[tuple[str, int]] = []
    parent = _FakePath("C:/virtual")
    target = _FakePath("C:/virtual/runtime.json", parent)

    monkeypatch.setattr(file_permissions.os, "name", "posix", raising=False)

    file_permissions.apply_shared_json_permissions(target)  # type: ignore[arg-type]

    assert chmod_calls == [
        ("C:/virtual", file_permissions.RUNTIME_DIR_MODE),
        ("C:/virtual/runtime.json", file_permissions.RUNTIME_FILE_MODE),
    ]
