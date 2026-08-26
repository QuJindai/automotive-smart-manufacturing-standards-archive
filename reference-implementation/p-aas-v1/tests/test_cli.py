import json, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class CliTests(unittest.TestCase):
    def test_help_and_reference_run_exit_zero(self):
        help_run=subprocess.run([sys.executable,str(ROOT/'run_reference.py'),'--help'],capture_output=True,text=True)
        self.assertEqual(0,help_run.returncode,help_run.stderr)
        self.assertIn('--out',help_run.stdout)
        with tempfile.TemporaryDirectory() as td:
            run=subprocess.run([sys.executable,str(ROOT/'run_reference.py'),'--out',td],capture_output=True,text=True)
            self.assertEqual(0,run.returncode,run.stderr+run.stdout)
            self.assertIn('AAS_PASS=19 AAS_FAIL=0 AAS_BLOCKED=0',run.stdout)
            summary=json.loads((Path(td)/'test-summary.json').read_text(encoding='utf-8'))
            self.assertEqual('PASS',summary['overall'])

if __name__=='__main__': unittest.main()
