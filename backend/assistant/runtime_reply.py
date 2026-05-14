"""Deterministic helpers for assistant runtime replies."""
from __future__ import annotations

from hashlib import sha1
from typing import Any, Iterable, Sequence

LIGHT_PERSONA_RATE_PERCENT = 25
STRONG_LIGHT_PERSONA_RATE_PERCENT = 100
DEFAULT_FOLLOWUP = "请问还有什么别的需求吗？"

HIGH_PERSONA_SUCCESS_INTENTS = {
    "create_schedule",
    "play_media",
    "adjust_volume",
    "adjust_volume_global",
    "adjust_volume_task",
    "adjust_volume_terminal",
}
HIGH_PERSONA_QUERY_INTENTS = {
    "query_task",
    "query_terminal",
}


def unique_texts(values: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def stable_reply(intent: str, variants: Sequence[str], *seed_parts: object, **kwargs: object) -> str:
    if not variants:
        raise ValueError("variants must not be empty")
    seed = "|".join(str(part or "").strip() for part in seed_parts)
    digest = sha1(f"{intent}|{seed}".encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % len(variants)
    return variants[index].format(**kwargs)


def stable_bucket(intent: str, *seed_parts: object) -> int:
    seed = "|".join(str(part or "").strip() for part in seed_parts)
    digest = sha1(f"{intent}|{seed}".encode("utf-8")).hexdigest()
    return int(digest[8:16], 16) % 100


def _base_intent_name(intent: str) -> str:
    return str(intent or "").split(":", 1)[0]


def _trim_terminal_punctuation(text: str) -> str:
    return str(text or "").strip().rstrip("。！？；，、,.!?;:")


def _finalize_sentence(text: str) -> str:
    stripped = str(text or "").strip()
    if not stripped:
        return ""
    if stripped[-1] in "。！？":
        return stripped
    return f"{stripped}。"


def _use_light_persona(intent: str, *seed_parts: object) -> bool:
    intent_name = _base_intent_name(intent)
    if intent.endswith(":success") and intent_name in HIGH_PERSONA_SUCCESS_INTENTS:
        threshold = STRONG_LIGHT_PERSONA_RATE_PERCENT
    elif intent.endswith(":query") and intent_name in HIGH_PERSONA_QUERY_INTENTS:
        threshold = STRONG_LIGHT_PERSONA_RATE_PERCENT
    else:
        threshold = LIGHT_PERSONA_RATE_PERCENT
    return stable_bucket(intent, *seed_parts) < threshold


def _light_success_reply(intent: str, base: str, *seed_parts: object) -> str:
    core = _trim_terminal_punctuation(base)
    if not core:
        return _finalize_sentence(base)
    if core.startswith(("小电已经", "搞定啦，小电已经", "安排好了，小电已经")):
        return _finalize_sentence(base)
    intent_name = _base_intent_name(intent)
    variants = [
        "安排好了，{core}。",
        "搞定啦，{core}。",
        "{core}。小电已经帮您处理好了。",
    ]
    if intent_name in HIGH_PERSONA_SUCCESS_INTENTS:
        variants = [
            "小电已经为您处理好了，{core}。",
            "小电已经帮您安排好了，{core}。",
            "搞定啦，小电已经为您处理好了，{core}。",
        ]
    return stable_reply(
        f"{intent}:success:light",
        variants,
        core,
        *seed_parts,
        core=core,
    )


def _light_query_reply(intent: str, base: str, *seed_parts: object) -> str:
    core = _trim_terminal_punctuation(base)
    if not core:
        return _finalize_sentence(base)
    if "小电已经" in core:
        return _finalize_sentence(base)
    intent_name = _base_intent_name(intent)
    variants = [
        "{core}。小电已经帮您整理好了。",
        "{core}，小电已经帮您查到了。",
        "{core}。小电这边已经为您查清楚了。",
    ]
    if intent_name in HIGH_PERSONA_QUERY_INTENTS:
        variants = [
            "{core}。小电已经帮您查到了。",
            "{core}。小电已经为您整理好了。",
            "{core}。小电这边已经帮您查清楚了。",
        ]
    return stable_reply(
        f"{intent}:query:light",
        variants,
        core,
        *seed_parts,
        core=core,
    )


def preview_names(values: Iterable[object], *, limit: int = 3, noun: str = "项") -> str:
    names = unique_texts(values)
    if not names:
        return ""
    if len(names) <= limit:
        return "、".join(names)
    return f"{'、'.join(names[:limit])}等{len(names)}{noun}"


def append_reply_details(main: str, *detail_lines: object) -> str:
    lines = [str(main or "").strip()]
    for line in detail_lines:
        text = str(line or "").strip()
        if text:
            lines.append(text)
    return "\n".join(line for line in lines if line)


def append_followup(reply: str, followup: str = DEFAULT_FOLLOWUP) -> str:
    main = _finalize_sentence(reply)
    extra = str(followup or "").strip()
    if not extra:
        return main
    if extra[-1] not in "。！？":
        extra = f"{extra}。"
    if main.endswith(extra):
        return main
    return f"{main} {extra}"


def success_runtime(intent: str, variants: Sequence[str], *seed_parts: object, **kwargs: object) -> str:
    base = stable_reply(intent, variants, *seed_parts, **kwargs)
    if _use_light_persona(f"{intent}:success", *seed_parts):
        return _light_success_reply(intent, base, *seed_parts)
    return _finalize_sentence(base)


def query_runtime(intent: str, variants: Sequence[str], *seed_parts: object, **kwargs: object) -> str:
    base = stable_reply(intent, variants, *seed_parts, **kwargs)
    if _use_light_persona(f"{intent}:query", *seed_parts):
        return _light_query_reply(intent, base, *seed_parts)
    return _finalize_sentence(base)


def confirm_runtime(
    intent: str,
    summary: str,
    *,
    question: str = "请确认要一次性执行还是永久生效？",
    **seed_kwargs: object,
) -> str:
    return stable_reply(
        f"{intent}:confirm",
        [
            "{summary}。{question}",
            "查到这些内容：{summary}。{question}",
            "结果如下：{summary}。{question}",
        ],
        summary,
        question,
        **seed_kwargs,
        summary=summary,
        question=question,
    )


def ask_runtime(
    intent: str,
    need: str,
    *,
    example: str = "",
    **seed_kwargs: object,
) -> str:
    base = stable_reply(
        f"{intent}:ask",
        [
            "还缺{need}。",
            "请补充{need}。",
            "要继续处理，请告诉我{need}。",
        ],
        need,
        example,
        **seed_kwargs,
        need=need,
        example=example,
    )
    if example:
        return append_reply_details(base, f"例如：{example}")
    return base


def failure_runtime(
    intent: str,
    topic: str,
    *seed_parts: object,
    reason: str = "",
    suggestion: str = "",
    **kwargs: object,
) -> str:
    variants = [
        "这次未完成{topic}。",
        "{topic}这次没有执行成功。",
        "这次未能完成{topic}处理。",
    ]
    if reason:
        variants = [
            "这次未完成{topic}，原因是{reason}。",
            "{topic}没有执行成功，原因是{reason}。",
            "这次未能完成{topic}处理，因为{reason}。",
        ]
    main = stable_reply(
        f"{intent}:failure",
        variants,
        topic,
        reason,
        *seed_parts,
        topic=topic,
        reason=reason,
        **kwargs,
    )
    if suggestion:
        return append_reply_details(main, suggestion)
    return main


def failure_detail_payload(
    raw_reason: object = None,
    *,
    user_reason: str = "",
    retryable: bool | None = None,
    failure_code: str = "",
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if raw_reason not in (None, ""):
        payload["failure_reason"] = raw_reason
    if user_reason:
        payload["user_reason"] = user_reason
    if retryable is not None:
        payload["retryable"] = retryable
    if failure_code:
        payload["failure_code"] = failure_code
    for key, value in extra.items():
        if value not in (None, "", [], {}):
            payload[key] = value
    return payload
