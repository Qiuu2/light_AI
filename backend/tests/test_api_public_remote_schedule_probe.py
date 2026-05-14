from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


def test_remote_fetch_schedule_source_surfaces_bad_gateway(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "REMOTE_SCHEDULES_PATH", "/task/sechinfo")
    monkeypatch.setattr(api_public, "REMOTE_SCHEDULES_FALLBACK_PATH", "/task/sechinfo")

    def fake_remote_request(method: str, path: str, **kwargs):
        del kwargs
        assert method == "GET"
        assert path == "/task/sechinfo"
        raise api_public.HTTPException(
            status_code=502,
            detail="Remote request failed: <html><body>502 Bad Gateway</body></html>",
        )

    monkeypatch.setattr(api_public, "_remote_request", fake_remote_request)

    with pytest.raises(api_public.HTTPException) as excinfo:
        api_public._remote_fetch_schedule_source()

    assert excinfo.value.status_code == 502
    assert "Bad Gateway" in str(excinfo.value.detail)


def test_live_remote_schedule_endpoint_returns_data_when_enabled() -> None:
    if os.getenv("RUN_LIVE_REMOTE_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_REMOTE_TESTS=1 to probe the real /task/sechinfo endpoint.")
    if not api_public._remote_enabled():
        pytest.skip("Remote base URL is not configured in this environment.")

    path = api_public.REMOTE_SCHEDULES_FALLBACK_PATH or "/task/sechinfo"
    payload = api_public._remote_request("GET", path)
    rows = api_public._remote_data_list(payload)

    assert isinstance(payload, (dict, list))
    assert rows, f"Remote endpoint {path} returned no schedule rows."
