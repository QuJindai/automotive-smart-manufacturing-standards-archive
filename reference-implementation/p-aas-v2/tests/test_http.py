import unittest
from support import *
from paas_v2.http import encode_identifier, request

class HttpTests(unittest.TestCase):
    def test_encode_identifier_is_urlsafe_base64_without_padding(self):
        self.assertEqual('dXJuOmV4YW1wbGU6YWFzOjE', encode_identifier('urn:example:aas:1'))
        self.assertNotIn('=', encode_identifier('urn:example:aas:1'))
    def test_request_captures_status_json_and_body(self):
        fake=FakeBaSyx().start()
        try:
            r=request('GET',fake.base_url+'/v3/api-docs')
            self.assertEqual(200,r.status)
            self.assertIn('/shells',r.json_body['paths'])
            self.assertTrue(r.body_text)
        finally: fake.stop()
    def test_fake_unknown_identifiers_return_json_404(self):
        fake=FakeBaSyx().start()
        try:
            for prefix in ("/shells/", "/submodels/", "/concept-descriptions/"):
                r=request('GET', fake.base_url + prefix + encode_identifier('urn:example:probe:missing'))
                self.assertEqual(404, r.status)
                self.assertEqual({'error':'not found'}, r.json_body)
        finally:
            fake.stop()
    def test_large_json_is_parsed_before_body_text_is_bounded(self):
        fake=FakeBaSyx().start()
        try:
            r=request('GET', fake.base_url + '/large-json')
            self.assertEqual(200, r.status)
            self.assertEqual('parsed', r.json_body['tail'])
            self.assertEqual(16384, len(r.body_text))
        finally:
            fake.stop()
