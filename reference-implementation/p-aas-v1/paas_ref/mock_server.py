from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from .jws import sign_compact
from .policy import evaluate_abac
from .sample import SampleBundle


@dataclass
class RunningServer:
    base_url: str
    _server: ThreadingHTTPServer
    _thread: threading.Thread

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


class ReferenceServer:
    def __init__(self, sample: SampleBundle, secret: bytes):
        self.sample = sample
        self.secret = secret
        self.resources: dict[str, dict] = {"existing-resource": {"value": 0}}

    def start(self) -> RunningServer:
        sample = self.sample
        secret = self.secret
        resources = self.resources

        class Handler(BaseHTTPRequestHandler):
            server_version = "PAASReference/1.0"

            def log_message(self, fmt: str, *args) -> None:
                return

            def _path(self) -> str:
                return urlsplit(self.path).path

            def _token(self) -> str | None:
                value = self.headers.get("Authorization")
                if not value or not value.startswith("Bearer "):
                    return None
                return value[7:]

            def _read_json(self) -> dict | None:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    raw = self.rfile.read(length) if length else b""
                    value = json.loads(raw.decode("utf-8")) if raw else {}
                    return value if isinstance(value, dict) else None
                except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                    return None

            def _json(self, status: int, payload: dict) -> None:
                raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self) -> None:
                path = self._path()
                body = self._read_json()
                if body is None:
                    self._json(400, {"error": "invalid_json"})
                    return
                if path == "/query":
                    if set(body) != {"idShort"} or not isinstance(body.get("idShort"), str):
                        self._json(400, {"error": "invalid_query_schema"})
                        return
                    matches = [x for x in sample.environment["submodels"] if x.get("idShort") == body["idShort"]]
                    self._json(200, {"results": matches})
                    return
                if path == "/authorize":
                    if not all(isinstance(body.get(k), dict) for k in ("subject", "resource", "context")):
                        self._json(400, {"error": "invalid_authorization_request"})
                        return
                    decision = evaluate_abac(body["subject"], body["resource"], body["context"])
                    self._json(200, {"allowed": decision.allowed, "reason_code": decision.reason_code, "attributes": decision.attributes})
                    return
                self._json(404, {"error": "not_found"})

            def do_GET(self) -> None:
                path = self._path()
                if path.startswith("/shells/"):
                    identifier = unquote(path[len("/shells/"):])
                    if identifier == sample.aas_id:
                        self._json(200, sample.aas)
                    else:
                        self._json(404, {"error": "aas_not_found"})
                    return
                if path.startswith("/submodels/"):
                    identifier = unquote(path[len("/submodels/"):])
                    target = next((x for x in sample.environment["submodels"] if x.get("id") == identifier), None)
                    self._json(200, target) if target is not None else self._json(404, {"error": "submodel_not_found"})
                    return
                if path == "/protected":
                    token = self._token()
                    if token is None:
                        self._json(401, {"error": "unauthorized"})
                    elif token != "reader-token":
                        self._json(403, {"error": "forbidden"})
                    else:
                        self._json(200, {"protected": True})
                    return
                if path.startswith("/signed/"):
                    identifier = unquote(path[len("/signed/"):])
                    if identifier != sample.aas_id:
                        self._json(404, {"error": "aas_not_found"})
                        return
                    payload = json.dumps(sample.aas, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    self._json(200, {"jws": sign_compact(payload, secret)})
                    return
                self._json(404, {"error": "not_found"})

            def do_PUT(self) -> None:
                path = self._path()
                if not path.startswith("/resources/"):
                    self._json(404, {"error": "not_found"})
                    return
                token = self._token()
                if token is None:
                    self._json(401, {"error": "unauthorized"})
                    return
                body = self._read_json()
                if body is None:
                    self._json(400, {"error": "invalid_json"})
                    return
                identifier = unquote(path[len("/resources/"):])
                exists = identifier in resources
                if not exists:
                    if token != "create-token":
                        self._json(403, {"error": "forbidden"})
                        return
                    resources[identifier] = body
                    self._json(201, {"id": identifier, "created": True})
                    return
                if token != "update-token":
                    self._json(403, {"error": "forbidden"})
                    return
                resources[identifier] = body
                self._json(200, {"id": identifier, "updated": True})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, name="paas-reference-server", daemon=True)
        thread.start()
        host, port = server.server_address
        return RunningServer(base_url=f"http://{host}:{port}", _server=server, _thread=thread)
