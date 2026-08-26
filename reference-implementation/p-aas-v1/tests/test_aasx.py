import sys, tempfile, unittest, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from paas_ref.sample import load_sample
from paas_ref.aasx import build_aasx, validate_aasx

EXAMPLE_DIR=ROOT/'examples'/'automotive-eol-station'

class AasxTests(unittest.TestCase):
    def setUp(self):
        self.sample=load_sample(EXAMPLE_DIR)

    def test_build_contains_required_opc_and_supplementary_files(self):
        with tempfile.TemporaryDirectory() as td:
            p=build_aasx(self.sample,Path(td)/'sample.aasx')
            with zipfile.ZipFile(p) as z:
                names=set(z.namelist())
            required={'[Content_Types].xml','_rels/.rels','aasx/aasx-origin','aasx/_rels/aasx-origin.rels','aasx/aas-environment.json','aasx/_rels/aas-environment.json.rels','aasx/suppl/manual.txt','aasx/suppl/program-version-note.txt','aasx/suppl/certificate.txt'}
            self.assertTrue(required.issubset(names))

    def test_valid_package_passes_structure_and_supplementary_checks(self):
        with tempfile.TemporaryDirectory() as td:
            p=build_aasx(self.sample,Path(td)/'sample.aasx')
            results=validate_aasx(p,{'manual.txt','program-version-note.txt','certificate.txt'})
            self.assertTrue(all(x.passed for x in results),[x.message for x in results])

    def test_missing_origin_fails(self):
        with tempfile.TemporaryDirectory() as td:
            good=build_aasx(self.sample,Path(td)/'good.aasx')
            bad=Path(td)/'bad.aasx'
            with zipfile.ZipFile(good) as src, zipfile.ZipFile(bad,'w') as dst:
                for item in src.infolist():
                    if item.filename != 'aasx/aasx-origin':
                        dst.writestr(item,src.read(item.filename))
            results=validate_aasx(bad,{'manual.txt','program-version-note.txt','certificate.txt'})
            self.assertTrue(any((not x.passed and 'origin' in x.check_id) for x in results))

if __name__=='__main__': unittest.main()
