import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from rehearse_supabase_import import verify_folder


class BackupVerificationTests(unittest.TestCase):
    def fixture(self,root):
        raw=b'[{"id":"one"}]'
        (root/'reports.json').write_bytes(raw)
        manifest={'status':'rows_exported_requires_final_snapshot','tables':{
            'reports':{'status':'exported','rows':1,'sha256':hashlib.sha256(raw).hexdigest()}}}
        (root/'manifest.json').write_text(json.dumps(manifest))
        return manifest

    def test_modified_backup_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root)
            (root/'reports.json').write_text('[{"id":"changed"}]')
            with self.assertRaises(ValueError):verify_folder(root,'tables')

    def test_false_row_count_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m=self.fixture(root)
            m['tables']['reports']['rows']=2
            (root/'manifest.json').write_text(json.dumps(m))
            with self.assertRaises(ValueError):verify_folder(root,'tables')

    def test_incomplete_export_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m=self.fixture(root);m['status']='incomplete'
            (root/'manifest.json').write_text(json.dumps(m))
            with self.assertRaises(ValueError):verify_folder(root,'tables')

    def test_verified_export_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m=self.fixture(root)
            self.assertEqual(verify_folder(root,'tables'),m)


if __name__=='__main__':unittest.main()
