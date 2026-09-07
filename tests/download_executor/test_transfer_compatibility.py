"""Protocol regressions for generic direct and staged transfer paths."""
import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.download_executor import (
    DEFAULT_CHUNK, DRIVE_ALIGNMENT, download_native, run_job,
    upload_staged_resumable,
)
from tests.download_executor.test_streaming_sources import DownloadFixture


def make_job(fixture, path="/static", kind="binary", **extra):
    return {
        "download_id": "download-compatibility",
        "upload_sessions": {"asset": fixture.url("/upload")},
        "assets": [{"asset_id": "asset", "filename": "sample.bin",
                    "source_url": fixture.url(path), "kind": kind, **extra}],
    }


class TransferCompatibilityTests(unittest.TestCase):
    def test_static_formats_redirects_and_no_range_keep_their_bytes(self):
        for kind, body, path in [
            ("pdf", b"%PDF-1.7\nfixture\n%%EOF", "/static"),
            ("zip", b"PK\x05\x06" + b"\0" * 18, "/redirect"),
            ("gguf", b"GGUF\x03\0\0\0" + b"\0" * 24, "/static"),
        ]:
            with self.subTest(kind=kind), DownloadFixture(body) as fixture, TemporaryDirectory() as folder:
                result = run_job(make_job(fixture, path, kind), Path(folder))
                self.assertEqual(result["fail_count"], 0, result)
                self.assertEqual(bytes(fixture.uploaded), body)
                self.assertEqual(result["assets"][0]["sha256"], hashlib.sha256(body).hexdigest())
                self.assertEqual(result["assets"][0]["method"], "drive-resumable")
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_static_without_length_or_range_stages_once_then_uploads(self):
        body = b"%PDF-1.7\nunknown-length-fixture\n%%EOF"
        with DownloadFixture(body, unknown_length=True) as fixture, TemporaryDirectory() as folder:
            result = run_job(make_job(fixture, kind="pdf"), Path(folder))
            self.assertEqual(result["fail_count"], 0, result)
            self.assertEqual(bytes(fixture.uploaded), body)
            self.assertEqual(fixture.ranges.count(None), 1)
            self.assertEqual(result["assets"][0]["method"], "drive-resumable-local")

    def test_range_resume_keeps_existing_prefix_and_hashes_whole_source(self):
        body = b"GGUF" + bytes(range(256)) * 4096
        with DownloadFixture(body, range_supported=True) as fixture, TemporaryDirectory() as folder:
            fixture.uploaded.extend(body[:DRIVE_ALIGNMENT])
            result = run_job(make_job(fixture, kind="gguf"), Path(folder))
            self.assertEqual(result["fail_count"], 0, result)
            self.assertEqual(bytes(fixture.uploaded), body)
            self.assertEqual(fixture.put_starts[0], DRIVE_ALIGNMENT)
            self.assertIn(f"bytes={DRIVE_ALIGNMENT}-", fixture.ranges)
            self.assertEqual(result["assets"][0]["sha256"], hashlib.sha256(body).hexdigest())

    def test_oversized_file_is_direct_streamed_in_multiple_chunks(self):
        body = b"GGUF" + bytes(range(256)) * (101 * 4096)
        with DownloadFixture(body) as fixture, TemporaryDirectory() as folder:
            result = run_job(make_job(fixture, kind="gguf"), Path(folder))
            self.assertEqual(result["fail_count"], 0, result)
            self.assertEqual(fixture.uploaded, body)
            self.assertEqual(fixture.put_starts, list(range(0, len(body), DEFAULT_CHUNK)))
            self.assertEqual(result["assets"][0]["sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_staged_multichunk_resume_never_reopens_source(self):
        body = bytes(range(256)) * 4096
        with DownloadFixture(body) as fixture, TemporaryDirectory() as folder:
            asset = make_job(fixture)["assets"][0]
            staged = download_native(asset, Path(folder))
            fixture.uploaded.extend(body[:DRIVE_ALIGNMENT])
            result = upload_staged_resumable(staged, asset, fixture.url("/upload"), DRIVE_ALIGNMENT)
            self.assertEqual(result.status, "PASS", result)
            self.assertEqual(fixture.uploaded, body)
            self.assertEqual(fixture.static_gets, 1)
            self.assertEqual(fixture.put_starts, [DRIVE_ALIGNMENT, 2 * DRIVE_ALIGNMENT, 3 * DRIVE_ALIGNMENT])
            self.assertEqual(result.sha256, hashlib.sha256(body).hexdigest())

    def test_modified_staged_snapshot_is_rejected_before_upload(self):
        with DownloadFixture(b"original") as fixture, TemporaryDirectory() as folder:
            asset = make_job(fixture)["assets"][0]
            staged = download_native(asset, Path(folder))
            Path(staged.artifact_path).write_bytes(b"modified")
            result = upload_staged_resumable(staged, asset, fixture.url("/upload"))
            self.assertEqual(result.status, "FAIL")
            self.assertIn("SHA256 mismatch", result.error)
            self.assertEqual(fixture.uploaded, b"")

    def test_bad_magic_and_expected_hash_do_not_pass_staging(self):
        for extras in [{"kind": "pdf"}, {"expected_sha256": "a" * 64}]:
            with self.subTest(extras=extras), DownloadFixture(b"not-a-pdf", unknown_length=True) as fixture, TemporaryDirectory() as folder:
                result = run_job(make_job(fixture, **extras), Path(folder))
                self.assertEqual(result["fail_count"], 1)
                self.assertEqual(fixture.uploaded, b"")

    def test_unknown_length_native_failure_falls_back_to_validated_browser_snapshot(self):
        # Only the external browser process is substituted. Its file validation
        # and the subsequent HTTP Drive upload both use production code.
        body = b"%PDF-1.7\nbrowser-fixture\n%%EOF"

        def browser_process(args, **kwargs):
            Path(args[-1]).write_bytes(body)
            from subprocess import CompletedProcess
            return CompletedProcess(args, 0, stdout="", stderr="")

        with DownloadFixture() as fixture, TemporaryDirectory() as folder:
            job = make_job(fixture, "/missing", "pdf", evidence={"fallback_chain": ["native", "browser"]})
            with patch("scripts.download_executor.subprocess.run", side_effect=browser_process):
                result = run_job(job, Path(folder))
            self.assertEqual(result["fail_count"], 0, result)
            self.assertEqual(fixture.uploaded, body)
            self.assertEqual(result["assets"][0]["sha256"], hashlib.sha256(body).hexdigest())


if __name__ == "__main__":
    unittest.main()
