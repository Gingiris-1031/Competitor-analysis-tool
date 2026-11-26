import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from reconcile_migration_reports import reconcile, merge_verified_reports


class ReconcileTests(unittest.TestCase):
    def test_preserve_both_sources(self):
        result = reconcile([{"id": "a"}], [{"id": "b"}])
        self.assertEqual(result["old_only"], ["a"])
        self.assertEqual(result["insforge_only"], ["b"])

    def test_privacy_or_owner_change_is_conflict(self):
        result = reconcile([{"id": "a", "is_public": False, "user_id": "u"}],
                           [{"id": "a", "is_public": True, "user_id": "v"}])
        self.assertEqual(result["conflicts"][0]["fields"], ["is_public", "user_id"])

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            reconcile([{"id": "a"}, {"id": "a"}], [])

    def test_missing_not_equal_to_null(self):
        self.assertTrue(reconcile([{"id": "a"}], [{"id": "a", "user_id": None}])["conflicts"])

    def test_equal_content(self):
        self.assertEqual(reconcile([{"id": "a"}], [{"id": "a"}])["identical"], ["a"])

    def test_merge_preserves_old_columns_and_translation(self):
        old = [{'id':'a','credits_cost':1,'report':{'body':'same'}}]
        new = [{'id':'a','updated_at':'now','report':{'body':'same','_translations':{'zh':'text'}}}]
        row = merge_verified_reports(old,new)[0]
        self.assertEqual(row['credits_cost'],1)
        self.assertEqual(row['report']['_translations'],{'zh':'text'})
        self.assertNotIn('_translations',old[0]['report'])

    def test_merge_rejects_owner_change(self):
        with self.assertRaises(ValueError):
            merge_verified_reports([{'id':'a','user_id':'u'}],[{'id':'a','user_id':'v'}])

    def test_merge_rejects_conflicting_translation(self):
        with self.assertRaises(ValueError):
            merge_verified_reports([{'id':'a','report':{'_translations':'one'}}],
                                   [{'id':'a','report':{'_translations':'two'}}])


if __name__ == "__main__":
    unittest.main()
