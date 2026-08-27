import subprocess, sys, unittest
from pathlib import Path

RUN_EXTERNAL = Path(__file__).resolve().parents[1] / 'run_external.py'

class CliTests(unittest.TestCase):
    def test_help_exposes_supplementary_aasx_mode(self):
        completed = subprocess.run([sys.executable, str(RUN_EXTERNAL), '--help'], capture_output=True, text=True)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn('--supplementary-aasx', completed.stdout)
