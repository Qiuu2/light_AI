import src.response_manager as response_manager
from src.response_manager import ResponseManager
from src.speech_templates import TEMPLATES


def test_key_success_reply_appends_fixed_followup() -> None:
    manager = ResponseManager()

    result = manager.generate(
        "adjust_volume",
        "success",
        {"zone_name": "高三一班"},
        prev_dialog_state=None,
    )

    assert "请问还有什么别的需求吗？" in result["output_speech"]
    assert "高三一班" in result["output_speech"]


def test_missing_slot_reply_is_more_natural_and_keeps_cancel_hint() -> None:
    manager = ResponseManager()

    result = manager.generate(
        "play_media",
        "incomplete",
        {},
        missing=["media_name"],
        prev_dialog_state=None,
    )

    assert "媒体" in result["output_speech"]
    assert "取消" in result["output_speech"]
    assert result["dialog_state"] == "ask"


def test_response_manager_style_avoids_old_ai_phrases() -> None:
    manager = ResponseManager()

    success = manager.generate("play_media", "success", {"media_name": "国歌"}, prev_dialog_state=None)
    none_result = manager.generate("none", "success", {}, prev_dialog_state=None)

    assert "这条我已经处理好了" not in success["output_speech"]
    assert "我先帮您" not in success["output_speech"]
    assert "我先听到了" not in none_result["output_speech"]


def test_key_templates_are_split_into_standard_and_light_versions() -> None:
    for key in (
        "move_schedule_success",
        "create_schedule_success",
        "play_media_success",
        "adjust_volume_success",
        "query_terminal_success",
        "query_task_success",
    ):
        entry = TEMPLATES[key]
        assert isinstance(entry, dict)
        assert isinstance(entry.get("standard"), list) and entry["standard"]
        assert isinstance(entry.get("light"), list) and entry["light"]


def test_success_reply_can_use_light_persona_variant(monkeypatch) -> None:
    monkeypatch.setattr(response_manager.random, "random", lambda: 0.1)
    monkeypatch.setattr(response_manager.random, "choice", lambda values: values[0])
    manager = ResponseManager()

    result = manager.generate(
        "play_media",
        "success",
        {"media_name": "国歌"},
        prev_dialog_state=None,
    )

    assert "国歌" in result["output_speech"]
    assert "小电已经" in result["output_speech"]
    assert "请问还有什么别的需求吗？" in result["output_speech"]


def test_non_key_success_reply_can_stay_standard_without_followup(monkeypatch) -> None:
    monkeypatch.setattr(response_manager.random, "random", lambda: 0.9)
    monkeypatch.setattr(response_manager.random, "choice", lambda values: values[0])
    manager = ResponseManager()

    result = manager.generate(
        "enable_schedule",
        "success",
        {"schedule_name": "春季作息"},
        prev_dialog_state=None,
    )

    assert "春季作息" in result["output_speech"]
    assert "安排好了" not in result["output_speech"]
    assert "搞定啦" not in result["output_speech"]
    assert "小电已经" not in result["output_speech"]
    assert "请问还有什么别的需求吗？" not in result["output_speech"]


def test_query_reply_can_use_light_persona_but_keeps_result_first(monkeypatch) -> None:
    monkeypatch.setattr(response_manager.random, "random", lambda: 0.1)
    monkeypatch.setattr(response_manager.random, "choice", lambda values: values[0])
    manager = ResponseManager()

    result = manager.generate(
        "query_task",
        "success",
        {},
        prev_dialog_state=None,
    )

    assert result["output_speech"].startswith("任务结果已经查到")
    assert "小电已经" in result["output_speech"]
    assert result["output_speech"].endswith("请问还有什么别的需求吗？")


def test_light_persona_reply_does_not_stack_completion_prefix(monkeypatch) -> None:
    monkeypatch.setattr(response_manager.random, "random", lambda: 0.1)
    monkeypatch.setattr(response_manager.random, "choice", lambda values: values[0])
    manager = ResponseManager()

    result = manager.generate(
        "create_schedule",
        "success",
        {"schedule_name": "春季作息"},
        prev_dialog_state="ask",
    )

    assert result["output_speech"].startswith("小电已经为您创建好了")
    assert not result["output_speech"].startswith("好，小电已经")


def test_missing_slot_reply_stays_professional_without_light_persona_tokens(monkeypatch) -> None:
    monkeypatch.setattr(response_manager.random, "choice", lambda values: values[0])
    manager = ResponseManager()

    result = manager.generate(
        "play_media",
        "incomplete",
        {},
        missing=["media_name"],
        prev_dialog_state=None,
    )

    assert "安排好了" not in result["output_speech"]
    assert "搞定啦" not in result["output_speech"]
    assert "小电已经" not in result["output_speech"]
