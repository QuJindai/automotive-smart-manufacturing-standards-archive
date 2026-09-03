import hashlib
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.download_executor import run_job


STATIC_BODY = b"static-payload-for-direct-drive"


class DownloadFixture:
    def __init__(self):
        self.dynamic_probe_bodies: list[bytes] = []
        self.dynamic_full_bodies: list[bytes] = []
        self.static_gets = 0
        self.uploaded = bytearray()
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format, *args):
                return

            def _finish_empty(self, status: int, **headers: str):
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name.replace("_", "-"), value)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_HEAD(self):
                if self.path == "/static":
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(STATIC_BODY)))
                    self.end_headers()
                    return
                if self.path == "/dynamic":
                    self.send_response(200)
                    self.end_headers()
                    return
                self._finish_empty(404)

            def do_GET(self):
                if self.path == "/static":
                    fixture.static_gets += 1
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(STATIC_BODY)))
                    self.end_headers()
                    self.wfile.write(STATIC_BODY)
                    return
                if self.path == "/dynamic":
                    request_number = len(fixture.dynamic_probe_bodies) + len(fixture.dynamic_full_bodies) + 1
                    body = json.dumps(
                        {"request_id": request_number, "items": ["alpha", "beta"]},
                        separators=(",", ":"),
                    ).encode("utf-8")
                    if self.headers.get("Range"):
                        fixture.dynamic_probe_bodies.append(body)
                    else:
                        fixture.dynamic_full_bodies.append(body)
                    self.send_response(200)
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    midpoint = len(body) // 2
                    try:
                        for chunk in (body[:midpoint], body[midpoint:]):
                            self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii"))
                            self.wfile.write(chunk + b"\r\n")
                        self.wfile.write(b"0\r\n\r\n")
                    except OSError:
                        # Size probing deliberately closes a 200/chunked body early.
                        pass
                    return
                self._finish_empty(404)

            def do_PUT(self):
                content_range = self.headers.get("Content-Range", "")
                if content_range.startswith("bytes */"):
                    headers = {}
                    if fixture.uploaded:
                        headers["Range"] = f"bytes=0-{len(fixture.uploaded) - 1}"
                    self._finish_empty(308, **headers)
                    return

                length = int(self.headers.get("Content-Length", "0"))
                chunk = self.rfile.read(length)
                start = int(content_range.split(" ", 1)[1].split("-", 1)[0])
                total = int(content_range.rsplit("/", 1)[1])
                if start != len(fixture.uploaded):
                    self._finish_empty(409)
                    return
                fixture.uploaded.extend(chunk)
                if len(fixture.uploaded) < total:
                    self._finish_empty(308, Range=f"bytes=0-{len(fixture.uploaded) - 1}")
                    return

                response = json.dumps(
                    {
                        "id": "drive-fixture",
                        "name": "download.bin",
                        "size": str(len(fixture.uploaded)),
                        "webViewLink": "https://drive.example/drive-fixture",
                    },
                    separators=(",", ":"),
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.server.server_port}{path}"


class StreamingSourceRegressionTests(unittest.TestCase):
    def test_unknown_length_dynamic_source_uploads_the_verified_snapshot(self):
        with DownloadFixture() as fixture, TemporaryDirectory() as out_dir:
            job = {
                "download_id": "download-dynamic",
                "upload_sessions": {"asset-1": fixture.url("/upload")},
                "assets": [
                    {
                        "asset_id": "asset-1",
                        "filename": "dynamic.json",
                        "source_url": fixture.url("/dynamic"),
                        "kind": "binary",
                    }
                ],
            }

            result = run_job(job, Path(out_dir))

        self.assertEqual(result["pass_count"], 1, result)
        self.assertEqual(result["fail_count"], 0, result)
        self.assertEqual(len(fixture.dynamic_full_bodies), 1)
        staged_snapshot = fixture.dynamic_full_bodies[0]
        self.assertEqual(bytes(fixture.uploaded), staged_snapshot)
        self.assertEqual(result["assets"][0]["sha256"], hashlib.sha256(staged_snapshot).hexdigest())
        self.assertEqual(result["assets"][0]["method"], "drive-resumable-local")

    def test_known_length_static_source_keeps_direct_streaming_path(self):
        with DownloadFixture() as fixture, TemporaryDirectory() as out_dir:
            job = {
                "download_id": "download-static",
                "upload_sessions": {"asset-1": fixture.url("/upload")},
                "assets": [
                    {
                        "asset_id": "asset-1",
                        "filename": "static.bin",
                        "source_url": fixture.url("/static"),
                        "kind": "binary",
                    }
                ],
            }

            result = run_job(job, Path(out_dir))

        self.assertEqual(result["pass_count"], 1)
        self.assertEqual(result["fail_count"], 0)
        self.assertEqual(fixture.static_gets, 1)
        self.assertEqual(bytes(fixture.uploaded), STATIC_BODY)
        self.assertEqual(result["assets"][0]["method"], "drive-resumable")


if __name__ == "__main__":
    unittest.main()
