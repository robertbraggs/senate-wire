from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SECRET_PARAM_NAMES = {
    "api_key",
    "apikey",
    "key",
    "token",
    "access_token",
    "auth",
    "authorization",
    "password",
    "secret",
}

_SECRET_LABEL_RE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|token|access[_-]?token|authorization|password|secret)\b\s*[:=]\s*[^\s&\"']+"
)


def configured_secret_values() -> list[str]:
    values: list[str] = []
    for name, value in os.environ.items():
        upper = name.upper()
        if any(marker in upper for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD")) and value:
            values.append(value)
    return sorted(set(values), key=len, reverse=True)


def sanitize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(str(url))
        query = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if key.lower() in SECRET_PARAM_NAMES:
                query.append((key, "[redacted]"))
            else:
                query.append((key, value))
        sanitized = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    except Exception:
        sanitized = str(url)
    return redact_secrets(sanitized)


def redact_secrets(value: str) -> str:
    text = str(value or "")
    text = _SECRET_LABEL_RE.sub(lambda m: f"{m.group(1)}=[redacted]", text)
    for secret in configured_secret_values():
        if len(secret) >= 4:
            text = text.replace(secret, "[redacted]")
    return text


def sanitize_error_message(error: Any) -> str:
    text = redact_secrets(str(error or "source fetch failed"))
    text = sanitize_url(text)
    lower = text.lower()
    if "timed out" in lower or "timeout" in lower:
        return "upstream timeout"
    if "status code" in lower or "httpstatuserror" in lower or re.search(r"\b[45]\d\d\b", text):
        return "upstream HTTP error"
    if "connect" in lower or "network" in lower or "dns" in lower:
        return "upstream connection error"
    if "json" in lower:
        return "upstream response parse error"
    if not text.strip():
        return "source fetch failed"
    return text[:240]


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: sanitize_payload(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_payload(v) for v in value]
    if isinstance(value, str):
        return sanitize_url(value) if value.startswith(("http://", "https://")) else redact_secrets(value)
    return value
