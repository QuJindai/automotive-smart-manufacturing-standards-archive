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

class SupplementaryRoundTripTests(unittest.TestCase):
    def test_renamed_parts_keep_identity_links_and_bytes_but_corruption_fails(self):
        import io, json, zipfile
        from paas_v2.supplementary import validate_supplementary_roundtrip
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture, package, required = build_supplementary_aasx(ENV, root/'input')
            source = package.read_bytes()
            renamed = {'manual.txt':'a1.txt','program-version-note.txt':'b2.txt','certificate.txt':'c3.txt'}
            for mode in ['valid', 'corrupt', 'swapped', 'unlinked']:
                with self.subTest(mode=mode):
                    target = root/(mode+'.aasx')
                    with zipfile.ZipFile(io.BytesIO(source)) as original, zipfile.ZipFile(target,'w') as output:
                        for name in original.namelist():
                            data = original.read(name)
                            for before, after in renamed.items():
                                name = name.replace(before, after)
                                if name.endswith(('.json','.rels')): data = data.replace(before.encode(), after.encode())
                            if mode == 'corrupt' and name.endswith('a1.txt'): data += b'changed'
                            if mode == 'swapped' and name.endswith('.json'):
                                data = data.replace(b'a1.txt',b'TEMP').replace(b'b2.txt',b'a1.txt').replace(b'TEMP',b'b2.txt')
                            if mode == 'unlinked' and name.endswith('aas-environment.json.rels'):
                                data = data.replace(b'aas-suppl',b'not-supplementary')
                            output.writestr(name,data)
                    check = validate_supplementary_roundtrip(fixture,source,target)
                    self.assertEqual(mode=='valid',check.passed,check.message)
                    if mode=='valid':
                        self.assertEqual(required,set(check.observed['verified_originals']))
                        self.assertEqual(set(renamed.values()),set(check.observed['linked']))
                        self.assertEqual(3,len(check.observed['files']))
