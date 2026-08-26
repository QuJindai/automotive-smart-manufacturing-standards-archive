import base64
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from paas_ref.policy import evaluate_abac
from paas_ref.jws import sign_compact, verify_compact

class PolicyJwsTests(unittest.TestCase):
    def test_abac_allows_matching_engineer_in_window_ready(self):
        d=evaluate_abac({'factory':'F1','role':'engineer'},{'factory':'F1'},{'hour':10,'equipment_state':'READY'})
        self.assertTrue(d.allowed)
        self.assertEqual('ALLOW',d.reason_code)

    def test_abac_denies_factory_role_time_and_state_mismatches(self):
        cases=[
            ({'factory':'F2','role':'engineer'},{'factory':'F1'},{'hour':10,'equipment_state':'READY'},'FACTORY_MISMATCH'),
            ({'factory':'F1','role':'viewer'},{'factory':'F1'},{'hour':10,'equipment_state':'READY'},'ROLE_DENIED'),
            ({'factory':'F1','role':'engineer'},{'factory':'F1'},{'hour':23,'equipment_state':'READY'},'OUTSIDE_TIME_WINDOW'),
            ({'factory':'F1','role':'engineer'},{'factory':'F1'},{'hour':10,'equipment_state':'FAULT'},'EQUIPMENT_NOT_READY')]
        for subject,resource,context,reason in cases:
            with self.subTest(reason=reason):
                d=evaluate_abac(subject,resource,context)
                self.assertFalse(d.allowed)
                self.assertEqual(reason,d.reason_code)

    def test_hs256_jws_verifies_and_tamper_fails(self):
        secret=b'synthetic-secret'
        token=sign_compact(b'{"id":"aas-1"}',secret)
        ok,payload=verify_compact(token,secret)
        self.assertTrue(ok)
        self.assertEqual(b'{"id":"aas-1"}',payload)
        parts=token.split('.')
        raw=base64.urlsafe_b64decode(parts[1]+'==')
        tampered=base64.urlsafe_b64encode(raw.replace(b'aas-1',b'aas-2')).rstrip(b'=').decode()
        bad='.'.join([parts[0],tampered,parts[2]])
        self.assertFalse(verify_compact(bad,secret)[0])

if __name__=='__main__': unittest.main()
