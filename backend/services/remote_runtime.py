"""Shared remote base URL resolution and remote settings helpers."""
from __future__ import annotations

import ipaddress
import json
import sys
import urllib.parse
from contextvars import ContextVar
from typing import Optional, Tuple

from fastapi import HTTPException

from backend.config import DATA_DIR, REMOTE_BASE_URL as CONFIG_REMOTE_BASE_URL
from backend.services.data_store import read_json_optional, write_json

REMOTE_SETTINGS_PATH = DATA_DIR / "remote_settings.json"
CURRENT_REMOTE_BASE_URL: ContextVar[Optional[str]] = ContextVar(
    "current_remote_base_url",
    default=None,
)


def _default_remote_settings_payload() -> dict:
    return {
        "remote_base_url": "",
        "last_verified_at": "",
        "last_verified_ip": "",
        "excluded_candidate_ips": [],
    }


def _clone_payload(payload: object) -> object:
    try:
        return json.loads(json.dumps(payload, ensure_ascii=False))
    except Exception:
        return payload


def normalize_remote_base_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="remote_base_url must be a valid http(s) URL.")
    normalized_path = parsed.path.rstrip("/")
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, normalized_path, "", "", "")).rstrip("/")


def normalize_remote_settings_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        payload = {}
    remote_base_url = normalize_remote_base_url(payload.get("remote_base_url"))
    last_verified_at = str(payload.get("last_verified_at") or "").strip()
    last_verified_ip = str(payload.get("last_verified_ip") or "").strip()
    raw_excluded_candidate_ips = payload.get("excluded_candidate_ips")
    excluded_candidate_ips = []
    if isinstance(raw_excluded_candidate_ips, list):
        for item in raw_excluded_candidate_ips:
            ip_text = str(item or "").strip()
            if not ip_text:
                continue
            try:
                parsed = ipaddress.ip_address(ip_text)
            except ValueError:
                continue
            if parsed.version != 4:
                continue
            normalized_ip = str(parsed)
            if normalized_ip not in excluded_candidate_ips:
                excluded_candidate_ips.append(normalized_ip)
    return {
        "remote_base_url": remote_base_url,
        "last_verified_at": last_verified_at,
        "last_verified_ip": last_verified_ip,
        "excluded_candidate_ips": excluded_candidate_ips,
    }


def _api_public_module():
    return sys.modules.get("backend.api_public")


def _environment_remote_base_url_value() -> str:
    module = _api_public_module()
    if module is not None and hasattr(module, "REMOTE_BASE_URL"):
        return str(getattr(module, "REMOTE_BASE_URL") or "")
    return str(CONFIG_REMOTE_BASE_URL or "")


def load_remote_settings_payload() -> dict:
    module = _api_public_module()
    if module is not None and hasattr(module, "_store_get") and hasattr(module, "_store_set"):
        payload = module._store_get("remote_settings")
        if payload is None:
            payload = _default_remote_settings_payload()
            module._store_set("remote_settings", payload)
        return normalize_remote_settings_payload(payload)
    payload = read_json_optional(REMOTE_SETTINGS_PATH)
    if payload is None:
        payload = _default_remote_settings_payload()
    return normalize_remote_settings_payload(payload)


def save_remote_settings_payload(payload: dict) -> dict:
    normalized = normalize_remote_settings_payload(payload)
    module = _api_public_module()
    if module is not None and hasattr(module, "_store_set"):
        path = getattr(module, "REMOTE_SETTINGS_PATH", REMOTE_SETTINGS_PATH)
        writer = getattr(module, "_write_json", write_json)
        writer(path, normalized)
        module._store_set("remote_settings", normalized)
        return normalized
    write_json(REMOTE_SETTINGS_PATH, normalized)
    return normalized


def resolved_saved_remote_base_url() -> str:
    payload = load_remote_settings_payload()
    return normalize_remote_base_url(payload.get("remote_base_url"))


def current_request_remote_base_url() -> Optional[str]:
    value = CURRENT_REMOTE_BASE_URL.get()
    if not value:
        return None
    return normalize_remote_base_url(value)


def resolve_remote_base_url(explicit: object = None) -> str:
    resolved, _ = resolve_remote_base_url_details(explicit)
    return resolved


def resolve_remote_base_url_details(explicit: object = None) -> Tuple[str, str]:
    explicit_text = str(explicit or "").strip()
    if explicit_text:
        return normalize_remote_base_url(explicit_text), "explicit"
    current = current_request_remote_base_url()
    if current:
        return current, "session"
    saved = resolved_saved_remote_base_url()
    if saved:
        return saved, "saved"
    environment = normalize_remote_base_url(_environment_remote_base_url_value())
    if environment:
        return environment, "environment"
    return "", "none"


def remote_settings_response_payload(payload: Optional[dict] = None) -> dict:
    normalized = normalize_remote_settings_payload(payload or load_remote_settings_payload())
    return {
        "remote_base_url": normalized.get("remote_base_url") or "",
        "last_verified_at": normalized.get("last_verified_at") or "",
        "last_verified_ip": normalized.get("last_verified_ip") or "",
        "excluded_candidate_ips": _clone_payload(normalized.get("excluded_candidate_ips") or []),
        "effective_remote_base_url": resolve_remote_base_url(),
        "environment_remote_base_url": normalize_remote_base_url(_environment_remote_base_url_value()),
    }
