from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.assistant import schedule_actions


class _FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, dict]] = []

    def _apply_create_scheme_intent(self, text: str, slots: dict, **kwargs):
        self.calls.append((text, dict(slots), dict(kwargs)))
        return "ok", {"missing_slots": []}, []


def test_apply_create_scheme_intent_keeps_shared_path_clean(monkeypatch) -> None:
    fake_api = _FakeApi()
    original_slots = {"schedule_name": "winter-schedule"}

    monkeypatch.setattr(schedule_actions, "_api", lambda: fake_api)

    reply, state, logs = schedule_actions.apply_create_scheme_intent("create winter schedule", original_slots)

    assert reply == "ok"
    assert state == {"missing_slots": []}
    assert logs == []
    assert len(fake_api.calls) == 1
    forwarded_text, forwarded_slots, forwarded_kwargs = fake_api.calls[0]
    assert forwarded_text == "create winter schedule"
    assert forwarded_slots == {"schedule_name": "winter-schedule"}
    assert forwarded_kwargs == {}
    assert original_slots == {"schedule_name": "winter-schedule"}


def test_apply_create_scheme_intent_for_assistant_passes_internal_scope(monkeypatch) -> None:
    fake_api = _FakeApi()
    original_slots = {"schedule_name": "winter-schedule"}

    monkeypatch.setattr(schedule_actions, "_api", lambda: fake_api)

    reply, state, logs = schedule_actions.apply_create_scheme_intent_for_assistant(
        "create winter schedule",
        original_slots,
    )

    assert reply == "ok"
    assert state == {"missing_slots": []}
    assert logs == []
    assert len(fake_api.calls) == 1
    forwarded_text, forwarded_slots, forwarded_kwargs = fake_api.calls[0]
    assert forwarded_text == "create winter schedule"
    assert forwarded_slots == {"schedule_name": "winter-schedule"}
    assert forwarded_kwargs == {
        "assistant_terminal_scope": schedule_actions._ASSISTANT_CREATE_SCHEDULE_ALL_PLAYBACK_TERMINALS
    }
    assert original_slots == {"schedule_name": "winter-schedule"}
