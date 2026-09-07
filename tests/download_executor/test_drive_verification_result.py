import unittest
import json
import re
import subprocess
import shutil
import sys
import textwrap
from pathlib import Path
from tempfile import TemporaryDirectory
from scripts.download_executor import apply_drive_verification


class DriveVerificationResultTests(unittest.TestCase):
    def result(self):
        ref = {'file_id': 'drive-1', 'name': 'a.pdf', 'size': 12, 'sha256': 'a' * 64}
        return {'assets': [{'asset_id': 'a', 'status': 'PASS', 'bytes': 12, 'sha256': 'a' * 64, 'drive_ref': ref}],
                'drive_refs': [ref], 'pass_count': 1, 'fail_count': 0}

    def test_independent_verification_is_attached_to_the_completed_result(self):
        data = self.result()
        verified = {'verified': True, 'drive_refs': [{**data['drive_refs'][0], 'checksum_verified': True,
                    'checksum_method': 'google_drive_sha256', 'drive_sha256': 'a' * 64}]}
        result = apply_drive_verification(data, verified)
        self.assertTrue(result['drive_verified'])
        self.assertTrue(result['assets'][0]['drive_ref']['checksum_verified'])

    def test_verification_failure_becomes_a_terminal_reportable_failure(self):
        result = apply_drive_verification(self.result(), {'error': 'Drive file SHA256 mismatch'})
        self.assertFalse(result['drive_verified'])
        self.assertEqual(result['fail_count'], 1)
        self.assertEqual(result['assets'][0]['status'], 'FAIL')
        self.assertEqual(result['assets'][0]['error_code'], 'DRIVE_VERIFICATION_FAILED')
        self.assertEqual(result['drive_refs'], [])

    def test_malformed_gateway_json_is_a_reportable_failure(self):
        for verification in (None, [], 42, {'drive_refs': 42}, {'drive_refs': [None, 42]}):
            with self.subTest(verification=verification):
                result = apply_drive_verification(self.result(), verification)
                self.assertFalse(result['drive_verified'])
                self.assertEqual(result['fail_count'], 1)

    def test_mismatched_or_incomplete_cloud_receipt_is_rejected(self):
        for changes in [{'size': 6}, {'sha256': 'b' * 64}, {'checksum_verified': False}, {'file_id': 'other'}]:
            data = self.result()
            receipt = {**data['drive_refs'][0], 'checksum_verified': True, **changes}
            result = apply_drive_verification(data, {'verified': True, 'drive_refs': [receipt]})
            self.assertFalse(result['drive_verified'])
            self.assertEqual(result['fail_count'], 1)

    def test_workflow_executes_verification_normalization_and_writes_both_outcomes(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / '.github/workflows/download-executor.yml').read_text(encoding='utf-8')
        step = workflow.split('      - name: Verify direct Drive uploads\n', 1)[1].split('      - name:', 1)[0]
        blocks = re.findall(r"python - <<'PY'\n(.*?)          PY", step, re.S)
        program = textwrap.dedent(blocks[-1])
        # Execute the exact embedded production step; only its HTTP input is a fixture.
        program = f'import sys; sys.path.insert(0, {str(root)!r})\n' + program
        for input_value in (True, False, None, [], {'drive_refs': 42}):
            success = input_value is True
            with self.subTest(input_value=input_value), TemporaryDirectory() as folder:
                data = self.result()
                verified = {'verified': input_value, 'drive_refs': [{**data['drive_refs'][0], 'checksum_verified': input_value}]} if isinstance(input_value, bool) else input_value
                (Path(folder) / 'result.json').write_text(json.dumps(data), encoding='utf-8')
                (Path(folder) / 'drive-verify-result.json').write_text(json.dumps(verified), encoding='utf-8')
                subprocess.run([sys.executable, '-c', program], cwd=folder, check=True, capture_output=True)
                saved = json.loads((Path(folder) / 'result.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['drive_verified'], success)
                self.assertEqual(saved['fail_count'], 0 if success else 1)

    def test_verification_oidc_failure_still_reaches_normalization(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / '.github/workflows/download-executor.yml').read_text(encoding='utf-8')
        refresh = workflow.split('          # Refresh the OIDC identity after downloading large files.\n', 1)[1].split("          python - <<'PY'", 1)[0]
        git_bash = Path('C:/Program Files/Git/bin/bash.exe')
        bash = str(git_bash) if git_bash.exists() else shutil.which('bash')
        self.assertTrue(bash, 'bash required for production workflow contract')
        program = ('set -euo pipefail\n'
                   'curl() { return 22; }\n'
                   'export ACTIONS_ID_TOKEN_REQUEST_TOKEN=fixture ACTIONS_ID_TOKEN_REQUEST_URL=https://invalid.example DOWNLOAD_ID=download-fixture\n'
                   + textwrap.dedent(refresh) + '\necho NORMALIZER_REACHED\n')
        with TemporaryDirectory() as folder:
            result = subprocess.run([bash, '-c', program], cwd=folder, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('NORMALIZER_REACHED', result.stdout)
