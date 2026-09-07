import unittest
import json
import os
import re
import subprocess
import shutil
import sys
import textwrap
from pathlib import Path
from tempfile import TemporaryDirectory
from scripts.download_executor import apply_drive_verification


class DriveVerificationResultTests(unittest.TestCase):
    def verification_step(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / '.github/workflows/download-executor.yml').read_text(encoding='utf-8')
        step = workflow.split('      - name: Verify direct Drive uploads\n', 1)[1].split('      - name:', 1)[0]
        return root, textwrap.dedent(step.split('        run: |\n', 1)[1])

    def run_verification_shell(self, folder, fake_curl):
        root, step = self.verification_step()
        git_bash = Path('C:/Program Files/Git/bin/bash.exe')
        bash = str(git_bash) if git_bash.exists() else shutil.which('bash')
        self.assertTrue(bash, 'bash required for production workflow contract')
        env = {**os.environ, 'PYTHONPATH': str(root), 'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'fixture',
               'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://invalid.example', 'DOWNLOAD_ID': 'download-fixture'}
        return subprocess.run([bash, '-c', fake_curl + '\n' + step], cwd=folder, env=env,
                              capture_output=True, text=True, timeout=30)

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
        with TemporaryDirectory() as folder:
            (Path(folder) / 'result.json').write_text(json.dumps(self.result()), encoding='utf-8')
            result = self.run_verification_shell(folder, 'curl() { return 22; }')
            saved = json.loads((Path(folder) / 'result.json').read_text(encoding='utf-8'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(saved['drive_verified'])
        self.assertEqual(saved['fail_count'], 1)

    def test_large_verification_uses_bounded_requests_and_combines_receipts(self):
        data = {'assets': [], 'drive_refs': []}
        for index in range(41):
            ref = {**self.result()['drive_refs'][0], 'file_id': f'id-{index}'}
            data['drive_refs'].append(ref)
            data['assets'].append({**self.result()['assets'][0], 'asset_id': str(index), 'drive_ref': ref})
        fake = '''curl() {
          if [[ "$*" == *audience=download-mcp* ]]; then
            printf '{"value":"fixture"}'
            return
          fi
          local output='' input=''
          while [ "$#" -gt 0 ]; do
            case "$1" in
              -o) output="$2"; shift 2;;
              --data-binary) input="${2#@}"; shift 2;;
              *) shift;;
            esac
          done
          python - "$input" "$output" <<'FIXTURE'
import json, sys
refs = json.load(open(sys.argv[1]))['drive_refs']
open('batch-sizes.txt', 'a').write(str(len(refs)) + '\\n')
json.dump({'verified': True, 'drive_refs': [{**r, 'checksum_verified': True} for r in refs]}, open(sys.argv[2], 'w'))
FIXTURE
          printf '200'
        }'''
        for fail_middle in (False, True):
            fake_response = fake.replace("'verified': True", "'verified': not sys.argv[2].endswith('-20.json')") if fail_middle else fake
            with self.subTest(fail_middle=fail_middle), TemporaryDirectory() as folder:
                (Path(folder) / 'result.json').write_text(json.dumps(data), encoding='utf-8')
                result = self.run_verification_shell(folder, fake_response)
                self.assertEqual(result.returncode, 0, result.stderr)
                batches = list(map(int, (Path(folder) / 'batch-sizes.txt').read_text().splitlines()))
                saved = json.loads((Path(folder) / 'result.json').read_text())
            self.assertEqual(batches, [20, 20, 1])
            self.assertEqual(saved['drive_verified'], not fail_middle)
            self.assertEqual(len(saved['drive_refs']), 21 if fail_middle else 41)
            self.assertEqual(saved['fail_count'], 20 if fail_middle else 0)
