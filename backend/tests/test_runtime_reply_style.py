from backend.assistant.runtime_reply import ask_runtime, confirm_runtime, failure_runtime, query_runtime, success_runtime


def _find_persona_reply(generator, intent: str, variants: list[str], marker: str) -> str:
    for idx in range(200):
        reply = generator(intent, variants, f"{marker}-{idx}")
        if any(token in reply for token in ("小电", "安排好了", "搞定啦")):
            return reply
    raise AssertionError("expected at least one light-persona reply")


def test_failure_runtime_hides_raw_exception_style_prefixes() -> None:
    reply = failure_runtime(
        "sync_terminal_time",
        "终端校时",
        "右一终端",
        suggestion="这次没能完成终端校时，您稍后可以再试一次。",
    )

    assert "终端校时" in reply
    assert "HTTPException" not in reply
    assert "detail=" not in reply


def test_confirm_runtime_keeps_mode_confirmation_keywords() -> None:
    reply = confirm_runtime("move_schedule", "找到这些任务：07:50 早读开始铃")

    assert "请确认要一次性执行还是永久生效" in reply
    assert "找到这些任务" in reply or "结果如下" in reply or "查到这些内容" in reply
    assert "我先帮您定位到这些内容" not in reply


def test_runtime_reply_style_avoids_old_ai_phrases() -> None:
    reply = failure_runtime(
        "sync_terminal_time",
        "终端校时",
        "右一终端",
        reason="请求没有发出",
        suggestion="稍后可以再试一次。",
    )

    assert "这条我已经处理好了" not in reply
    assert "我先帮您" not in reply
    assert "我这边还没把" not in reply


def test_success_runtime_keeps_business_result_when_light_persona_is_used() -> None:
    reply = _find_persona_reply(
        success_runtime,
        "play_media",
        ['已在高三一班播放“国歌”，预计持续10分钟。'],
        "success",
    )

    assert "国歌" in reply
    assert "高三一班" in reply
    assert any(token in reply for token in ("小电已经为您", "小电已经帮您", "搞定啦"))


def test_query_runtime_keeps_result_first_when_light_persona_is_used() -> None:
    reply = _find_persona_reply(
        query_runtime,
        "query_task",
        ["已经查到 3 条任务。"],
        "query",
    )

    assert "3 条任务" in reply
    assert any(token in reply for token in ("小电已经", "查到了"))


def test_confirm_and_ask_runtime_stay_professional() -> None:
    confirm_reply = confirm_runtime("move_schedule", "已识别到这些任务：07:50 早读开始铃")
    ask_reply = ask_runtime("play_media", "要播放的媒体名称", example="比如播放国歌")

    for reply in (confirm_reply, ask_reply):
        assert "小电" not in reply
        assert "安排好了" not in reply
        assert "搞定啦" not in reply
        assert "巡视机房" not in reply
        assert "翻遍系统" not in reply
