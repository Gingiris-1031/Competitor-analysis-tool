import unittest
from modules.report_access import report_id_for_path, owner_can_read

class ReportAccessTests(unittest.TestCase):
 def test_payload_variants(self):
  for path in ['/api/report/a','/api/v1/report/a','/api/v1/report/a/markdown','/api/export/a','/api/share/a','/api/share/audit/a','/api/og/audit/a.png','/api/report/a/translate','/api/growth-audit/a']:
   self.assertEqual(report_id_for_path(path),'a',path)
 def test_gallery_not_blocked(self):
  self.assertIsNone(report_id_for_path('/api/public-reports'))
 def test_private_requires_matching_owner(self):
  r={'is_public':False,'user_id':'owner'}
  self.assertFalse(owner_can_read(r,None))
  self.assertFalse(owner_can_read(r,{'id':'other'}))
  self.assertTrue(owner_can_read(r,{'id':'owner'}))
 def test_ownerless_private_is_not_public(self):
  self.assertFalse(owner_can_read({'is_public':False,'user_id':None},{'id':None}))
 def test_public_remains_public(self):
  self.assertTrue(owner_can_read({'is_public':True},None))
