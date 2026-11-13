import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from matryoshka_history import history_payload, collect

ROWS = [{'id_courier': 123, 'courier_kontr': None, 'id_courier_kontr': None},
        {'id_courier': 456, 'courier_kontr': 'Partner', 'id_courier_kontr': '001'}]

class HistoryTests(unittest.TestCase):
    def test_history_does_not_reset_at_shop_or_type_change(self):
        queries = history_payload(ROWS)['queries']
        self.assertEqual(queries[0]['filters'], [{'col': 'id_courier', 'op': 'IN', 'val': [123]}])
        self.assertEqual(queries[1]['filters'], [])
        self.assertNotIn('time_range', queries[0])
        self.assertIn('qty_orders_delivered', queries[0]['metrics'])

    def test_empty_candidates_do_not_query_entire_company(self):
        with self.assertRaises(ValueError):
            history_payload([])

    @patch('matryoshka_history.private_write')
    @patch('matryoshka_history.chart_data')
    def test_partial_or_truncated_history_is_not_saved(self, chart, write):
        for blocks in ([], [{'data': [{'id_courier': 123}] * 1001}, {'data': []}, {'data': []}]):
            chart.return_value = (200, {'result': blocks})
            with self.assertRaises(ValueError):
                collect(None, None, {'rows': ROWS}, {})
        write.assert_not_called()
