import json,tempfile,unittest
from pathlib import Path
from support import *
from paas_v2.basyx import BasyxAdapter
from paas_v2.runner import run_external

class RunnerTests(unittest.TestCase):
    def test_fake_basyx_generates_core_pass_and_truthful_aasx_results(self):
        fake=FakeBaSyx().start()
        try:
            with tempfile.TemporaryDirectory() as td:
                result=run_external(BasyxAdapter(fake.base_url,{'implementation':'Eclipse BaSyx','version':'fake'}),ENV,Path(td))
                self.assertEqual(0,result['required_failures'])
                bundle=json.loads((Path(td)/'evidence-bundle.json').read_text())
                by_id={x['test_id']:x for x in bundle['test_results']}
                self.assertEqual('PASS',by_id['AAS-T018']['result'])
                self.assertEqual('NOT_APPLICABLE',by_id['AAS-T019']['result'])
                self.assertIn('fixture_has_no_supplementary_files',by_id['AAS-T019']['observations'])
                summary=json.loads((Path(td)/'interop-summary.json').read_text())
                self.assertEqual({'PASS':12,'FAIL':0,'BLOCKED':0,'NOT_APPLICABLE':7},summary['counts'])
                matrix=json.loads((Path(td)/'implementation-capability-matrix.json').read_text())
                caps={x['capability_id']:x for x in matrix}
                self.assertEqual('SUPPORTED_VERIFIED',caps['environment_import']['status'])
                self.assertEqual('SUPPORTED_VERIFIED',caps['aasx_package']['status'])
        finally: fake.stop()
