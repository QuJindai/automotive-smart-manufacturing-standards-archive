import json,unittest
from support import *
from paas_v2.v1_bridge import normalize_bundle,run_core_semantic_checks
class V1BridgeTests(unittest.TestCase):
    def test_returned_objects_pass_v1_checks(self):
        b=normalize_bundle(json.loads(json.dumps(ENV)),{'capabilities':['read_aas','read_submodel']}); results=run_core_semantic_checks(b); self.assertTrue(all(x.passed for x in results),[x.message for x in results])
    def test_missing_semantic_id_fails(self):
        env=json.loads(json.dumps(ENV)); env['submodels'][0]['submodelElements'][0].pop('semanticId'); b=normalize_bundle(env,{'capabilities':['read_aas','read_submodel']}); self.assertFalse(next(x for x in run_core_semantic_checks(b) if x.check_id=='required-semantics').passed)
