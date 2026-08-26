import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from paas_ref.sample import load_sample

EXAMPLE_DIR = ROOT / 'examples' / 'automotive-eol-station'

class SampleTests(unittest.TestCase):
    def test_load_sample_has_instance_asset_and_five_submodels(self):
        sample = load_sample(EXAMPLE_DIR)
        self.assertEqual('Instance', sample.aas['assetInformation']['assetKind'])
        self.assertTrue(sample.aas['assetInformation']['globalAssetId'])
        self.assertEqual(5, len(sample.environment['submodels']))

    def test_sample_uses_synthetic_namespace(self):
        sample = load_sample(EXAMPLE_DIR)
        text = json.dumps(sample.environment, ensure_ascii=False)
        self.assertIn('urn:example:automotive:', text)

    def test_loader_rejects_missing_top_level_keys(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root/'aas-environment.json').write_text('{}', encoding='utf-8')
            (root/'capabilities.json').write_text('{}', encoding='utf-8')
            (root/'semantic-dictionary.json').write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_sample(root)

if __name__ == '__main__':
    unittest.main()
