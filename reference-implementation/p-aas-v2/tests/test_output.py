import json,tempfile,unittest
from pathlib import Path
from support import *
from paas_v2.output import write_outputs
from paas_v2.assessment import AssessmentResult
from paas_v2.external import CapabilityRecord, CapabilityStatus
class OutputTests(unittest.TestCase):
    def test_writes_truthful_matrix_and_summary(self):
        with tempfile.TemporaryDirectory() as td:
            caps=[CapabilityRecord('authorization',['AAS-T013'],False,False,CapabilityStatus.UNSUPPORTED_WITH_EVIDENCE,'openapi',None,None,'disabled',[])]; results=[AssessmentResult('AAS-T013','NOT_APPLICABLE','UNSUPPORTED_WITH_EVIDENCE','disabled',[],[])]; write_outputs(Path(td),{'implementation':'BaSyx','version':'x'},caps,results); summary=json.loads((Path(td)/'interop-summary.json').read_text()); self.assertFalse(summary['certification_claim']); self.assertEqual(1,summary['counts']['NOT_APPLICABLE']); self.assertTrue((Path(td)/'implementation-capability-matrix.csv').exists())
