import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import download_executor as executor


class PersonalArchiveContracts(unittest.TestCase):
    def test_personal_job_without_drive_session_never_fetches_to_a_transfer_artifact(self):
        job = {'download_id': 'private', 'purpose': 'personal_archive', 'assets': [
            {'asset_id': 'a', 'filename': 'paper.pdf', 'source_url': 'https://publisher.example/paper.pdf'}]}
        with patch.object(executor, 'run_small_asset', side_effect=AssertionError('source must not be fetched')):
            result = executor.run_job(job, Path('.'))
        self.assertEqual(result['pass_count'], 0)
        self.assertTrue(result['auth_required'])
        self.assertEqual(result['assets'][0]['error_code'], 'PRIVATE_DRIVE_SESSION_REQUIRED')

    def test_personal_jobs_never_allow_github_artifact_upload(self):
        allow = getattr(executor, 'artifact_upload_allowed', lambda job: True)
        self.assertFalse(allow({'purpose': 'personal_archive'}))
        self.assertTrue(allow({'purpose': 'public_redistribution'}))
        self.assertTrue(allow({}))  # Existing jobs keep their previous transfer contract.

    def test_personal_preflight_without_session_makes_no_source_request(self):
        asset = {'asset_id': 'a', 'source_url': 'https://publisher.example/paper.pdf', 'expected_size_bytes': 200000000}
        job = {'purpose': 'personal_archive', 'assets': [asset]}
        with patch.object(executor, 'source_size', side_effect=AssertionError('preflight must not fetch')):
            self.assertEqual(executor.preflight_source_size(job, asset), 0)

    def test_non_private_destination_is_a_terminal_failure_not_oauth_retry(self):
        job = {'purpose': 'personal_archive', 'drive_session_error': 'PRIVATE_DESTINATION_REQUIRED', 'assets': [{'asset_id': 'a', 'filename': 'a.pdf'}]}
        result = executor.run_job(job, Path('.'))
        self.assertEqual(result['assets'][0]['error_code'], 'PRIVATE_DESTINATION_REQUIRED')
        self.assertFalse(result.get('auth_required', False))


if __name__ == '__main__':
    unittest.main()
