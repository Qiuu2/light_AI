from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.session_manager import SessionState, resolve_with_session


def _ask_session() -> SessionState:
    session = SessionState()
    session.last_intent = "play_media"
    session.last_dialog_state = "ask"
    session.pending_slots = {"__missing": ["media_name"]}
    session.last_update = time.time()
    return session


def test_name_followup_with_business_tokens_stays_followup() -> None:
    session = _ask_session()

    resolution = resolve_with_session(session, "none", {}, "播放测试广播", None)

    assert resolution is not None
    assert resolution.kind == "followup"
    assert resolution.intent == "play_media"
    assert resolution.slots == {"media_name": "播放测试广播"}
