import json,tempfile,unittest
from pathlib import Path
from support import *
from paas_v2.basyx import BasyxAdapter
from paas_v2.runner import run_external
class RunnerTests(unittest.TestCase):
    def test_fake_basyx_generates_core_pass_and_optional_evidence(self):
        fake=FakeBaSyx().start()
        try:
            with tempfile.TemporaryDirectory() as td:
                result=run_external(BasyxAdapter(fake.base_url,{'implementation':'Eclipse BaSyx','version':'fake'}),ENV,Path(td)); self.assertEqual(0,result['required_failures']); self.assertTrue((Path(td)/'evidence-bundle.json').exists()); matrix=json.loads((Path(td)/'implementation-capability-matrix.json').read_text()); self.assertTrue(any(x['capability_id']=='authorization' and x['status']=='UNSUPPORTED_WITH_EVIDENCE' for x in matrix))
        finally: fake.stop()
