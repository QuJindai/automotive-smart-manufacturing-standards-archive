"""Regressions for false PASS, safe fallback and completed upload receipts."""
import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from subprocess import CompletedProcess
from unittest.mock import patch

from scripts.download_executor import download_native, run_job, upload_staged_resumable
from tests.download_executor.test_streaming_sources import DownloadFixture
from tests.download_executor.test_transfer_compatibility import make_job


class IntegrityClosureTests(unittest.TestCase):
    def test_html_challenge_can_fall_back_without_accepting_it_as_a_pdf(self):
        body = b'%PDF-1.7\nverified-browser-payload\n%%EOF'
        def browser_process(args, **kwargs):
            Path(args[-1]).write_bytes(body)
            return CompletedProcess(args, 0, stdout='', stderr='')
        for direct, content_type in [(d, t) for d in (False, True) for t in ('text/html', 'text/plain', None)]:
            with self.subTest(direct=direct, content_type=content_type), DownloadFixture(b'<html>verify</html>', content_type=content_type) as fixture, TemporaryDirectory() as folder:
                job = make_job(fixture, kind='pdf', expected_size_bytes=len(body), evidence={'fallback_chain': ['native', 'browser']})
                if not direct:
                    job['upload_sessions'] = {}
                with patch('scripts.download_executor.subprocess.run', side_effect=browser_process):
                    result = run_job(job, Path(folder))
                self.assertEqual(result['fail_count'], 0, result)
                self.assertEqual(result['assets'][0]['bytes'], len(body))

    def test_partial_direct_resume_without_identity_is_rejected(self):
        body = b'old-prefix-new-tail'
        with DownloadFixture(body, range_supported=True) as fixture, TemporaryDirectory() as folder:
            fixture.uploaded.extend(b'old-prefix')
            result = run_job(make_job(fixture), Path(folder))
            self.assertEqual(result['fail_count'], 1, result)
            self.assertFalse(fixture.complete)

    def test_unknown_length_new_snapshot_cannot_append_to_unidentified_old_session(self):
        with DownloadFixture(b'new-prefix-tail', unknown_length=True) as fixture, TemporaryDirectory() as folder:
            fixture.uploaded.extend(b'old-prefix')
            result = run_job(make_job(fixture), Path(folder))
            self.assertEqual(result['fail_count'], 1, result)
            self.assertFalse(fixture.complete)
            self.assertEqual(bytes(fixture.uploaded), b'old-prefix')

    def test_incorrect_expected_size_never_finishes_a_truncated_file(self):
        for no_length in (False, True):
            with self.subTest(no_length=no_length), DownloadFixture(b'complete-payload', unknown_length=no_length) as fixture, TemporaryDirectory() as folder:
                result = run_job(make_job(fixture, expected_size_bytes=8), Path(folder))
                self.assertEqual(result['fail_count'], 1, result)
                self.assertFalse(fixture.complete)
                self.assertEqual(result['assets'][0]['error_code'], 'INTEGRITY_ERROR')

    def test_known_length_source_failure_can_upload_browser_snapshot(self):
        body = b'%PDF-1.7\nbrowser-fixture\n%%EOF'
        def browser_process(args, **kwargs):
            Path(args[-1]).write_bytes(body)
            return CompletedProcess(args, 0, stdout='', stderr='')
        with DownloadFixture() as fixture, TemporaryDirectory() as folder:
            job = make_job(fixture, '/missing', 'pdf', expected_size_bytes=len(body), evidence={'fallback_chain': ['native', 'browser']})
            with patch('scripts.download_executor.subprocess.run', side_effect=browser_process):
                result = run_job(job, Path(folder))
            self.assertEqual(result['fail_count'], 0, result)
            self.assertEqual(bytes(fixture.uploaded), body)
            self.assertEqual(result['assets'][0]['sha256'], hashlib.sha256(body).hexdigest())

    def test_hash_failure_does_not_finalize_or_fall_back(self):
        with DownloadFixture(b'complete-payload') as fixture, TemporaryDirectory() as folder:
            job = make_job(fixture, expected_sha256='a' * 64, evidence={'fallback_chain': ['native', 'browser']})
            with patch('scripts.download_executor.subprocess.run', side_effect=AssertionError('integrity failures must not invoke browser')):
                result = run_job(job, Path(folder))
            self.assertEqual(result['fail_count'], 1)
            self.assertFalse(fixture.complete)
            self.assertEqual(result['assets'][0]['error_code'], 'INTEGRITY_ERROR')

    def test_completed_staged_session_preserves_file_id_without_source_refetch(self):
        with DownloadFixture(b'complete-payload') as fixture, TemporaryDirectory() as folder:
            asset = make_job(fixture)['assets'][0]
            staged = download_native(asset, Path(folder))
            first = upload_staged_resumable(staged, asset, fixture.url('/upload'))
            second = upload_staged_resumable(staged, asset, fixture.url('/upload'))
            self.assertEqual(second.status, 'PASS', second)
            self.assertEqual(second.drive_ref['file_id'], first.drive_ref['file_id'])
            self.assertEqual(second.sha256, first.sha256)
            self.assertEqual(fixture.static_gets, 1)

    def test_completed_direct_session_returns_id_and_computed_hash(self):
        with DownloadFixture(b'complete-payload') as fixture, TemporaryDirectory() as folder:
            job = make_job(fixture)
            first = run_job(job, Path(folder))
            second = run_job(job, Path(folder))
            self.assertEqual(second['fail_count'], 0, second)
            self.assertEqual(second['drive_refs'][0]['file_id'], 'drive-fixture')
            self.assertEqual(second['assets'][0]['sha256'], first['assets'][0]['sha256'])

    def test_missing_completed_receipt_id_is_not_a_pass(self):
        for staged_path in (False, True):
            with self.subTest(staged_path=staged_path), DownloadFixture(b'complete-payload', unknown_length=staged_path) as fixture, TemporaryDirectory() as folder:
                fixture.omit_receipt_id = True
                result = run_job(make_job(fixture), Path(folder))
                self.assertEqual(result['fail_count'], 1, result)
                self.assertEqual(result['drive_refs'], [])

    def test_partial_resume_without_range_does_not_mix_a_new_browser_snapshot(self):
        with DownloadFixture(b'complete-payload') as fixture, TemporaryDirectory() as folder:
            fixture.uploaded.extend(b'complete')
            job = make_job(fixture, evidence={'fallback_chain': ['native', 'browser']})
            with patch('scripts.download_executor.subprocess.run', side_effect=AssertionError('must not mix snapshots')):
                result = run_job(job, Path(folder))
            self.assertEqual(result['fail_count'], 1)
            self.assertFalse(fixture.complete)


if __name__ == '__main__':
    unittest.main()
