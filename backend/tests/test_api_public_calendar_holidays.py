from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.api_public as api_public


@pytest.fixture(autouse=True)
def _isolate_calendar_holidays() -> None:
    original_entry = deepcopy(api_public.DATA_STORE["calendar_holidays_cn"])
    api_public._store_set("calendar_holidays_cn", {"years": {}})
    yield
    api_public.DATA_STORE["calendar_holidays_cn"] = original_entry


def _auth_headers() -> dict[str, str]:
    session = api_public._create_local_session("remote-test-token", "tester", "test")
    return {"X-Token": session["token"]}


def test_load_calendar_holidays_year_payload_returns_normalized_days() -> None:
    api_public._store_set(
        "calendar_holidays_cn",
        api_public._normalize_calendar_holidays_payload(
            {
                "years": {
                    "2026": {
                        "days": {
                            "20260101": {"name": "元旦", "type": "holiday", "isWorkday": False},
                            "2026-02-15": {"name": "春节调休", "type": "makeup_workday", "isWorkday": False},
                        }
                    }
                }
            }
        ),
    )

    result = api_public._load_calendar_holidays_year_payload("2026")

    assert result["year"] == 2026
    assert result["days"]["2026-01-01"] == {
        "name": "元旦",
        "type": "holiday",
        "isWorkday": False,
    }
    assert result["days"]["2026-02-15"] == {
        "name": "春节调休",
        "type": "makeup_workday",
        "isWorkday": True,
    }


def test_load_calendar_holidays_year_payload_returns_empty_days_for_missing_year() -> None:
    api_public._store_set("calendar_holidays_cn", {"years": {"2026": {"days": {}}}})

    result = api_public._load_calendar_holidays_year_payload("2027")

    assert result == {"year": 2027, "days": {}}


def test_get_calendar_holidays_rejects_invalid_year(monkeypatch) -> None:
    monkeypatch.setattr(api_public, "_init_data_store", lambda: None)

    with TestClient(api_public.app) as client:
        response = client.get(
            "/data/calendar_holidays",
            params={"year": "bad-year"},
            headers=_auth_headers(),
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid year"
