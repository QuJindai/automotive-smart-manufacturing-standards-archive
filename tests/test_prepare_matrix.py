import copy
import unittest

from scripts.prepare_matrix import MAX_ARTIFACT_BYTES, build_matrix, validate_manifest


class PrepareMatrixTests(unittest.TestCase):
    def base_manifest(self):
        return {
            "schema_version": 1,
            "assets": [
                {
                    "id": "A",
                    "title": "A",
                    "url": "https://example.com/a.pdf",
                    "filename": "a.pdf",
                    "kind": "pdf",
                    "artifact_group": "docs",
                    "license_class": "public-government",
                    "redistributable": True,
                    "expected_size_bytes": 100,
                },
                {
                    "id": "B",
                    "title": "B",
                    "url": "https://example.com/b.zip",
                    "filename": "b.zip",
                    "kind": "zip",
                    "artifact_group": "large",
                    "license_class": "open-source",
                    "redistributable": True,
                    "expected_size_bytes": 1000,
                    "split_parts": 2,
                },
            ],
        }

    def test_valid_manifest_builds_group_and_split_matrix(self):
        manifest = self.base_manifest()
        assets = validate_manifest(manifest)
        matrix = build_matrix(assets)
        self.assertEqual(3, len(matrix["include"]))
        self.assertEqual("group", matrix["include"][0]["mode"])
        self.assertEqual("docs", matrix["include"][0]["artifact_name"])
        self.assertEqual("split", matrix["include"][1]["mode"])
        self.assertEqual(0, matrix["include"][1]["part_index"])
        self.assertEqual(1, matrix["include"][2]["part_index"])

    def test_duplicate_id_is_rejected(self):
        manifest = self.base_manifest()
        duplicate = copy.deepcopy(manifest["assets"][0])
        duplicate["filename"] = "other.pdf"
        manifest["assets"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "duplicate asset id"):
            validate_manifest(manifest)

    def test_non_https_url_is_rejected(self):
        manifest = self.base_manifest()
        manifest["assets"][0]["url"] = "http://example.com/a.pdf"
        with self.assertRaisesRegex(ValueError, "https URL"):
            validate_manifest(manifest)

    def test_non_redistributable_asset_is_rejected(self):
        manifest = self.base_manifest()
        manifest["assets"][0]["redistributable"] = False
        with self.assertRaisesRegex(ValueError, "redistributable"):
            validate_manifest(manifest)

    def test_samr_fulltext_domain_is_rejected_from_public_artifacts(self):
        manifest = self.base_manifest()
        manifest["assets"][0]["url"] = "https://openstd.samr.gov.cn/bzgk/std/example.pdf"
        with self.assertRaisesRegex(ValueError, "copyright-restricted"):
            validate_manifest(manifest)

    def test_oversized_group_is_rejected(self):
        manifest = self.base_manifest()
        manifest["assets"][0]["expected_size_bytes"] = MAX_ARTIFACT_BYTES + 1
        with self.assertRaisesRegex(ValueError, "exceeds"):
            validate_manifest(manifest)

    def test_split_count_must_reduce_expected_part_under_limit(self):
        manifest = self.base_manifest()
        manifest["assets"][1]["expected_size_bytes"] = MAX_ARTIFACT_BYTES * 3
        manifest["assets"][1]["split_parts"] = 2
        with self.assertRaisesRegex(ValueError, "remains too large"):
            validate_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
