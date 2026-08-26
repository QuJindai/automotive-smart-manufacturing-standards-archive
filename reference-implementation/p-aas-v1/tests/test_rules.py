import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from paas_ref.sample import load_sample
from paas_ref.rules import check_asset_kind, check_asset_identifier, check_capabilities, check_required_semantics

EXAMPLE_DIR = ROOT / 'examples' / 'automotive-eol-station'

class RulesTests(unittest.TestCase):
    def setUp(self):
        self.sample = load_sample(EXAMPLE_DIR)

    def test_positive_structural_rules_pass(self):
        self.assertTrue(check_asset_kind(self.sample).passed)
        self.assertTrue(check_asset_identifier(self.sample).passed)
        self.assertTrue(check_required_semantics(self.sample).passed)
        required = {'read_aas','read_submodel','query','authorization','signed','aasx_delivery'}
        self.assertTrue(check_capabilities(self.sample, required).passed)

    def test_missing_asset_identifier_fails(self):
        sample = copy.deepcopy(self.sample)
        sample.environment['assetAdministrationShells'][0]['assetInformation'].pop('globalAssetId')
        self.assertFalse(check_asset_identifier(sample).passed)

    def test_missing_element_semantic_id_fails(self):
        sample = copy.deepcopy(self.sample)
        sample.environment['submodels'][0]['submodelElements'][0].pop('semanticId')
        result = check_required_semantics(sample)
        self.assertFalse(result.passed)
        self.assertIn('OperatingState', result.message)

    def test_missing_capability_fails(self):
        sample = copy.deepcopy(self.sample)
        sample.capabilities['capabilities'].remove('signed')
        self.assertFalse(check_capabilities(sample, {'signed'}).passed)

if __name__ == '__main__':
    unittest.main()
