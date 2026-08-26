import unittest
from support import *
from paas_v2.assessment import classify_optional, external_result
from paas_v2.external import CapabilityRecord, CapabilityStatus
class AssessmentTests(unittest.TestCase):
    def test_unsupported_optional_maps_to_na_with_evidence(self):
        c=CapabilityRecord('authorization',['AAS-T013'],False,False,CapabilityStatus.UNSUPPORTED_WITH_EVIDENCE,'openapi',None,None,'authorization disabled',[]); r=classify_optional('AAS-T013',c); self.assertEqual('NOT_APPLICABLE',r.result); self.assertEqual('UNSUPPORTED_WITH_EVIDENCE',r.capability_status)
    def test_supported_not_verified_optional_is_blocked_not_pass(self):
        c=CapabilityRecord('aasx_package',['AAS-T018'],True,False,CapabilityStatus.SUPPORTED_NOT_VERIFIED,'openapi','/serialization',None,'advertised but not probed',[]); r=classify_optional('AAS-T018',c); self.assertEqual('BLOCKED',r.result); self.assertEqual('SUPPORTED_NOT_VERIFIED',r.capability_status)
    def test_blocked_maps_to_blocked(self):
        c=CapabilityRecord('read_aas',['AAS-T011'],False,False,CapabilityStatus.BLOCKED,'transport',None,None,'no openapi',[]); self.assertEqual('BLOCKED',external_result('AAS-T011',c,required=True).result)
