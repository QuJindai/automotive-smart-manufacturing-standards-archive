from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TransportBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpEvidence:
    method: str
    url: str
    status: int
    body_text: str
    json_body: Any
    headers: dict[str, str]


def encode_identifier(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def request(method: str, url: str, body: bytes | dict | None = None, headers: dict[str, str] | None = None, timeout: float = 10.0) -> HttpEvidence:
    headers = dict(headers or {})
    data: bytes | None
    if isinstance(body, dict):
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    else:
        data = body
    req = Request(url, data=data, method=method.upper(), headers=headers)
    try:
        resp = urlopen(req, timeout=timeout)
        raw = resp.read()
        status = resp.status
        resp_headers = {k: v for k, v in resp.headers.items()}
    except HTTPError as exc:
        raw = exc.read()
        status = exc.code
        resp_headers = {k: v for k, v in exc.headers.items()} if exc.headers else {}
    except (URLError, TimeoutError, OSError) as exc:
        raise TransportBlocked(f"{method} {url}: {exc}") from exc
    text = raw.decode("utf-8", errors="replace")[:16384]
    try:
        obj = json.loads(text) if text else None
    except json.JSONDecodeError:
        obj = None
    return HttpEvidence(method.upper(), url, int(status), text, obj, resp_headers)
