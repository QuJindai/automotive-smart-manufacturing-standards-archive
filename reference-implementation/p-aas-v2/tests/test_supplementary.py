import tempfile, unittest
from pathlib import Path
from support import ENV
from paas_ref.aasx import validate_aasx
from paas_v2.supplementary import build_supplementary_aasx

class SupplementaryAasxTests(unittest.TestCase):
    def test_build_adds_three_file_elements_and_valid_relationships(self):
        with tempfile.TemporaryDirectory() as td:
            environment, package, required = build_supplementary_aasx(ENV, Path(td))
            documentation = next(sm for sm in environment['submodels'] if sm['idShort'] == 'Documentation')
            file_elements = [e for e in documentation['submodelElements'] if e.get('modelType') == 'File']
            self.assertEqual({'manual.txt','program-version-note.txt','certificate.txt'}, required)
            self.assertEqual(3, len(file_elements))
            self.assertEqual(required, {Path(e['value']).name for e in file_elements})
            self.assertTrue(all(e.get('semanticId') for e in file_elements))
            checks = validate_aasx(package, required)
            by_id = {c.check_id:c for c in checks}
            self.assertTrue(by_id['aasx-core'].passed)
            self.assertTrue(by_id['aasx-supplementary'].passed)
