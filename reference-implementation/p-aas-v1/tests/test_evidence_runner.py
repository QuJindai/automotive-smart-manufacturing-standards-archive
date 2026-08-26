import hashlib, json, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from paas_ref.runner import run_reference

EXAMPLE_DIR=ROOT/'examples'/'automotive-eol-station'
PROFILE_DIR=ROOT/'profile'

class EvidenceRunnerTests(unittest.TestCase):
    def test_reference_run_yields_19_pass_results_and_hashed_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)
            bundle=run_reference(EXAMPLE_DIR,out,profile_dir=PROFILE_DIR)
            self.assertEqual(19,len(bundle['test_results']))
            self.assertEqual([f'AAS-T{i:03d}' for i in range(1,20)],[x['test_id'] for x in bundle['test_results']])
            self.assertTrue(all(x['result']=='PASS' for x in bundle['test_results']))
            self.assertTrue((out/'sample.aasx').exists())
            self.assertTrue((out/'test-summary.json').exists())
            text=json.dumps(bundle,ensure_ascii=False)
            self.assertNotIn('drive.google.com',text)
            seen={}
            for result in bundle['test_results']:
                for artifact in result['artifacts']:
                    seen[artifact['artifact_id']]=artifact
            self.assertGreaterEqual(len(seen),3)
            for artifact in seen.values():
                p=out/artifact['uri']
                self.assertTrue(p.exists(),artifact)
                self.assertEqual(artifact['sha256'],hashlib.sha256(p.read_bytes()).hexdigest())
            summary=json.loads((out/'test-summary.json').read_text(encoding='utf-8'))
            self.assertEqual({'PASS':19,'FAIL':0,'BLOCKED':0,'NOT_APPLICABLE':0},summary['counts'])
            self.assertEqual('PASS',summary['overall'])

    def test_bundle_has_evidence_schema_required_fields(self):
        with tempfile.TemporaryDirectory() as td:
            bundle=run_reference(EXAMPLE_DIR,Path(td),profile_dir=PROFILE_DIR)
            for key in ['schema_version','evidence_bundle_id','profile_version','system_under_test','run_started_at','test_results']:
                self.assertIn(key,bundle)
            for result in bundle['test_results']:
                for key in ['test_id','level','result','executed_at','linked_rule_ids','assertions','artifacts']:
                    self.assertIn(key,result)

if __name__=='__main__': unittest.main()
