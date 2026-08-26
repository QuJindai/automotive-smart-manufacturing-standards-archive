import unittest
from support import *
from paas_v2.http import encode_identifier, request
class HttpTests(unittest.TestCase):
    def test_encode_identifier_is_urlsafe_base64_without_padding(self): self.assertEqual('dXJuOmV4YW1wbGU6YWFzOjE',encode_identifier('urn:example:aas:1')); self.assertNotIn('=',encode_identifier('urn:example:aas:1'))
    def test_request_captures_status_json_and_body(self):
        fake=FakeBaSyx().start()
        try:
            r=request('GET',fake.base_url+'/v3/api-docs'); self.assertEqual(200,r.status); self.assertIn('/shells',r.json_body['paths']); self.assertTrue(r.body_text)
        finally: fake.stop()
