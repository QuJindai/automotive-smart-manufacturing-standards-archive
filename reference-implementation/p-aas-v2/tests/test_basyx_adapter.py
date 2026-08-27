import json, unittest, zipfile, io
from support import *
from support import _fake_aasx
from paas_v2.basyx import BasyxAdapter
from paas_v2.external import CapabilityStatus

class BasyxAdapterTests(unittest.TestCase):
    def setUp(self): self.fake=FakeBaSyx().start(); self.adapter=BasyxAdapter(self.fake.base_url, {'implementation':'Eclipse BaSyx','version':'test'})
    def tearDown(self): self.fake.stop()
    def test_discovers_core_capabilities_from_openapi(self):
        caps={c.capability_id:c for c in self.adapter.discover_capabilities()}
        self.assertEqual(CapabilityStatus.SUPPORTED_VERIFIED,caps['read_aas'].status)
        self.assertEqual(CapabilityStatus.UNSUPPORTED_WITH_EVIDENCE,caps['query'].status)
        self.assertEqual(CapabilityStatus.UNSUPPORTED_WITH_EVIDENCE,caps['authorization'].status)
        self.assertEqual(CapabilityStatus.SUPPORTED_NOT_VERIFIED,caps['aasx_package'].status)
    def test_reads_aas_submodel_and_concept_description(self):
        aas_id=self.fake.env['assetAdministrationShells'][0]['id']; sm_id=self.fake.env['submodels'][0]['id']; cd_id=self.fake.env['conceptDescriptions'][0]['id']
        self.assertEqual(aas_id,self.adapter.read_aas(aas_id).payload['id'])
        self.assertEqual(sm_id,self.adapter.read_submodel(sm_id).payload['id'])
        self.assertEqual(cd_id,self.adapter.read_concept_description(cd_id).payload['id'])
    def test_import_falls_back_to_repository_posts(self):
        result=self.adapter.import_environment(self.fake.env); self.assertEqual('repository-posts',result.route); self.assertTrue(result.success)
    def test_import_aasx_uses_package_part_and_json_response_accept(self):
        package=_fake_aasx(self.fake.env)
        result=self.adapter.import_aasx(package,'fixture.aasx')
        self.assertTrue(result.success)
        self.assertEqual('upload-aasx',result.route)
        self.assertEqual('application/json',self.fake.last_upload_accept)
        self.assertTrue(self.fake.last_upload_contains_zip)
    def test_fetch_openapi_decodes_basyx_base64_wrapped_json_string(self):
        self.fake.stop(); self.fake=FakeBaSyx(openapi_base64=True).start(); self.adapter=BasyxAdapter(self.fake.base_url,{'implementation':'Eclipse BaSyx','version':'milestone-fixture'})
        response=self.adapter.fetch_openapi(); self.assertEqual(200,response.status); self.assertIsInstance(response.payload,dict); self.assertEqual('3.0.1',response.payload['openapi']); self.assertIn('/shells/{aasIdentifier}',response.payload['paths'])
    def test_serialize_aasx_uses_encoded_ids_and_returns_zip_bytes(self):
        aas_id=self.fake.env['assetAdministrationShells'][0]['id']
        sm_ids=[x['id'] for x in self.fake.env['submodels']]
        response=self.adapter.serialize_aasx([aas_id],sm_ids,include_concept_descriptions=True)
        self.assertEqual(200,response.status)
        self.assertTrue(response.raw_body.startswith(b'PK'))
        with zipfile.ZipFile(io.BytesIO(response.raw_body)) as z:
            self.assertIsNone(z.testzip())
            self.assertIn('aasx/aasx-origin',z.namelist())
