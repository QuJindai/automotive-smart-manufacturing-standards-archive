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

    def test_unknown_source_size_stages_asset_then_retries_direct_drive(self):
        job = {
            "download_id": "download-unknown-size",
            "upload_sessions": {"asset-1": "https://upload.example/session"},
            "assets": [
                {
                    "asset_id": "asset-1",
                    "filename": "repo_tree.json",
                    "source_url": "https://example.com/chunked.json",
                    "kind": "binary",
                    "evidence": {"fallback_chain": ["native", "browser"]},
                }
            ],
        }
        first = AssetResult(
            asset_id="asset-1",
            filename="repo_tree.json",
            status="FAIL",
            bytes=0,
            sha256=None,
            method="drive-resumable",
            error="source size unavailable",
        )
        staged = AssetResult(
            asset_id="asset-1",
            filename="repo_tree.json",
            status="PASS",
            bytes=1234,
            sha256="b" * 64,
            method="native",
            artifact_path="/tmp/repo_tree.json",
        )
        second = AssetResult(
            asset_id="asset-1",
            filename="repo_tree.json",
            status="PASS",
            bytes=1234,
            sha256="b" * 64,
            method="drive-resumable",
            drive_ref={"file_id": "drive-tree", "name": "repo_tree.json", "size": 1234},
        )

        with patch("scripts.download_executor.upload_direct_resumable", side_effect=[first, second]) as upload, \
             patch("scripts.download_executor.run_small_asset", return_value=staged) as stage:
            result = run_job(job, out_dir="/tmp")

        self.assertEqual(result["pass_count"], 1)
        self.assertEqual(result["fail_count"], 0)
        stage.assert_called_once_with(job["assets"][0], "/tmp")
        self.assertEqual(upload.call_count, 2)
        retried_asset = upload.call_args_list[1].args[0]
        self.assertEqual(retried_asset["expected_size_bytes"], 1234)
        self.assertEqual(retried_asset["expected_sha256"], "b" * 64)


if __name__ == "__main__":
    unittest.main()
