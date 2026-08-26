import sys, unittest
from pathlib import Path
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from paas_ref.sample import load_sample
from paas_ref.mock_server import ReferenceServer
from paas_ref.api import request_json
from paas_ref.jws import verify_compact

EXAMPLE_DIR=ROOT/'examples'/'automotive-eol-station'

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.sample=load_sample(EXAMPLE_DIR)
        self.secret=b'synthetic-reference-secret'
        self.running=ReferenceServer(self.sample,self.secret).start()
    def tearDown(self):
        self.running.stop()

    def test_query_valid_and_invalid(self):
        good=request_json('POST',self.running.base_url+'/query',{'idShort':'Status'})
        self.assertEqual(200,good.status)
        self.assertEqual('Status',good.json['results'][0]['idShort'])
        bad=request_json('POST',self.running.base_url+'/query',{'unsupported':'x'})
        self.assertEqual(400,bad.status)

    def test_reads_aas_and_submodel_by_id(self):
        aas=request_json('GET',self.running.base_url+'/shells/'+quote(self.sample.aas_id,safe=''))
        self.assertEqual(200,aas.status)
        self.assertEqual(self.sample.aas_id,aas.json['id'])
        smid=self.sample.submodel_ids['Status']
        sm=request_json('GET',self.running.base_url+'/submodels/'+quote(smid,safe=''))
        self.assertEqual(200,sm.status)
        self.assertEqual('Status',sm.json['idShort'])

    def test_protected_resource_401_403_and_200(self):
        self.assertEqual(401,request_json('GET',self.running.base_url+'/protected').status)
        denied=request_json('GET',self.running.base_url+'/protected',token='no-privilege-token')
        self.assertEqual(403,denied.status)
        self.assertNotIn('protected',denied.json)
        self.assertEqual(200,request_json('GET',self.running.base_url+'/protected',token='reader-token').status)

    def test_create_update_rights_are_separated(self):
        url=self.running.base_url+'/resources/new-resource'
        self.assertEqual(403,request_json('PUT',url,{'value':1},token='no-privilege-token').status)
        self.assertEqual(201,request_json('PUT',url,{'value':1},token='create-token').status)
        self.assertEqual(403,request_json('PUT',url,{'value':2},token='create-token').status)
        self.assertEqual(200,request_json('PUT',url,{'value':2},token='update-token').status)

    def test_abac_endpoint_and_signed_endpoint(self):
        decision=request_json('POST',self.running.base_url+'/authorize',{
            'subject':{'factory':'F1','role':'engineer'},'resource':{'factory':'F1'},'context':{'hour':10,'equipment_state':'READY'}})
        self.assertEqual(200,decision.status)
        self.assertTrue(decision.json['allowed'])
        signed=request_json('GET',self.running.base_url+'/signed/'+quote(self.sample.aas_id,safe=''))
        self.assertEqual(200,signed.status)
        ok,payload=verify_compact(signed.json['jws'],self.secret)
        self.assertTrue(ok)
        self.assertIn(self.sample.aas_id.encode(),payload)

if __name__=='__main__': unittest.main()
