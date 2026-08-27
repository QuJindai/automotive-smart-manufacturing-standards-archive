import unittest
from support import *
from paas_v2.external import CapabilityStatus, CapabilityRecord
class ExternalModelTests(unittest.TestCase):
    def test_capability_statuses_are_stable(self):
        self.assertEqual('SUPPORTED_VERIFIED',CapabilityStatus.SUPPORTED_VERIFIED.value); self.assertEqual('UNSUPPORTED_WITH_EVIDENCE',CapabilityStatus.UNSUPPORTED_WITH_EVIDENCE.value)
    def test_capability_record_serializes(self):
        rec=CapabilityRecord('read_aas',['AAS-T011'],True,True,CapabilityStatus.SUPPORTED_VERIFIED,'openapi','/shells/{id}',200,'ok',[]); self.assertEqual('read_aas',rec.to_dict()['capability_id'])
