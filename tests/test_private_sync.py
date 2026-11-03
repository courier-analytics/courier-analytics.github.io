import importlib.util,json,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('private_sync',Path(__file__).resolve().parents[1]/'tools/private_web/sync_data.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
ROOT=Path(__file__).resolve().parents[1]
class PrivateFeedSyncTests(unittest.TestCase):
    def test_medical_uses_published_fallback_if_current_site_missing(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)
            result=m.sync({'medical-books.json':[target/'missing',ROOT/'data/medical-books.json']},target)
            self.assertEqual(result['medical-books.json'],'updated')
            self.assertTrue(json.loads((target/'medical-books.json').read_text())['records'])
    def test_missing_optional_feed_does_not_block_slots_or_fabricate_zero(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)
            result=m.sync({'dashboard.json':[ROOT/'data/dashboard.json'],'medical-books.json':[target/'missing']},target)
            self.assertEqual(result['medical-books.json'],'optional_feed_unavailable')
            self.assertEqual(json.loads((target/'medical-books.json').read_text())['records'],[])
            self.assertTrue(json.loads((target/'dashboard.json').read_text())['records'])
    def test_previous_copy_preserved_and_invalid_sources_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d);(target/'medical-books.json').write_text('previous')
            m.sync({'medical-books.json':[target/'missing']},target)
            self.assertEqual((target/'medical-books.json').read_text(),'previous')
            bad=target/'bad.json';bad.write_text('{"schema_version":1,"records":[{"name":"PRIVATE_NAME"}]}')
            result=m.sync({'dashboard.json':[bad,ROOT/'data/dashboard.json']},target)
            self.assertEqual(result['dashboard.json'],'updated')
            self.assertNotIn('PRIVATE_NAME',(target/'dashboard.json').read_text())
    def test_missing_primary_feed_without_saved_copy_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):m.sync({'dashboard.json':[Path(d)/'missing']},Path(d))
