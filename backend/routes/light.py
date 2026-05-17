"""Lightweight broadcast proxy routes for the Hangtian Guangdian action API."""
from __future__ import annotations

import json
import http.cookiejar
import os
import threading
import uuid
import urllib.parse
import urllib.request
from typing import Any
from urllib.error import HTTPError, URLError

from fastapi import APIRouter, Body, HTTPException

from backend.services.remote_runtime import current_request_remote_base_url, resolved_saved_remote_base_url


LIGHT_REMOTE_BASE_URL = os.getenv("LIGHT_REMOTE_BASE_URL", "http://192.168.1.88").rstrip("/")
LIGHT_REMOTE_TIMEOUT = float(os.getenv("LIGHT_REMOTE_TIMEOUT", "15"))
LIGHT_REMOTE_USERNAME = os.getenv("LIGHT_REMOTE_USERNAME", "useradmin")
LIGHT_REMOTE_PASSWORD = os.getenv("LIGHT_REMOTE_PASSWORD", "123456")
LIGHT_REMOTE_AUTO_LOGIN = os.getenv("LIGHT_REMOTE_AUTO_LOGIN", "1") == "1"
_DEFAULT_COOKIE_JAR = http.cookiejar.CookieJar()
_DEFAULT_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_DEFAULT_COOKIE_JAR))
_COOKIE_JAR = _DEFAULT_COOKIE_JAR
_OPENER = _DEFAULT_OPENER
_COOKIE_JARS_BY_BASE_URL: dict[str, http.cookiejar.CookieJar] = {}
_OPENERS_BY_BASE_URL: dict[str, urllib.request.OpenerDirector] = {}
_OPENER_LOCK = threading.Lock()
_LOGIN_LOCK = threading.Lock()
LIGHT_DEFAULT_SCHEME_COUNT = int(os.getenv("LIGHT_DEFAULT_SCHEME_COUNT", "8"))
_ACTION_REMOTE_BASE_URL = ""
_ACTION_REMOTE_CREDENTIALS_BY_BASE_URL: dict[str, tuple[str, str]] = {}
_ACTION_SESSION_COOKIE_NAME = "-goahead-session-"
_RAW_PREVIEW_LIMIT = 500


def _compact_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    compact: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        if isinstance(value, list) and not value:
            continue
        compact[str(key)] = value
    return compact


def _resolve_light_remote_base_url(explicit: object = None) -> tuple[str, str]:
    explicit_text = str(explicit or "").strip().rstrip("/")
    if explicit_text:
        return explicit_text, "explicit"
    current = current_request_remote_base_url()
    if current:
        return current.rstrip("/"), "session"
    saved = resolved_saved_remote_base_url()
    if saved:
        return saved.rstrip("/"), "saved"
    if _ACTION_REMOTE_BASE_URL:
        return _ACTION_REMOTE_BASE_URL.rstrip("/"), "action"
    return LIGHT_REMOTE_BASE_URL.rstrip("/"), "environment"


def _remote_url_details(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    remote_base_url: object = None,
) -> tuple[str, str, str]:
    remote_base_url, source = _resolve_light_remote_base_url(remote_base_url)
    if not remote_base_url:
        raise HTTPException(status_code=500, detail="LIGHT_REMOTE_BASE_URL is not configured.")
    url = f"{remote_base_url}{path if path.startswith('/') else '/' + path}"
    query = _compact_payload(params)
    if query:
        url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"
    return url, remote_base_url, source


def _remote_url(path: str, params: dict[str, Any] | None = None) -> str:
    url, _, _ = _remote_url_details(path, params)
    return url


def _decode_remote_response(raw_bytes: bytes) -> tuple[Any, str]:
    raw = raw_bytes.decode("utf-8", errors="ignore")
    text = raw.strip()
    if not text:
        return None, raw
    if text.startswith(("{", "[")):
        try:
            return json.loads(text), raw
        except json.JSONDecodeError:
            return None, raw
    return None, raw


def _looks_like_html_response(raw: str) -> bool:
    text = str(raw or "").strip().lower()
    if not text:
        return False
    return (
        text.startswith("<!doctype")
        or text.startswith("<html")
        or "<html" in text[:512]
        or "</html>" in text
    )


def _remote_html_kind(raw: str) -> str:
    text = str(raw or "")
    lowered = text.lower()
    if not _looks_like_html_response(text):
        return "not_html"

    login_score = 0
    for marker in (
        'id="realform"',
        "id='realform'",
        "/action/login",
        "dhxform",
        "qrcode",
        "qrcodes",
        "serpwd",
        'name: "password"',
        "name: 'password'",
        'name="password"',
        "name='password'",
        "login page",
    ):
        if marker in lowered:
            login_score += 1
    if login_score >= 2 or ("login page" in lowered and "password" in lowered):
        return "login_page"

    app_score = 0
    for marker in (
        "dhtmlxlayoutobject",
        "status.asp",
        "attachaccordion",
        "attachsidebar",
        "/action/updatemenupage",
        "sidebar_item_",
    ):
        if marker in lowered:
            app_score += 1
    if app_score >= 2:
        return "app_shell"

    return "other_html"


def _looks_like_login_page_response(raw: str) -> bool:
    return _remote_html_kind(raw) == "login_page"


def _looks_like_app_shell_response(raw: str) -> bool:
    return _remote_html_kind(raw) == "app_shell"


def _redact_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(str(url or ""))
    query_items = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    redacted_query = urllib.parse.urlencode(
        [(key, "***" if key.lower() in {"password", "pwd"} else value) for key, value in query_items],
        doseq=True,
    )
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, redacted_query, parsed.fragment))


def _raw_preview(raw: object) -> str:
    text = str(raw or "")
    if len(text) > _RAW_PREVIEW_LIMIT:
        return text[:_RAW_PREVIEW_LIMIT]
    return text


def _headers_to_dict(headers: object) -> dict[str, str]:
    if headers is None:
        return {}
    try:
        return {str(key): str(value) for key, value in headers.items()}
    except Exception:
        return {}


def _header_value(headers: object, name: str) -> str:
    if headers is None:
        return ""
    try:
        value = headers.get(name)
    except Exception:
        value = None
    if value is None:
        header_map = _headers_to_dict(headers)
        for key, item in header_map.items():
            if key.lower() == name.lower():
                return str(item or "")
        return ""
    return str(value or "")


def _response_headers(resp: object) -> object:
    try:
        return resp.info()
    except Exception:
        return getattr(resp, "headers", None)


def _response_status(resp: object) -> int:
    for attr in ("status", "code"):
        value = getattr(resp, attr, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    getcode = getattr(resp, "getcode", None)
    if callable(getcode):
        try:
            return int(getcode())
        except (TypeError, ValueError):
            pass
    return 0


def _response_url(resp: object, fallback: str) -> str:
    geturl = getattr(resp, "geturl", None)
    if callable(geturl):
        try:
            return str(geturl() or fallback)
        except Exception:
            return fallback
    return fallback


def _cookie_domain_matches(cookie: http.cookiejar.Cookie, host: str) -> bool:
    cookie_domain = str(getattr(cookie, "domain", "") or "").lstrip(".").lower()
    host = str(host or "").lower()
    if not cookie_domain:
        return True
    return host == cookie_domain or host.endswith("." + cookie_domain)


def _cookies_for_base_url(cookie_jar: http.cookiejar.CookieJar, remote_base_url: str) -> list[http.cookiejar.Cookie]:
    host = urllib.parse.urlparse(str(remote_base_url or "")).hostname or ""
    if not host:
        return []
    return [cookie for cookie in cookie_jar if _cookie_domain_matches(cookie, host)]


def _cookie_snapshot(cookie_jar: http.cookiejar.CookieJar, remote_base_url: str) -> dict[str, Any]:
    cookies = _cookies_for_base_url(cookie_jar, remote_base_url)
    names = []
    for cookie in cookies:
        name = str(getattr(cookie, "name", "") or "")
        if name and name not in names:
            names.append(name)
    return {
        "count": len(cookies),
        "names": names,
        "has_action_session": _ACTION_SESSION_COOKIE_NAME in names,
    }


def _action_session_cookie_values(cookie_jar: http.cookiejar.CookieJar, remote_base_url: str) -> list[str]:
    return [
        str(getattr(cookie, "value", "") or "")
        for cookie in _cookies_for_base_url(cookie_jar, remote_base_url)
        if str(getattr(cookie, "name", "") or "") == _ACTION_SESSION_COOKIE_NAME
    ]


def _set_cookie_has_action_session(headers: object) -> bool:
    return _ACTION_SESSION_COOKIE_NAME in _header_value(headers, "Set-Cookie")


def _get_remote_cookie_state(remote_base_url: str) -> tuple[urllib.request.OpenerDirector, http.cookiejar.CookieJar]:
    if _OPENER is not _DEFAULT_OPENER:
        return _OPENER, _COOKIE_JAR
    key = str(remote_base_url or "").rstrip("/")
    with _OPENER_LOCK:
        cookie_jar = _COOKIE_JARS_BY_BASE_URL.get(key)
        opener = _OPENERS_BY_BASE_URL.get(key)
        if cookie_jar is None or opener is None:
            cookie_jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
            _COOKIE_JARS_BY_BASE_URL[key] = cookie_jar
            _OPENERS_BY_BASE_URL[key] = opener
        return opener, cookie_jar


def _action_diagnostic(
    *,
    phase: str,
    method: str,
    path: str,
    url: str,
    remote_base_url: str,
    remote_base_url_source: str,
    body_mode: str,
    cookie_jar: http.cookiejar.CookieJar,
    response: object = None,
    raw: object = "",
    error: object = "",
    status_code: int | None = None,
) -> dict[str, Any]:
    headers = _response_headers(response) if response is not None else None
    status = _response_status(response) if response is not None else status_code
    content_type = _header_value(headers, "Content-Type")
    set_cookie = _header_value(headers, "Set-Cookie")
    raw_text = str(raw or "")
    html_kind = _remote_html_kind(raw_text)
    return {
        "phase": str(phase or ""),
        "method": str(method or "").upper(),
        "path": str(path or ""),
        "url": _redact_url(url),
        "remote_base_url": str(remote_base_url or ""),
        "remote_base_url_source": str(remote_base_url_source or ""),
        "body_mode": str(body_mode or ""),
        "status_code": status,
        "content_type": content_type,
        "response_url": _redact_url(_response_url(response, url)) if response is not None else "",
        "html_like": _looks_like_html_response(raw_text),
        "html_kind": html_kind,
        "login_page_like": html_kind == "login_page",
        "app_shell_like": html_kind == "app_shell",
        "raw_preview": _raw_preview(raw_text),
        "set_cookie_present": bool(set_cookie),
        "set_cookie_has_action_session": _ACTION_SESSION_COOKIE_NAME in set_cookie,
        "cookies": _cookie_snapshot(cookie_jar, remote_base_url),
        "error": str(error or ""),
    }


def _rows_from_payload(payload: Any) -> list[Any]:
    if isinstance(payload, dict):
        if isinstance(payload.get("rows"), list):
            return payload["rows"]
        data = payload.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            return data["rows"]
    if isinstance(payload, list):
        return payload
    return []


def _tree_leaf_options(payload: Any, *, value_prefix: str = "") -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        children = node.get("item")
        if isinstance(children, list) and children:
            for child in children:
                walk(child)
            return
        node_id = node.get("id") or node.get("value") or node.get("code")
        label = node.get("text") or node.get("name") or node.get("label") or node_id
        if node_id in (None, ""):
            return
        raw_value = str(node_id).strip()
        if not raw_value or raw_value.startswith("dir_"):
            return
        value = raw_value if not value_prefix or raw_value.startswith(("1_", "2_")) else f"{value_prefix}{raw_value}"
        options.append(
            {
                "id": raw_value,
                "value": value,
                "label": str(label).strip() or raw_value,
                "raw": node,
            }
        )

    walk(payload)
    return options


def _terminal_id_response_options(response: dict[str, Any]) -> list[dict[str, Any]]:
    data = response.get("data")
    if data is not None:
        options = _tree_leaf_options(data, value_prefix="2_")
        if options:
            return options
        rows = _rows_from_payload(data)
        if rows:
            return _tree_leaf_options(rows, value_prefix="2_")
    raw = str(response.get("raw") or "").strip()
    if not raw:
        return []
    ids = [item.strip() for item in raw.replace("\r", "\n").replace(",", "\n").split("\n") if item.strip()]
    return [
        {
            "id": item,
            "value": item if item.startswith(("1_", "2_")) else f"2_{item}",
            "label": item,
            "raw": item,
        }
        for item in ids
    ]


def _unique_options(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for option in options:
        value = str(option.get("value") or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(option)
    return unique


def _group_options_from_payload(payload: Any) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for option in _tree_leaf_options(payload, value_prefix="1_"):
        item = dict(option)
        item["kind"] = "group"
        options.append(item)
    for row in _rows_from_payload(payload):
        if not isinstance(row, dict):
            continue
        group_id = _group_id_from_row(row)
        if not group_id:
            continue
        label = row.get("name") or row.get("groupname") or row.get("text") or row.get("label") or group_id
        options.append(
            {
                "id": group_id,
                "value": group_id if group_id.startswith(("1_", "2_")) else f"1_{group_id}",
                "label": str(label).strip() or group_id,
                "raw": row,
                "kind": "group",
            }
        )
    return _unique_options(options)


def _group_id_from_row(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    value = row.get("id") or row.get("groupid") or row.get("group_id")
    return "" if value in (None, "") else str(value)


def _task_info_row_from_payload(payload: Any, task_id: str) -> dict[str, Any] | None:
    target = str(task_id or "").strip()
    for row in _rows_from_payload(payload):
        if not isinstance(row, dict):
            continue
        row_id = row.get("id") or row.get("taskid") or row.get("task_id")
        if str(row_id or "").strip() == target:
            return row
    return None


def _split_hms(value: object) -> tuple[str, str, str]:
    parts = str(value or "").strip().split(":")
    if len(parts) >= 3:
        return parts[0] or "0", parts[1] or "0", parts[2] or "0"
    if len(parts) == 2:
        return parts[0] or "0", parts[1] or "0", "0"
    return "0", "0", "0"


def _normalized_taskinfo_detail(row: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(row, dict):
        return {}
    detail: dict[str, str] = {}
    direct_fields = {
        "taskname": row.get("taskname"),
        "volume": row.get("volume"),
        "random": row.get("rand") if row.get("rand") is not None else row.get("random"),
        "pretime": row.get("Pre-Start") if row.get("Pre-Start") is not None else row.get("pretime"),
        "delaytime": row.get("Pre-Stop") if row.get("Pre-Stop") is not None else row.get("delaytime"),
    }
    for key, value in direct_fields.items():
        if value not in (None, ""):
            detail[key] = str(value)

    if row.get("enable") not in (None, ""):
        detail["enableordis"] = "0" if str(row.get("enable")) == "1" else "1"

    if row.get("playtime") not in (None, ""):
        detail["time"] = str(row.get("playtime"))
        playhour, playminute, playsecond = _split_hms(row.get("playtime"))
        detail["playhour"] = playhour
        detail["playminute"] = playminute
        detail["playsecond"] = playsecond

    if row.get("playlength") not in (None, ""):
        timehour, timeminute, timesecond = _split_hms(row.get("playlength"))
        detail["timehour"] = timehour
        detail["timeminute"] = timeminute
        detail["timesecond"] = timesecond

    for index, key in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun")):
        if row.get(key) not in (None, ""):
            detail[f"day{index}"] = str(row.get(key))

    area = str(row.get("area") or "").strip()
    if area:
        for index, value in enumerate(area[:8]):
            detail[f"area{index}"] = value
    return detail


def _scheme_from_row(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    scheme_id = row.get("id") or row.get("scheme_id") or row.get("program_id")
    if scheme_id in (None, ""):
        return None
    name = row.get("name") or row.get("programname") or row.get("sechename") or f"方案{scheme_id}"
    return {
        "id": str(scheme_id),
        "name": str(name),
        "raw": row,
    }


def _task_from_program_row(row: Any, scheme: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {
            "program_id": scheme["id"],
            "program_name": scheme["name"],
            "raw": row,
        }
    task_id = row.get("taskid") or row.get("task_id") or row.get("id")
    data = row.get("data") if isinstance(row.get("data"), list) else []
    task: dict[str, Any] = {
        **row,
        "id": task_id,
        "taskid": task_id,
        "program_id": scheme["id"],
        "program_name": scheme["name"],
        "raw": row,
    }
    if data:
        task.update(
            {
                "taskname": row.get("taskname") or (data[0] if len(data) > 0 else ""),
                "playtime": row.get("playtime") or (data[1] if len(data) > 1 else ""),
                "duration": row.get("duration") or (data[2] if len(data) > 2 else ""),
                "volume": row.get("volume") or (data[4] if len(data) > 4 else ""),
                "pretime": row.get("pretime") or (data[13] if len(data) > 13 else ""),
                "delaytime": row.get("delaytime") or (data[14] if len(data) > 14 else ""),
            }
        )
    return task


def _multipart_form_data(payload: dict[str, Any]) -> tuple[bytes, str]:
    boundary = f"----LightAiSpeaker{uuid.uuid4().hex}"
    lines: list[bytes] = []
    for key, value in payload.items():
        values = value if isinstance(value, list) else [value]
        for item in values:
            lines.append(f"--{boundary}".encode("utf-8"))
            safe_key = str(key).replace('"', "%22")
            lines.append(f'Content-Disposition: form-data; name="{safe_key}"'.encode("utf-8"))
            lines.append(b"")
            lines.append(str(item).encode("utf-8"))
    lines.append(f"--{boundary}--".encode("utf-8"))
    lines.append(b"")
    return b"\r\n".join(lines), boundary


def _probe_action_session(
    opener: urllib.request.OpenerDirector,
    cookie_jar: http.cookiejar.CookieJar,
    remote_base_url: str,
    *,
    phase: str = "business_probe",
) -> tuple[bool, list[dict[str, Any]]]:
    probe_path = "/action/getmedia"
    url, resolved_remote_base_url, remote_base_url_source = _remote_url_details(
        probe_path,
        remote_base_url=remote_base_url,
    )
    req = urllib.request.Request(url, data=None, method="POST", headers={"Accept": "application/json"})
    try:
        with opener.open(req, timeout=LIGHT_REMOTE_TIMEOUT) as resp:
            _, raw = _decode_remote_response(resp.read())
            diagnostic = _action_diagnostic(
                phase=phase,
                method="POST",
                path=probe_path,
                url=url,
                remote_base_url=resolved_remote_base_url,
                remote_base_url_source=remote_base_url_source,
                body_mode="none",
                cookie_jar=cookie_jar,
                response=resp,
                raw=raw,
            )
            success = bool(_response_status(resp) == 200 and not _looks_like_login_page_response(raw))
            return success, [diagnostic]
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else str(exc)
        return False, [
            _action_diagnostic(
                phase=phase,
                method="POST",
                path=probe_path,
                url=url,
                remote_base_url=resolved_remote_base_url,
                remote_base_url_source=remote_base_url_source,
                body_mode="none",
                cookie_jar=cookie_jar,
                raw=detail,
                error=f"HTTP {exc.code}",
                status_code=int(exc.code),
            )
        ]
    except (TimeoutError, URLError) as exc:
        return False, [
            _action_diagnostic(
                phase=phase,
                method="POST",
                path=probe_path,
                url=url,
                remote_base_url=resolved_remote_base_url,
                remote_base_url_source=remote_base_url_source,
                body_mode="none",
                cookie_jar=cookie_jar,
                raw="",
                error=f"Remote request failed: {exc}",
            )
        ]


def _login_attempt_requests(
    remote_base_url: str,
    username: str,
    password: str,
) -> list[dict[str, Any]]:
    credentials = {"username": username, "password": password}
    query_url, _, _ = _remote_url_details(
        "/action/login",
        params=credentials,
        remote_base_url=remote_base_url,
    )
    form_url, _, _ = _remote_url_details(
        "/action/login",
        params={},
        remote_base_url=remote_base_url,
    )
    form_body = urllib.parse.urlencode(credentials, doseq=True).encode("utf-8")
    return [
        {
            "mode": "post_query",
            "method": "POST",
            "url": query_url,
            "data": None,
            "headers": {"Accept": "application/json"},
            "body_mode": "none",
        },
        {
            "mode": "get_query",
            "method": "GET",
            "url": query_url,
            "data": None,
            "headers": {"Accept": "application/json"},
            "body_mode": "none",
        },
        {
            "mode": "post_urlencoded",
            "method": "POST",
            "url": form_url,
            "data": form_body,
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            "body_mode": "urlencoded",
        },
    ]


def action_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    form: dict[str, Any] | None = None,
    body_mode: str = "multipart",
    allow_login_retry: bool = True,
    diagnostics: list[dict[str, Any]] | None = None,
    phase: str = "initial",
) -> dict[str, Any]:
    if diagnostics is None:
        diagnostics = []
    url, remote_base_url, remote_base_url_source = _remote_url_details(path, params)
    opener, cookie_jar = _get_remote_cookie_state(remote_base_url)
    body = _compact_payload(form)
    data = None
    headers = {"Accept": "application/json"}
    normalized_body_mode = str(body_mode or "none").strip().lower()
    if normalized_body_mode not in {"multipart", "urlencoded", "none"}:
        raise HTTPException(status_code=500, detail=f"Unsupported light remote body mode: {body_mode}")
    if method.upper() in {"POST", "PUT", "DELETE"} and body and normalized_body_mode != "none":
        if normalized_body_mode == "urlencoded":
            data = urllib.parse.urlencode(body, doseq=True).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data, boundary = _multipart_form_data(body)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
    try:
        with opener.open(req, timeout=LIGHT_REMOTE_TIMEOUT) as resp:
            parsed, raw = _decode_remote_response(resp.read())
            diagnostics.append(
                _action_diagnostic(
                    phase=phase,
                    method=method,
                    path=path,
                    url=url,
                    remote_base_url=remote_base_url,
                    remote_base_url_source=remote_base_url_source,
                    body_mode=normalized_body_mode,
                    cookie_jar=cookie_jar,
                    response=resp,
                    raw=raw,
                )
            )
            if _looks_like_login_page_response(raw):
                if allow_login_retry:
                    relogin_resp = light_login(force=True, remote_base_url=remote_base_url)
                    diagnostics.extend(list(relogin_resp.get("diagnostics") or []))
                    if relogin_resp.get("success") is False:
                        return {
                            "success": False,
                            "message": f"Remote session appears expired and re-login failed: {relogin_resp.get('message') or 'unknown error'}",
                            "data": None,
                            "raw": raw,
                            "diagnostics": diagnostics,
                        }
                    retry_resp = action_request(
                        method,
                        path,
                        params=params,
                        form=form,
                        body_mode=body_mode,
                        allow_login_retry=False,
                        diagnostics=diagnostics,
                        phase="retry_after_relogin",
                    )
                    if retry_resp.get("success") is False and _looks_like_login_page_response(str(retry_resp.get("raw") or "")):
                        return {
                            "success": False,
                            "message": "Remote session appears expired; re-login succeeded but business API still returned login page.",
                            "data": None,
                            "raw": retry_resp.get("raw") or raw,
                            "diagnostics": diagnostics,
                        }
                    return retry_resp
                return {
                    "success": False,
                    "message": "Remote session appears expired; business API returned login page after retry handling was disabled.",
                    "data": None,
                    "raw": raw,
                    "diagnostics": diagnostics,
                }
            return {
                "success": True,
                "message": "ok",
                "data": parsed,
                "raw": raw,
                "diagnostics": diagnostics,
            }
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else str(exc)
        diagnostics.append(
            _action_diagnostic(
                phase=phase,
                method=method,
                path=path,
                url=url,
                remote_base_url=remote_base_url,
                remote_base_url_source=remote_base_url_source,
                body_mode=normalized_body_mode,
                cookie_jar=cookie_jar,
                raw=detail,
                error=f"HTTP {exc.code}",
                status_code=int(exc.code),
            )
        )
        if allow_login_retry and exc.code in {401, 403} and LIGHT_REMOTE_AUTO_LOGIN:
            relogin_resp = light_login(force=True, remote_base_url=remote_base_url)
            diagnostics.extend(list(relogin_resp.get("diagnostics") or []))
            if relogin_resp.get("success") is False:
                return {
                    "success": False,
                    "message": f"Remote authorization failed and re-login failed: {relogin_resp.get('message') or 'unknown error'}",
                    "data": None,
                    "raw": detail,
                    "diagnostics": diagnostics,
                }
            return action_request(
                method,
                path,
                params=params,
                form=form,
                body_mode=body_mode,
                allow_login_retry=False,
                diagnostics=diagnostics,
                phase="retry_after_relogin",
            )
        return {
            "success": False,
            "message": detail or f"Remote HTTP {exc.code}",
            "data": None,
            "raw": detail,
            "diagnostics": diagnostics,
        }
    except (URLError, TimeoutError) as exc:
        # TimeoutError covers socket-level read timeouts (Python 3.10+ alias of
        # socket.timeout), which urllib's URLError does NOT subclass — without
        # this branch every remote read timeout would bubble up as a 500.
        diagnostics.append({
            "phase": phase,
            "method": method,
            "path": path,
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
        })
        return {
            "success": False,
            "message": f"Remote connection failed: {exc}",
            "data": None,
            "raw": str(exc),
            "diagnostics": diagnostics,
        }


def light_login(
    force: bool = False,
    *,
    remote_base_url: object = None,
    username: object = None,
    password: object = None,
) -> dict[str, Any]:
    url, resolved_remote_base_url, remote_base_url_source = _remote_url_details(
        "/action/login",
        params={},
        remote_base_url=remote_base_url,
    )
    stored_credentials = _ACTION_REMOTE_CREDENTIALS_BY_BASE_URL.get(resolved_remote_base_url)
    username_text = str(username if username is not None else (stored_credentials[0] if stored_credentials else LIGHT_REMOTE_USERNAME) or "").strip()
    password_text = str(password if password is not None else (stored_credentials[1] if stored_credentials else LIGHT_REMOTE_PASSWORD) or "")
    diagnostics: list[dict[str, Any]] = []
    if not username_text or not password_text:
        return {"success": False, "message": "light remote credentials are missing", "data": None, "raw": ""}
    opener, cookie_jar = _get_remote_cookie_state(resolved_remote_base_url)
    with _LOGIN_LOCK:
        last_raw = ""
        last_error = ""
        for attempt in _login_attempt_requests(resolved_remote_base_url, username_text, password_text):
            before_cookies = _cookie_snapshot(cookie_jar, resolved_remote_base_url)
            before_cookie_values = _action_session_cookie_values(cookie_jar, resolved_remote_base_url)
            url = str(attempt["url"])
            req = urllib.request.Request(
                url,
                data=attempt["data"],
                method=str(attempt["method"]),
                headers=dict(attempt["headers"]),
            )
            try:
                with opener.open(req, timeout=LIGHT_REMOTE_TIMEOUT) as resp:
                    raw = resp.read().decode("utf-8", errors="ignore")
                    last_raw = raw
                    last_error = ""
                    after_cookies = _cookie_snapshot(cookie_jar, resolved_remote_base_url)
                    after_cookie_values = _action_session_cookie_values(cookie_jar, resolved_remote_base_url)
                    cookie_changed = before_cookie_values != after_cookie_values
                    diagnostics.append(
                        _action_diagnostic(
                            phase="relogin" if force else "login",
                            method=str(attempt["method"]),
                            path="/action/login",
                            url=url,
                            remote_base_url=resolved_remote_base_url,
                            remote_base_url_source=remote_base_url_source,
                            body_mode=str(attempt["body_mode"]),
                            cookie_jar=cookie_jar,
                            response=resp,
                            raw=raw,
                        )
                    )
                    login_diagnostic = diagnostics[-1]
                    login_diagnostic["login_attempt_mode"] = str(attempt["mode"])
                    login_diagnostic["cookies_before"] = before_cookies
                    login_diagnostic["cookies_after"] = after_cookies
                    login_diagnostic["cookie_changed"] = bool(cookie_changed)
                    login_diagnostic["business_probe_attempted"] = False
                    login_diagnostic["business_probe_success"] = False
                    login_diagnostic["business_probe_path"] = ""
                    if _response_status(resp) == 200:
                        if _looks_like_app_shell_response(raw):
                            return {
                                "success": True,
                                "message": "ok",
                                "data": None,
                                "raw": raw,
                                "diagnostics": diagnostics,
                            }
                        login_diagnostic["business_probe_attempted"] = True
                        login_diagnostic["business_probe_path"] = "/action/getmedia"
                        probe_success, probe_diagnostics = _probe_action_session(
                            opener,
                            cookie_jar,
                            resolved_remote_base_url,
                        )
                        diagnostics.extend(probe_diagnostics)
                        login_diagnostic["business_probe_success"] = bool(probe_success)
                        if probe_success:
                            return {
                                "success": True,
                                "message": "ok",
                                "data": None,
                                "raw": raw,
                                "diagnostics": diagnostics,
                            }
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else str(exc)
                last_raw = detail
                last_error = detail or f"Remote HTTP {exc.code}"
                diagnostics.append(
                    _action_diagnostic(
                        phase="relogin" if force else "login",
                        method=str(attempt["method"]),
                        path="/action/login",
                        url=url,
                        remote_base_url=resolved_remote_base_url,
                        remote_base_url_source=remote_base_url_source,
                        body_mode=str(attempt["body_mode"]),
                        cookie_jar=cookie_jar,
                        raw=detail,
                        error=f"HTTP {exc.code}",
                        status_code=int(exc.code),
                    )
                )
                diagnostics[-1]["login_attempt_mode"] = str(attempt["mode"])
            except URLError as exc:
                last_error = f"Remote request failed: {exc}"
                diagnostics.append(
                    _action_diagnostic(
                        phase="relogin" if force else "login",
                        method=str(attempt["method"]),
                        path="/action/login",
                        url=url,
                        remote_base_url=resolved_remote_base_url,
                        remote_base_url_source=remote_base_url_source,
                        body_mode=str(attempt["body_mode"]),
                        cookie_jar=cookie_jar,
                        raw="",
                        error=last_error,
                    )
                )
                diagnostics[-1]["login_attempt_mode"] = str(attempt["mode"])
        return {
            "success": False,
            "message": last_error or "Remote login completed but business probe still returned login page.",
            "data": None,
            "raw": last_raw,
            "diagnostics": diagnostics,
        }


def login_with_credentials(remote_base_url: str, username: str, password: str) -> dict[str, Any]:
    global _ACTION_REMOTE_BASE_URL
    _ACTION_REMOTE_BASE_URL = str(remote_base_url or "").rstrip("/")
    _ACTION_REMOTE_CREDENTIALS_BY_BASE_URL[_ACTION_REMOTE_BASE_URL] = (
        str(username or "").strip(),
        str(password or ""),
    )
    return light_login(
        force=True,
        remote_base_url=_ACTION_REMOTE_BASE_URL,
        username=username,
        password=password,
    )


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/light", tags=["light"])

    @router.post("/login")
    def login():
        return light_login(force=True)

    @router.get("/resources")
    def get_resources():
        # Swagger also exposes /action/basicparameters, but no current UI flow consumes it.
        media = action_request("POST", "/action/getmedia")
        terminal = action_request("POST", "/action/getterminal")
        groups = action_request("POST", "/action/getextgroup", body_mode="none")
        basic = action_request("POST", "/action/getbasicinfo")
        failed = [
            name
            for name, response in (("media", media), ("terminal", terminal), ("groups", groups), ("basic", basic))
            if response.get("success") is False
        ]
        terminal_options = _tree_leaf_options(terminal.get("data"), value_prefix="2_")
        group_options = _group_options_from_payload(groups.get("data"))
        return {
            "success": not failed,
            "message": "ok" if not failed else f"Failed to load light resources: {', '.join(failed)}",
            "data": {
                "media": media.get("data"),
                "terminal": terminal.get("data"),
                "groups": groups.get("data"),
                "basic": basic.get("data"),
                "media_options": _tree_leaf_options(media.get("data")),
                "terminal_options": _unique_options(terminal_options + group_options),
                "group_options": group_options,
            },
            "parts": {
                "media": {"success": media.get("success"), "message": media.get("message")},
                "terminal": {"success": terminal.get("success"), "message": terminal.get("message")},
                "groups": {"success": groups.get("success"), "message": groups.get("message")},
                "basic": {"success": basic.get("success"), "message": basic.get("message")},
            },
            "raw": {
                "media": media.get("raw"),
                "terminal": terminal.get("raw"),
                "groups": groups.get("raw"),
                "basic": basic.get("raw"),
            },
        }

    @router.get("/terminals")
    def get_terminals():
        return action_request("POST", "/action/getterminal", body_mode="none")

    @router.get("/terminal-groups")
    def get_terminal_groups():
        return action_request("POST", "/action/getextgroup", body_mode="none")

    @router.get("/terminal-groups/{group_id}/terminals")
    def get_terminal_group_terminals(group_id: str):
        response = action_request(
            "POST",
            "/action/getterminalid",
            form={"groupid": group_id},
            body_mode="multipart",
        )
        if response.get("success") is False:
            return response
        options = _terminal_id_response_options(response)
        return {
            "success": True,
            "message": response.get("message") or "ok",
            "data": options,
            "raw": response.get("raw"),
        }

    @router.get("/terminal-snapshot")
    def get_terminal_snapshot():
        groups = action_request("POST", "/action/getextgroup", body_mode="none")
        terminals = action_request("POST", "/action/getterminal", body_mode="none")

        zone_terminals: dict[str, dict[str, Any]] = {}
        raw_zone_terminals: dict[str, str | None] = {}
        failed_groups: list[str] = []
        for row in _rows_from_payload(groups.get("data")):
            group_id = _group_id_from_row(row)
            if not group_id:
                continue
            response = action_request(
                "POST",
                "/action/getterminalid",
                form={"groupid": group_id},
                body_mode="multipart",
            )
            if response.get("success") is False:
                zone_terminals[group_id] = response
            else:
                zone_terminals[group_id] = {
                    "success": True,
                    "message": response.get("message") or "ok",
                    "data": _terminal_id_response_options(response),
                    "raw": response.get("raw"),
                }
            raw_zone_terminals[group_id] = response.get("raw")
            if response.get("success") is False:
                failed_groups.append(group_id)

        failed_parts = []
        if groups.get("success") is False:
            failed_parts.append("terminal-groups")
        if terminals.get("success") is False:
            failed_parts.append("terminals")
        if failed_groups:
            failed_parts.append(f"group-terminals({', '.join(failed_groups)})")

        return {
            "success": not failed_parts,
            "message": "ok" if not failed_parts else f"Failed to load terminal snapshot: {', '.join(failed_parts)}",
            "zones": groups,
            "zone_terminals": zone_terminals,
            "terminal_info": terminals,
            "raw": {
                "zones": groups.get("raw"),
                "terminal_info": terminals.get("raw"),
                "zone_terminals": raw_zone_terminals,
            },
        }

    @router.get("/schedules")
    def get_schedules():
        schemes_resp = action_request("POST", "/action/getallsech", body_mode="none")
        if schemes_resp.get("success") is False:
            return schemes_resp

        raw_schemes = _rows_from_payload(schemes_resp.get("data"))
        schemes: list[dict[str, Any]] = []
        raw_tasks_by_scheme: dict[str, Any] = {}

        for raw_scheme in raw_schemes:
            scheme = _scheme_from_row(raw_scheme)
            if not scheme:
                continue
            schemes.append(scheme)
        for scheme in schemes:
            tasks_resp = action_request(
                "POST",
                "/action/opensech",
                params={"id": scheme["id"]},
                body_mode="none",
            )
            raw_tasks_by_scheme[scheme["id"]] = {
                "success": tasks_resp.get("success"),
                "data": tasks_resp.get("data"),
                "raw": tasks_resp.get("raw"),
            }
            task_rows = _rows_from_payload(tasks_resp.get("data")) if tasks_resp.get("success") is not False else []
            scheme["tasks"] = [_task_from_program_row(row, scheme) for row in task_rows]
            scheme["task_success"] = tasks_resp.get("success") is not False
            if tasks_resp.get("success") is False:
                scheme["task_error"] = tasks_resp.get("message") or "opensech failed"

        return {
            "success": True,
            "message": "ok",
            "data": {"schemes": schemes},
            "raw": {
                "schemes": schemes_resp.get("raw"),
                "tasks_by_scheme": raw_tasks_by_scheme,
            },
        }

    @router.get("/current-schedule-tasks")
    def get_current_schedule_tasks():
        response = action_request("POST", "/action/gettaskinfo", body_mode="none")
        if response.get("success") is False:
            return response
        current_scheme = {"id": "", "name": "当前启用作息", "raw": {}}
        task_rows = _rows_from_payload(response.get("data"))
        return {
            "success": True,
            "message": "ok",
            "data": {"tasks": [_task_from_program_row(row, current_scheme) for row in task_rows]},
            "raw": response.get("raw"),
        }

    @router.post("/schedules/{program_id}/tasks")
    def add_task(program_id: str, payload: dict[str, Any] = Body(default_factory=dict)):
        return action_request("POST", "/action/addtask", params={"id": program_id}, form=payload, body_mode="urlencoded")

    @router.post("/schedules/{program_id}/activate")
    def activate_schedule(program_id: str):
        return action_request("POST", "/action/activeprogram", form={"id": program_id}, body_mode="urlencoded")

    @router.put("/schedules/{program_id}/name")
    def rename_schedule(program_id: str, payload: dict[str, Any] = Body(default_factory=dict)):
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        return action_request(
            "POST",
            "/action/saveprogramname",
            form={"id": program_id, "name": name},
            body_mode="urlencoded",
        )

    # Field order matches the swagger curl sample for modifytask/addtask exactly.
    # Some old embedded webservers parse positional / buffered fields and silently
    # drop fields that arrive after a certain point, so we always reorder.
    _MODIFYTASK_FIELD_ORDER = (
        "media", "terminal", "taskname",
        "playhour", "playminute", "playsecond", "playmode",
        "timehour", "timeminute", "timesecond", "times",
        "volume", "enableordis",
        "area0", "area1", "area2", "area3", "area4", "area5", "area6", "area7",
        "workmode",
        "day0", "day1", "day2", "day3", "day4", "day5", "day6",
        "pretime", "delaytime", "random",
    )

    def _order_modifytask_payload(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        ordered: dict[str, Any] = {}
        for key in _MODIFYTASK_FIELD_ORDER:
            if key in payload:
                ordered[key] = payload[key]
        for key, value in payload.items():
            if key not in ordered:
                ordered[key] = value
        return ordered

    @router.put("/tasks/{task_id}")
    def update_task(task_id: str, payload: dict[str, Any] = Body(default_factory=dict)):
        ordered = _order_modifytask_payload(payload)
        return action_request(
            "POST", "/action/modifytask",
            params={"taskid": task_id}, form=ordered, body_mode="urlencoded",
        )

    @router.delete("/tasks/{task_id}")
    def delete_task(task_id: str):
        return action_request("POST", "/action/deletetask", form={"taskid": task_id}, body_mode="multipart")

    @router.get("/tasks")
    def get_tasks():
        return action_request("POST", "/action/getquicktask", body_mode="none")

    @router.get("/tasks/{task_id}/details")
    def get_task_details(task_id: str):
        media = action_request("POST", "/action/gettaskmedia", form={"taskid": task_id}, body_mode="urlencoded")
        terminal = action_request("POST", "/action/gettaskterminal", form={"taskid": task_id}, body_mode="urlencoded")
        area = action_request("GET", "/action/gettaskarea", params={"taskid": task_id}, body_mode="none")

        # Fast path: gettaskinfo 只返回"当前启用方案"的任务。
        taskinfo = action_request("POST", "/action/gettaskinfo", body_mode="none")
        taskinfo_row = _task_info_row_from_payload(taskinfo.get("data"), task_id) if taskinfo.get("success") is not False else None

        # Fallback: 如果当前启用方案里没匹配，遍历所有方案用 opensech 找。
        # 这覆盖了"用户编辑的不是当前启用方案的任务"这种常见场景。
        if taskinfo_row is None:
            try:
                schemes_resp = action_request("POST", "/action/getallsech", body_mode="none")
                if schemes_resp.get("success") is not False:
                    for scheme in _rows_from_payload(schemes_resp.get("data")):
                        if not isinstance(scheme, dict):
                            continue
                        scheme_id = str(scheme.get("id") or scheme.get("secheid") or "").strip()
                        if not scheme_id:
                            continue
                        tasks_resp = action_request(
                            "POST", "/action/opensech",
                            params={"id": scheme_id}, body_mode="none",
                        )
                        if tasks_resp.get("success") is False:
                            continue
                        hit = _task_info_row_from_payload(tasks_resp.get("data"), task_id)
                        if hit:
                            taskinfo_row = hit
                            break
            except Exception:
                pass

        taskinfo_detail = _normalized_taskinfo_detail(taskinfo_row)
        taskinfo_payload = {
            "detail": taskinfo_detail,
            "row": taskinfo_row,
        }
        # taskinfo is optional: /action/gettaskinfo only returns rows for the
        # currently-activated schedule, so editing a task in another schedule
        # will legitimately produce an empty match. Never count it as failure.
        detail_map = {
            "media": media,
            "terminal": terminal,
            "area": area,
            "taskinfo": taskinfo,
        }
        required = ("media", "terminal", "area")
        failed = [name for name in required if detail_map[name].get("success") is False]
        def _csv_ids(resp: dict[str, Any]) -> list[str]:
            data = resp.get("data")
            if isinstance(data, list):
                return [str(item).strip() for item in data if str(item).strip()]
            raw_text = str(resp.get("raw") or "").strip()
            if not raw_text:
                return []
            return [part.strip() for part in raw_text.split(",") if part.strip()]

        media_ids = _csv_ids(media)
        terminal_ids = _csv_ids(terminal)

        return {
            "success": not failed,
            "message": "ok" if not failed else f"Failed to load task detail: {', '.join(failed)}",
            "data": {
                "media": media_ids,
                "terminal": terminal_ids,
                "area": area.get("data"),
                "taskinfo": taskinfo_payload,
            },
            "raw": {name: resp.get("raw") for name, resp in detail_map.items()},
        }

    @router.post("/tasks/{task_id}/execute")
    def execute_task(task_id: str):
        return action_request("POST", "/action/taskstart", form={"taskid": task_id}, body_mode="urlencoded")

    @router.post("/tasks/{task_id}/stop")
    def stop_task(task_id: str):
        return action_request("POST", "/action/taskstop", form={"taskid": task_id}, body_mode="urlencoded")

    @router.post("/instant-play")
    def instant_play(payload: dict[str, Any] = Body(default_factory=dict)):
        form = _compact_payload(payload)
        if not form.get("media"):
            form.pop("media", None)
        response = action_request("POST", "/action/executetmptask", form=form, body_mode="urlencoded")
        if response.get("success"):
            try:
                from backend import api_public

                api_public._record_light_instant_play_runtime_entry(form, response)
            except Exception:
                pass
        return response

    @router.post("/instant-play/stop")
    def stop_instant_play():
        response = action_request("POST", "/action/stoptmptask", body_mode="none")
        if response.get("success"):
            try:
                from backend import api_public

                api_public._mark_recent_light_instant_play_entries_stopped()
            except Exception:
                pass
        return response

    @router.post("/system-volume")
    def set_system_volume(payload: dict[str, Any] = Body(default_factory=dict)):
        volume = payload.get("volume")
        try:
            volume_value = int(str(volume).strip())
        except (TypeError, ValueError):
            return {"success": False, "message": "volume must be an integer between 0 and 100", "data": None, "raw": ""}
        if volume_value < 0 or volume_value > 100:
            return {"success": False, "message": "volume must be between 0 and 100", "data": None, "raw": ""}
        return action_request(
            "POST",
            "/action/setvolume",
            form={"volume": str(volume_value)},
            body_mode="multipart",
        )

    return router
