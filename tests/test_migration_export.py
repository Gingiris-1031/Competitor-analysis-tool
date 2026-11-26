import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("exporter", Path(__file__).parents[1] / "scripts/export_insforge_for_migration.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class ExportTests(unittest.TestCase):
    def fake(self, rows):
        def fetch(table, params):
            cursor = params.get("id", "gt.")[3:]
            selected = [row for row in rows if row["id"] > cursor]
            return selected[:1], {"Content-Range": f"0-0/{len(rows)}"}
        return fetch

    def test_server_page_cap_does_not_truncate(self):
        rows = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        self.assertEqual(exporter.collect_table(self.fake(rows), "reports", "id", 25), rows)

    def test_missing_count_fails_closed(self):
        with self.assertRaises(ValueError):
            exporter.exact_count({"Content-Range": "0-0/*"})

    def test_repeating_page_stops(self):
        with self.assertRaises(ValueError):
            exporter.collect_table(lambda *a: ([{"id": "a"}], {"Content-Range": "0-0/2"}), "reports", "id", 25)

    def test_count_mismatch_fails(self):
        def fetch(table, params):
            rows, _ = self.fake([{"id": "a"}])(table, params)
            return rows, {"Content-Range": "0-0/2"}
        with self.assertRaises(ValueError):
            exporter.collect_table(fetch, "reports", "id", 25)

    def test_atomic_file_is_private(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "data.json"
            exporter.atomic_json(path, [{"id": "a"}])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
