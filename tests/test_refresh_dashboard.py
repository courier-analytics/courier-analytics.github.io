import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from refresh_dashboard import refresh, merge_feed, rows_from_api


class RefreshTests(unittest.TestCase):
    def payload(self):
        return {'items': [{'slot_id': 123, 'shopno_cluster_id': 5818,
            'slot_type': 'limited', 'capacity': 2, 'occupied': 1,
            'time_from': '07:00', 'time_to': '19:00', 'couriers': [
                {'id': '11', 'shift_status': 'Вышел', 'shift_start': '2026-10-25T07:00:00+03:00',
                 'booking_date': '2026-10-24T16:00:00+03:00'}]}]}

    def test_complete_refresh_private_xlsx_and_public_feed(self):
        config = {'schema_version': 1, 'shops': [
            {'shop_id': 5818, 'scope_verified': True, 'cluster_ids': []}]}
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            with patch('refresh_dashboard.fetch', return_value=self.payload()):
                refresh(config, '2026-10-25', 'secret', '', folder/'private', folder/'feed.json')
            data = json.loads((folder/'feed.json').read_text())
            self.assertEqual(data['records'][0]['fill_percent'], 50)
            self.assertNotIn('secret', (folder/'feed.json').read_text())
            self.assertNotIn('courier_id', (folder/'feed.json').read_text())
            self.assertEqual((folder/'private/slots-2026-10-25.xlsx').stat().st_mode & 0o777, 0o600)
            from import_slots import read_export
            self.assertEqual(read_export(folder/'private/slots-2026-10-25.xlsx')[0]['booked'], 1)

    def test_failed_fetch_keeps_published_feed(self):
        config = {'schema_version': 1, 'shops': [
            {'shop_id': 5818, 'scope_verified': True, 'cluster_ids': []}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feed = root/'feed.json'
            feed.write_text('previous')
            with patch('refresh_dashboard.fetch', side_effect=RuntimeError('API HTTP 401')):
                with self.assertRaises(RuntimeError):
                    refresh(config, '2026-10-25', 'secret', '', root/'private', feed)
            self.assertEqual(feed.read_text(), 'previous')

    def test_wrong_scope_or_occupancy_rejected(self):
        raw = self.payload()
        with self.assertRaises(ValueError):
            rows_from_api('2026-10-25', 5818, 'cluster_id', 7332, raw)
        raw['items'][0]['occupied'] = 2
        with self.assertRaises(ValueError):
            rows_from_api('2026-10-25', 5818, 'shopno', 5818, raw)

    def test_new_date_keeps_history(self):
        def feed(day):
            return {'schema_version': 1, 'records': [{
                'date': day, 'shop_id': 5818, 'booked_places': 1, 'capacity': 2,
                'fill_percent': 50, 'source': 'slots_export',
                'reported_at': '2026-10-26T07:12:12+00:00'}]}
        result = merge_feed(feed('2026-10-25'), feed('2026-10-26'))
        self.assertEqual([r['date'] for r in result['records']], ['2026-10-25', '2026-10-26'])
