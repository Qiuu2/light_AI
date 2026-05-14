from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import engine as engine_module


class _DummySession:
    def __init__(self) -> None:
        self.last_dialog_state = None
        self.pending_slots = {}
        self.updated: list[tuple] = []

    def update(self, *args) -> None:
        self.updated.append(args)


class _DummyResponder:
    def generate(self, intent, status, slots, missing, prev_dialog_state):
        return {"output_speech": "ok", "dialog_state": "complete"}


def _slots_from_entities(entities: dict) -> dict:
    slots: dict = {}
    for key, values in entities.items():
        if values:
            slots[key] = values[0]
    return slots


def _build_engine(monkeypatch, run_model):
    engine = engine_module.JointInferenceEngine.__new__(engine_module.JointInferenceEngine)
    engine.session = _DummySession()
    engine.responder = _DummyResponder()
    engine._run_model = run_model
    engine._post_process_slots = lambda entities, intent: _slots_from_entities(entities)
    engine._check_missing_slots = lambda intent, slots: []
    engine._intent_cmd = lambda intent: 7
    monkeypatch.setattr(engine_module, "resolve_with_session", lambda session, intent, slots, text, standard_time: None)
    return engine


def test_infer_removes_ascii_spaces_before_model_and_response_fields(monkeypatch) -> None:
    captured: dict = {}

    def fake_run_model(text: str):
        captured["text"] = text
        return (
            "replace_media_in_task",
            0.98,
            {"new_media_name": ["陈奕迅孤勇者"], "media_name": ["上课铃"]},
            list(text),
            list(range(len(text))),
        )

    engine = _build_engine(monkeypatch, fake_run_model)

    result = engine.infer(" 用陈奕迅 孤勇者替换掉上课铃 ")

    assert captured["text"] == "用陈奕迅孤勇者替换掉上课铃"
    assert result["input"] == "用陈奕迅孤勇者替换掉上课铃"
    assert result["tokens"] == list("用陈奕迅孤勇者替换掉上课铃")
    assert result["entities"] == {"new_media_name": ["陈奕迅孤勇者"], "media_name": ["上课铃"]}
    assert result["slots"] == {"new_media_name": "陈奕迅孤勇者", "media_name": "上课铃"}


def test_infer_normalizes_play_media_input_the_same_with_or_without_spaces(monkeypatch) -> None:
    captured: list[str] = []

    def fake_run_model(text: str):
        captured.append(text)
        return ("play_media", 0.91, {"media_name": ["陈奕迅孤勇者"]}, list(text), [1] * len(text))

    engine = _build_engine(monkeypatch, fake_run_model)

    result_with_space = engine.infer("播放 陈奕迅 孤勇者")
    result_without_space = engine.infer("播放陈奕迅孤勇者")

    assert captured == ["播放陈奕迅孤勇者", "播放陈奕迅孤勇者"]
    assert result_with_space["input"] == result_without_space["input"] == "播放陈奕迅孤勇者"
    assert result_with_space["tokens"] == result_without_space["tokens"] == list("播放陈奕迅孤勇者")


def test_infer_keeps_tabs_and_full_width_spaces_inside_text(monkeypatch) -> None:
    captured: dict = {}

    def fake_run_model(text: str):
        captured["text"] = text
        return ("play_media", 0.88, {"media_name": [text]}, list(text), [2] * len(text))

    engine = _build_engine(monkeypatch, fake_run_model)

    result = engine.infer(" 播\t放　国歌 ")

    assert captured["text"] == "播\t放　国歌"
    assert result["input"] == "播\t放　国歌"
    assert result["tokens"] == ["播", "\t", "放", "　", "国", "歌"]
    assert result["slots"] == {
        "media_name": "播\t放　国歌",
        "task_name": "播\t放　国歌",
    }


def test_infer_returns_empty_result_after_ascii_space_normalization() -> None:
    engine = engine_module.JointInferenceEngine.__new__(engine_module.JointInferenceEngine)

    result = engine.infer("   ")

    assert result["input"] == ""
    assert result["intent"] == "none"
    assert result["tokens"] == []
    assert result["tag_ids"] == []
