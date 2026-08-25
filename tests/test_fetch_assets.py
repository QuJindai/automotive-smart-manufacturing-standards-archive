import tempfile
import unittest
from pathlib import Path

from scripts.fetch_assets import (
    enforce_payload_limit,
    sha256_file,
    split_bounds,
    validate_magic,
    write_part,
)
from scripts.prepare_matrix import MAX_ARTIFACT_BYTES


class FetchAssetsTests(unittest.TestCase):
    def test_validate_pdf_and_zip_magic(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "a.pdf"
            zip_file = root / "a.zip"
            pdf.write_bytes(b"%PDF-1.7\nhello")
            zip_file.write_bytes(b"PK\x03\x04hello")
            validate_magic(pdf, "pdf")
            validate_magic(zip_file, "zip")

    def test_invalid_magic_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.pdf"
            path.write_bytes(b"NOT-A-PDF")
            with self.assertRaisesRegex(ValueError, "invalid PDF header"):
                validate_magic(path, "pdf")

    def test_split_bounds_cover_source_without_overlap(self):
        bounds = [split_bounds(11, i, 2) for i in range(2)]
        self.assertEqual([(0, 5), (5, 11)], bounds)

    def test_write_parts_reconstruct_exact_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.bin"
            source.write_bytes(bytes(range(251)) * 1000)
            parts = []
            for index in range(3):
                part = root / f"part{index}"
                write_part(source, part, index, 3)
                parts.append(part)
            reconstructed = b"".join(part.read_bytes() for part in parts)
            self.assertEqual(source.read_bytes(), reconstructed)
            self.assertEqual(sha256_file(source), sha256_file(source))

    def test_payload_limit_rejects_large_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.bin").write_bytes(b"x" * 101)
            with self.assertRaisesRegex(ValueError, "exceeds limit"):
                enforce_payload_limit(root, limit=100)

    def test_default_payload_limit_accepts_small_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.bin").write_bytes(b"x" * 1024)
            self.assertEqual(1024, enforce_payload_limit(root, limit=MAX_ARTIFACT_BYTES))


if __name__ == "__main__":
    unittest.main()
