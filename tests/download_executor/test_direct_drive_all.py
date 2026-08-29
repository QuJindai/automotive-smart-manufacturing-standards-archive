import unittest
from unittest.mock import patch

from scripts.download_executor import AssetResult, run_job


class DirectDriveAllAssetsContracts(unittest.TestCase):
    def test_small_asset_uses_drive_session_when_available(self):
        job = {
            "download_id": "download-small",
            "small_limit_bytes": 100 * 1024 * 1024,
            "upload_sessions": {"asset-1": "https://upload.example/session"},
            "assets": [
                {
                    "asset_id": "asset-1",
                    "filename": "paper.pdf",
                    "source_url": "https://example.com/paper.pdf",
                    "kind": "pdf",
                    "expected_size_bytes": 2 * 1024 * 1024,
                }
            ],
        }
        direct = AssetResult(
            asset_id="asset-1",
            filename="paper.pdf",
            status="PASS",
            bytes=2 * 1024 * 1024,
            sha256="a" * 64,
            method="drive-resumable",
            drive_ref={"file_id": "drive-1", "name": "paper.pdf", "size": 2 * 1024 * 1024},
        )
        with patch("scripts.download_executor.upload_direct_resumable", return_value=direct) as upload, \
             patch("scripts.download_executor.run_small_asset", side_effect=AssertionError("small artifact path must not run when Drive session exists")):
            result = run_job(job, out_dir=None)

        upload.assert_called_once_with(job["assets"][0], "https://upload.example/session")
        self.assertEqual(result["pass_count"], 1)
        self.assertEqual(result["fail_count"], 0)
        self.assertEqual(result["drive_refs"][0]["file_id"], "drive-1")


if __name__ == "__main__":
    unittest.main()
