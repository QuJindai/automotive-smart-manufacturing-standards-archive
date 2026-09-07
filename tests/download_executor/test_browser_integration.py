"""Real Chromium/helper integration against a controlled HTTPS origin.

Enable with DOWNLOAD_BROWSER_INTEGRATION=1 after installing Playwright Chromium.
The generated certificate is trusted by the Node request client only for this test.
No browser or executor function is replaced.
"""
import hashlib
import os
import ssl
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.download_executor import run_job
from tests.download_executor.test_streaming_sources import DownloadFixture


@unittest.skipUnless(os.environ.get('DOWNLOAD_BROWSER_INTEGRATION') == '1', 'requires installed Chromium and openssl')
class BrowserIntegrationTests(unittest.TestCase):
    def check_browser_path(self, known_size):
        body = b'%PDF-1.7\ncontrolled-browser-download\n%%EOF'
        browser_gets = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_HEAD(self):
                self.send_response(200)
                if known_size:
                    self.send_header('Content-Length', str(len(body)))
                self.end_headers()
            def do_GET(self):
                if self.path != '/sample.pdf':
                    self.send_response(200)
                    self.end_headers()
                    return
                if 'DownloadExecutor/' in self.headers.get('User-Agent', ''):
                    self.send_response(403)
                    self.end_headers()
                    return
                browser_gets.append(self.headers.get('User-Agent', ''))
                self.send_response(200)
                self.send_header('Content-Type', 'application/pdf')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        with TemporaryDirectory() as folder, DownloadFixture() as drive:
            cert, key = Path(folder) / 'cert.pem', Path(folder) / 'key.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                            '-keyout', str(key), '-out', str(cert), '-subj', '/CN=localhost',
                            '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1'], check=True, capture_output=True)
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                asset = {'asset_id': 'a', 'filename': 'browser.pdf', 'kind': 'pdf',
                         'source_url': f'https://localhost:{server.server_port}/sample.pdf',
                         'evidence': {'fallback_chain': ['native', 'browser']}}
                if known_size:
                    asset['expected_size_bytes'] = len(body)
                job = {'download_id': 'download-browserintegration', 'assets': [asset],
                       'upload_sessions': {'a': drive.url('/upload')}}
                with patch.dict(os.environ, {'NODE_EXTRA_CA_CERTS': str(cert), 'SSL_CERT_FILE': str(cert)}):
                    result = run_job(job, Path(folder) / 'out')
                self.assertEqual(result['fail_count'], 0, result)
                self.assertEqual(bytes(drive.uploaded), body)
                self.assertEqual(result['assets'][0]['sha256'], hashlib.sha256(body).hexdigest())
                self.assertTrue(any('Mozilla/' in user_agent for user_agent in browser_gets))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_real_browser_fallback_for_known_length_source(self):
        self.check_browser_path(True)

    def test_real_browser_fallback_for_unknown_length_source(self):
        self.check_browser_path(False)
