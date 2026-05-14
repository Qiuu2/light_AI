"""Assistant-layer chat and inference orchestration."""
from __future__ import annotations

from typing import List

from fastapi import HTTPException, Request

from backend.models import ChatResponse, InferRequest, InferResponse

from ._compat import api_public
from .dispatch import apply_action_for_assistant as apply_action

ASSISTANT_UNAVAILABLE_REPLY = "当前网络不稳定，请重新发送。"
PENDING_ACTION_DIALOG_STATE = "pending_action_followup"


def _module():
    return api_public()


def _sync_engine_followup_state(
    module,
    *,
    intent: str,
    slots: dict,
    missing_slots: List[str],
    dialog_state_detail: str = "ask_missing_slot",
) -> None:
    session = getattr(getattr(module, "ENGINE", None), "session", None)
    if session is None:
        return

    update = getattr(session, "update", None)
    if callable(update):
        update(
            intent,
            dict(slots or {}),
            [],
            "ask",
            "incomplete",
            list(missing_slots or []),
            dialog_state_detail,
        )
        return

    session.last_dialog_state = "ask"
    session.last_intent = intent
    session.pending_slots = dict(slots or {})
    session.pending_slots["__missing"] = list(missing_slots or [])


def _clear_engine_followup_state(module) -> None:
    session = getattr(getattr(module, "ENGINE", None), "session", None)
    if session is None:
        return

    clear_pending_dialog = getattr(session, "clear_pending_dialog", None)
    if callable(clear_pending_dialog):
        clear_pending_dialog()
        return

    session.last_dialog_state = None
    session.pending_slots = {}
    if hasattr(session, "interrupt_candidate"):
        session.interrupt_candidate = {}


def _controller_debug(module, controller: str, text: str) -> None:
    try:
        module.LOGGER.debug("Assistant controller=%s text=%s", controller, text)
    except Exception:
        pass


def _build_pending_action_response(
    module,
    *,
    text: str,
    action_reply,
) -> ChatResponse:
    reply, overrides, action_log = action_reply
    overrides = dict(overrides or {})
    pending_action = module._snapshot_pending_action()
    diagnostics = list(overrides.get("diagnostics") or []) if isinstance(overrides.get("diagnostics"), list) else []
    dialog_state_detail = overrides.get("dialog_state_detail")
    if not dialog_state_detail:
        dialog_state_detail = PENDING_ACTION_DIALOG_STATE if pending_action else "complete"
    _controller_debug(module, "pending_action", text)
    return ChatResponse(
        reply=reply,
        output_speech=reply,
        intent=str(overrides.get("intent") or ""),
        confidence=float(overrides.get("confidence", 1.0)),
        slots=dict(overrides.get("slots") or {}),
        missing_slots=list(overrides.get("missing_slots") or []),
        dialog_state_detail=dialog_state_detail,
        raw_entities=dict(overrides.get("raw_entities") or {}),
        tokens=list(overrides.get("tokens") or []),
        tags=list(overrides.get("tags") or []),
        action_log=action_log,
        diagnostics=diagnostics,
        pending_action=pending_action,
    )


def _build_unavailable_response(
    module,
    *,
    result: dict | None = None,
    missing_slots: List[str] | None = None,
    dialog_state_detail: str | None = None,
    pending_scope: str = "",
) -> ChatResponse:
    result = dict(result or {})
    effective_detail = str(dialog_state_detail or "").strip() or "complete"
    pending_action = (
        module._snapshot_pending_action(pending_scope)
        if pending_scope
        else module._snapshot_pending_action()
    )
    return ChatResponse(
        reply=ASSISTANT_UNAVAILABLE_REPLY,
        output_speech=ASSISTANT_UNAVAILABLE_REPLY,
        intent=str(result.get("intent") or ""),
        confidence=float(result.get("intent_confidence", 0.0) or 0.0),
        slots=dict(result.get("slots") or {}),
        missing_slots=list(missing_slots or []),
        dialog_state_detail=effective_detail,
        raw_entities=dict(result.get("entities") or {}),
        tokens=list(result.get("tokens") or []),
        tags=list(result.get("tag_ids") or []),
        action_log=[],
        diagnostics=[],
        pending_action=pending_action,
    )


def infer(payload: InferRequest) -> InferResponse:
    module = _module()
    result = module.ENGINE.infer(payload.text)
    missing = result.get("missing_slots") or []
    output_speech = result.get("output_speech")
    return InferResponse(
        intent=result.get("intent", ""),
        confidence=float(result.get("intent_confidence", 0.0)),
        slots=result.get("slots", {}),
        missing_slots=missing,
        dialog_state_detail=result.get("dialog_state_detail"),
        raw_entities=result.get("entities", {}),
        tokens=result.get("tokens", []),
        tags=result.get("tag_ids", []),
        output_speech=output_speech,
        message=output_speech,
    )


def infer_api(payload: InferRequest) -> InferResponse:
    return infer(payload)


async def chat(request: Request) -> ChatResponse:
    module = _module()
    text = await module._extract_text_from_request(request)
    if not text:
        raise HTTPException(status_code=400, detail="Missing text in request body.")

    local_session = getattr(request.state, "local_session", None)
    reset_pending_scope = None
    reset_remote_token = None
    reset_remote_base_url = None
    if isinstance(local_session, dict):
        pending_scope = str(local_session.get("token") or "").strip()
        remote_token = module._normalize_remote_access_token(local_session.get("remote_token"))
        remote_base_url = module._normalize_remote_base_url(local_session.get("remote_base_url"))
        if pending_scope:
            reset_pending_scope = module._set_current_pending_scope(pending_scope)
        if remote_token:
            reset_remote_token = module.CURRENT_REMOTE_TOKEN.set(remote_token)
        if remote_base_url:
            reset_remote_base_url = module.CURRENT_REMOTE_BASE_URL.set(remote_base_url)
    else:
        pending_scope = ""

    result: dict = {}
    missing: List[str] = []
    dialog_state_detail: str | None = None
    try:
        session = getattr(getattr(module, "ENGINE", None), "session", None)
        session_dialog_state = str(getattr(session, "last_dialog_state", "") or "")
        pending_before = module._snapshot_pending_action(pending_scope) if pending_scope else None
        if pending_before and session_dialog_state != "interrupt_confirm":
            try:
                action_reply = module._handle_pending_action_for_scope(text, pending_scope)
            except HTTPException as exc:
                if exc.status_code < 500:
                    raise
                module.LOGGER.warning("Assistant pending_action failed with HTTP %s: %s", exc.status_code, exc.detail)
                return _build_unavailable_response(
                    module,
                    result=result,
                    missing_slots=missing,
                    dialog_state_detail=dialog_state_detail,
                    pending_scope=pending_scope,
                )
            except Exception as exc:
                module.LOGGER.exception("Assistant pending_action failed unexpectedly: %s", exc)
                return _build_unavailable_response(
                    module,
                    result=result,
                    missing_slots=missing,
                    dialog_state_detail=dialog_state_detail,
                    pending_scope=pending_scope,
                )
            if action_reply:
                if session_dialog_state in {"ask", "interrupt_confirm"}:
                    _clear_engine_followup_state(module)
                return _build_pending_action_response(module, text=text, action_reply=action_reply)

        result = module.ENGINE.infer(text)
        missing = result.get("missing_slots") or []
        output_speech = result.get("output_speech")
        reply = output_speech or ""
        action_log: List[dict] = []
        diagnostics: List[dict] = []
        dialog_state_detail = result.get("dialog_state_detail")
        should_skip_action = (
            result.get("dialog_state") == "interrupt_confirm"
            or dialog_state_detail == "confirm_interrupt_switch"
        )
        if should_skip_action:
            _controller_debug(module, "interrupt_confirm", text)
        elif dialog_state_detail == "ask_missing_slot":
            _controller_debug(module, "session_followup", text)

        try:
            action_reply = None
            if not should_skip_action:
                action_reply = module._handle_pending_action_for_scope(text, pending_scope) if pending_scope else None
            if not action_reply and not should_skip_action:
                action_reply = apply_action(text, result)
        except HTTPException as exc:
            if exc.status_code < 500:
                raise
            module.LOGGER.warning("Assistant chat apply_action failed with HTTP %s: %s", exc.status_code, exc.detail)
            return _build_unavailable_response(
                module,
                result=result,
                missing_slots=missing,
                dialog_state_detail=dialog_state_detail,
                pending_scope=pending_scope,
            )
        except Exception as exc:
            module.LOGGER.exception("Assistant chat apply_action failed unexpectedly: %s", exc)
            return _build_unavailable_response(
                module,
                result=result,
                missing_slots=missing,
                dialog_state_detail=dialog_state_detail,
                pending_scope=pending_scope,
            )

        if action_reply:
            reply, overrides, action_log = action_reply
            output_speech = reply
            if overrides:
                override_dialog_state_detail = str(overrides.get("dialog_state_detail") or "").strip()
                if "intent" in overrides:
                    result["intent"] = overrides["intent"]
                if "confidence" in overrides:
                    result["intent_confidence"] = float(overrides["confidence"])
                if "slots" in overrides:
                    result["slots"] = overrides["slots"]
                if "raw_entities" in overrides:
                    result["entities"] = overrides["raw_entities"]
                if "tokens" in overrides:
                    result["tokens"] = list(overrides.get("tokens") or [])
                if "tags" in overrides:
                    result["tag_ids"] = list(overrides.get("tags") or [])
                if "missing_slots" in overrides:
                    missing = list(overrides.get("missing_slots") or [])
                if override_dialog_state_detail:
                    dialog_state_detail = override_dialog_state_detail
                if isinstance(overrides.get("diagnostics"), list):
                    diagnostics = list(overrides.get("diagnostics") or [])
                if overrides.get("missing_slots"):
                    current_pending_action = (
                        module._snapshot_pending_action(pending_scope)
                        if pending_scope
                        else module._snapshot_pending_action()
                    )
                    if current_pending_action:
                        _clear_engine_followup_state(module)
                        dialog_state_detail = PENDING_ACTION_DIALOG_STATE
                    else:
                        _clear_engine_followup_state(module)
                        dialog_state_detail = override_dialog_state_detail or "ask_missing_slot"
                        _sync_engine_followup_state(
                            module,
                            intent=result.get("intent", ""),
                            slots=result.get("slots", {}),
                            missing_slots=missing,
                            dialog_state_detail=dialog_state_detail,
                        )
                        module.LOGGER.debug(
                            "Backend ask state synced: intent=%s, missing=%s",
                            result.get("intent"),
                            missing,
                        )
                else:
                    current_pending_action = (
                        module._snapshot_pending_action(pending_scope)
                        if pending_scope
                        else module._snapshot_pending_action()
                    )
                    if current_pending_action:
                        if dialog_state_detail is None:
                            dialog_state_detail = PENDING_ACTION_DIALOG_STATE
                    else:
                        _clear_engine_followup_state(module)
                        dialog_state_detail = "complete"

        if action_log:
            try:
                module._append_assistant_command_log(text=text, reply=reply, action_log=action_log)
            except Exception as exc:  # pragma: no cover - persistence should not break chat
                module.LOGGER.warning("Failed to persist assistant command log: %s", exc)

        pending_action = None if dialog_state_detail == "confirm_interrupt_switch" else module._snapshot_pending_action()
        return ChatResponse(
            reply=reply,
            output_speech=output_speech,
            intent=result.get("intent", ""),
            confidence=float(result.get("intent_confidence", 0.0)),
            slots=result.get("slots", {}),
            missing_slots=missing,
            dialog_state_detail=dialog_state_detail,
            raw_entities=result.get("entities", {}),
            tokens=result.get("tokens", []),
            tags=result.get("tag_ids", []),
            action_log=action_log,
            diagnostics=diagnostics,
            pending_action=pending_action,
        )
    except HTTPException as exc:
        if exc.status_code < 500:
            raise
        module.LOGGER.warning("Assistant chat failed with HTTP %s: %s", exc.status_code, exc.detail)
        return _build_unavailable_response(
            module,
            result=result,
            missing_slots=missing,
            dialog_state_detail=dialog_state_detail,
            pending_scope=pending_scope,
        )
    except Exception as exc:
        module.LOGGER.exception("Assistant chat failed unexpectedly: %s", exc)
        return _build_unavailable_response(
            module,
            result=result,
            missing_slots=missing,
            dialog_state_detail=dialog_state_detail,
            pending_scope=pending_scope,
        )
    finally:
        if reset_pending_scope is not None:
            module._reset_current_pending_scope(reset_pending_scope)
        if reset_remote_token is not None:
            module.CURRENT_REMOTE_TOKEN.reset(reset_remote_token)
        if reset_remote_base_url is not None:
            module.CURRENT_REMOTE_BASE_URL.reset(reset_remote_base_url)


async def chat_api(request: Request) -> ChatResponse:
    return await chat(request)


__all__ = ["chat", "chat_api", "infer", "infer_api"]
