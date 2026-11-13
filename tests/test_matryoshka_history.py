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
        self.assertEqual(queries[1]['filters'], queries[0]['filters'])
        for q in queries:
            self.assertEqual(q['granularity'], 'date_supply')
            self.assertIn(' : ', q['time_range'])
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
        self.assertTrue(all('history-error.json' in str(call.args[0]) for call in write.call_args_list))

    def test_explicit_window_overrides_dataset_one_day_default(self):
        queries = history_payload(ROWS, '2026-11-13T17:03:31+03:00')['queries']
        for q in queries:
            self.assertEqual(q['time_range'], '2024-11-06T17:03:31 : 2026-11-13T17:03:31')

    def test_leap_day_window(self):
        q = history_payload(ROWS, '2024-02-29T12:00:00+03:00')['queries'][0]
        self.assertTrue(q['time_range'].startswith('2022-02-21T12:00:00'))

    def test_diagnostic_does_not_expose_server_message(self):
        from matryoshka_history import response_diagnostic
        result = response_diagnostic(400, {'message': 'SECRET SQL syntax error'})
        self.assertTrue(result['sql_error_reported'])
        self.assertNotIn('SECRET', str(result))
