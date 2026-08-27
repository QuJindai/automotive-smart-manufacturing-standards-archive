import base64
import json
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from support import ENV, _fake_aasx


class FakeFAAAST:
    def __init__(self):
        self.env = json.loads(json.dumps(ENV))
        self.server = None
        self.thread = None
        self.base_url = None

    def start(self):
        env = self.env

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _bytes(self, status, data, content_type):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _json(self, status, obj):
                self._bytes(status, json.dumps(obj).encode(), "application/json")

            @staticmethod
            def _decode(token):
                return base64.urlsafe_b64decode(token + "=" * ((4 - len(token) % 4) % 4)).decode()

            def do_GET(self):
                split = urlsplit(self.path)
                if split.path == "/api/v3.0/shells":
                    return self._json(200, {"result": env["assetAdministrationShells"]})
                if split.path == "/api/v3.0/submodels":
                    return self._json(200, {"result": env["submodels"]})
                if split.path == "/api/v3.0/concept-descriptions":
                    return self._json(200, {"result": env["conceptDescriptions"]})
                if split.path == "/api/v3.0/serialization":
                    query = parse_qs(split.query)
                    if not query.get("aasIds"):
                        return self._json(400, {"error": "missing aasIds"})
                    return self._bytes(200, _fake_aasx(env), "application/asset-administration-shell-package+xml")
                for prefix, key in (
                    ("/api/v3.0/shells/", "assetAdministrationShells"),
                    ("/api/v3.0/submodels/", "submodels"),
                    ("/api/v3.0/concept-descriptions/", "conceptDescriptions"),
                ):
                    if split.path.startswith(prefix):
                        raw = self._decode(split.path[len(prefix):])
                        for item in env[key]:
                            if item["id"] == raw:
                                return self._json(200, item)
                        return self._json(404, {"error": "not found"})
                return self._json(404, {"error": "no route"})

            def do_POST(self):
                split = urlsplit(self.path)
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length) if length else b""
                if split.path == "/api/v3.0/import":
                    return self._json(200, [])
                return self._json(404, {"error": "no route"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()


class FAAASTCliTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeFAAAST().start()

    def tearDown(self):
        self.fake.stop()

    def test_cli_runs_same_profile_against_faaast(self):
        root = Path(__file__).resolve().parents[1]
        fixture = root.parent / "p-aas-v1" / "examples" / "automotive-eol-station" / "aas-environment.json"
        out = root / "tests" / ".tmp-faaast-cli"
        command = [
            sys.executable,
            str(root / "run_external.py"),
            "--adapter", "faaast",
            "--base-url", self.fake.base_url,
            "--fixture", str(fixture),
            "--out", str(out),
            "--target-version", "1.3.0-test",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("P_AAS_V2_REQUIRED_FAILURES=0", completed.stdout)
        summary = json.loads((out / "interop-summary.json").read_text(encoding="utf-8"))
        self.assertEqual({"FAIL": 0, "BLOCKED": 0}, {k: summary["counts"][k] for k in ("FAIL", "BLOCKED")})
        bundle = json.loads((out / "evidence-bundle.json").read_text(encoding="utf-8"))
        aasx_result = next(x for x in bundle["test_results"] if x["test_id"] == "AAS-T018")
        self.assertNotIn("BaSyx", aasx_result["observations"])
        self.assertIn("FA3ST", aasx_result["observations"])


if __name__ == "__main__":
    unittest.main()
