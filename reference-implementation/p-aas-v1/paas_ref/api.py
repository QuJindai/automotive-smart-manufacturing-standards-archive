from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request


class TransportError(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpResult:
    status: int
    json: Any
    text: str
    headers: dict[str, str]


def request_json(method: str, url: str, body: Any = None, token: str | None = None, timeout: float = 5.0) -> HttpResult:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url=url, data=data, method=method.upper(), headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
            response_headers = dict(resp.headers.items())
    except error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
        response_headers = dict(exc.headers.items()) if exc.headers else {}
    except (error.URLError, TimeoutError, OSError) as exc:
        raise TransportError(str(exc)) from exc
    text = raw.decode("utf-8", errors="replace")[:4096]
    parsed = None
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
    return HttpResult(status=status, json=parsed, text=text, headers=response_headers)
