import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from paas_ref.sample import load_sample
from paas_ref.semantic import check_iec61360, check_languages, check_units, check_unit_resolvability

EXAMPLE_DIR = ROOT / 'examples' / 'automotive-eol-station'

class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.sample = load_sample(EXAMPLE_DIR)

    def test_positive_semantic_rules_pass(self):
        self.assertTrue(check_iec61360(self.sample).passed)
        self.assertTrue(check_languages(self.sample, {'en','zh-CN'}).passed)
        self.assertTrue(check_units(self.sample).passed)
        self.assertTrue(check_unit_resolvability(self.sample).passed)

    def test_missing_iec61360_fails(self):
        sample = copy.deepcopy(self.sample)
        sample.environment['conceptDescriptions'][0]['embeddedDataSpecifications'] = []
        self.assertFalse(check_iec61360(sample).passed)

    def test_missing_english_preferred_name_fails(self):
        sample = copy.deepcopy(self.sample)
        content = sample.environment['conceptDescriptions'][0]['embeddedDataSpecifications'][0]['dataSpecificationContent']
        content['preferredName'] = [x for x in content['preferredName'] if x['language'] != 'en']
        self.assertFalse(check_languages(sample, {'en'}).passed)

    def test_unit_text_mismatch_fails(self):
        sample = copy.deepcopy(self.sample)
        target = next(x for x in sample.environment['conceptDescriptions'] if x['idShort']=='VoltageSetpoint')
        target['embeddedDataSpecifications'][0]['dataSpecificationContent']['unit'] = 'mV'
        self.assertFalse(check_units(sample).passed)

    def test_unknown_unit_id_fails(self):
        sample = copy.deepcopy(self.sample)
        target = next(x for x in sample.environment['conceptDescriptions'] if x['idShort']=='VoltageSetpoint')
        target['embeddedDataSpecifications'][0]['dataSpecificationContent']['unitId']['keys'][0]['value'] = 'urn:example:unit:unknown'
        self.assertFalse(check_unit_resolvability(sample).passed)

if __name__ == '__main__':
    unittest.main()
