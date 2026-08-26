import hashlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.download_executor import (
    AssetResult,
    chunk_ranges,
    detect_magic,
    fallback_methods,
    redact_url,
    should_fallback,
    validate_descriptor,
)


class DownloadExecutorContracts(unittest.TestCase):
    def test_descriptor_contains_only_download_id(self):
        self.assertEqual(validate_descriptor({"download_id": "download-abc"}), "download-abc")
        with self.assertRaises(ValueError):
            validate_descriptor({"download_id": "download-abc", "source_url": "https://secret.example/file"})

    def test_magic_detection(self):
        self.assertEqual(detect_magic(b"%PDF-1.7"), "pdf")
        self.assertEqual(detect_magic(b"GGUF\x03\x00\x00\x00"), "gguf")
        self.assertEqual(detect_magic(b"PK\x03\x04abc"), "zip")
        self.assertEqual(detect_magic(b"{\"x\":1}"), "json")

    def test_chunk_ranges_are_contiguous_and_aligned(self):
        ranges = list(chunk_ranges(10 * 1024 * 1024 + 17, 4 * 1024 * 1024))
        self.assertEqual(ranges[0], (0, 4 * 1024 * 1024 - 1))
        self.assertEqual(ranges[-1][1], 10 * 1024 * 1024 + 16)
        for left, right in zip(ranges, ranges[1:]):
            self.assertEqual(left[1] + 1, right[0])

    def test_url_redaction_never_logs_query_or_session(self):
        value = redact_url("https://example.com/file.bin?token=secret&x=1")
        self.assertEqual(value, "https://example.com/file.bin")
        self.assertNotIn("secret", value)

    def test_pass_does_not_fallback(self):
        passed = AssetResult(asset_id="a", filename="a.pdf", status="PASS", bytes=42, sha256="abc", method="native")
        self.assertFalse(should_fallback(passed))
        failed = AssetResult(asset_id="a", filename="a.pdf", status="FAIL", bytes=0, sha256=None, method="native", error="403")
        self.assertTrue(should_fallback(failed))

    def test_browser_hint_adds_browser_after_native_only(self):
        asset = {"evidence": {"browser_hint": True, "fallback_chain": ["native", "browser", "alternate_egress"]}}
        self.assertEqual(fallback_methods(asset), ["native", "browser", "alternate_egress"])
        asset = {"evidence": {"browser_hint": False}}
        self.assertEqual(fallback_methods(asset), ["native"])

    def test_fallback_chain_is_deduplicated_and_native_first(self):
        asset = {"evidence": {"browser_hint": True, "fallback_chain": ["browser", "native", "browser"]}}
        self.assertEqual(fallback_methods(asset), ["native", "browser"])


if __name__ == "__main__":
    unittest.main()
