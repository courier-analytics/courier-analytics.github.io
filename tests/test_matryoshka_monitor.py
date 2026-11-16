import json
import sqlite3
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from matryoshka_monitor_source import collect, start_condition
from run_matryoshka_monitor import deliver, notices

class MonitorTests(unittest.TestCase):
    def test_delivery_ack_survives_restart(self):
        db = sqlite3.connect(':memory:')
        sent = []
        sender = lambda text: sent.append(text) or 42
        event = {'event_id': 'a', 'text': 'test'}
        self.assertEqual(deliver(db, [event], sender), 1)
        self.assertEqual(deliver(db, [event], sender), 0)
        self.assertEqual(sent, ['test'])

    def test_uncertain_delivery_is_never_automatically_repeated(self):
        db = sqlite3.connect(':memory:')
        def fail(text): raise TimeoutError()
        event = {'event_id': 'a', 'text': 'test'}
        with self.assertRaises(RuntimeError): deliver(db, [event], fail)
        self.assertEqual(deliver(db, [event], lambda text: self.fail('duplicate')), 0)
        self.assertEqual(db.execute('SELECT status FROM deliveries').fetchone()[0], 'uncertain')

    def test_started_and_threshold_notice_deduplicate_independently(self):
        now = datetime.fromisoformat('2026-11-16T12:00:00+03:00')
        person = {'courier_id':'123', 'enrollment_id':'A', 'enrolled_at':'2026-11-13T12:00:00+03:00',
                  'name':'TEST', 'last_shop':8889, 'current_type':24, 'current_type_verified':True,
                  'count_scope':'delivered_since_enrollment', 'delivered_orders':10}
        snapshot = {'verified':True, 'observed_at':now.isoformat(), 'participants':[person]}
        first = notices(snapshot, now)
        self.assertEqual(len(first), 1)
        person['delivered_orders'] = 100
        later = notices(snapshot, now)
        self.assertEqual(len(later), 2)
        self.assertEqual(first[0]['event_id'], later[0]['event_id'])
        self.assertIn('24 → 25', later[1]['text'])

    def test_program_start_cannot_be_sql_injected_or_before_launch(self):
        for row in ({'id_courier':'1 OR 1=1','program_first_order':'2026-11-13 12:00:00'},
                    {'id_courier':1,'program_first_order':"2026-11-13';--"},
                    {'id_courier':1,'program_first_order':'2026-11-12 12:00:00'}):
            with self.assertRaises(ValueError): start_condition([row])

    @patch('matryoshka_monitor_source.private_write')
    @patch('matryoshka_monitor_source.fetch')
    def test_counts_continue_across_shop_and_type_changes(self, fetch, write):
        fetch.side_effect = [[{'id_courier':123}],
          [{'id_courier':123,'program_first_order':'2026-11-13 12:00:00'}],
          [{'id_courier':123,'qty_orders_delivered':305,'observed_type':'25',
            'courier_name':'TEST','last_shop':7745,'last_delivery':'2026-11-16 11:00:00'}]]
        collect(None, None)
        queries = [call.args[2]['queries'][0] for call in fetch.call_args_list]
        self.assertNotIn('shopno', str(queries[1]['filters']))
        self.assertNotIn('shopno', str(queries[2]['filters']))
        self.assertNotIn('id_courier_type IN', queries[2]['extras']['where'])
        snapshot = json.loads(write.call_args.args[1])
        self.assertEqual(snapshot['participants'][0]['delivered_orders'], 305)

    @patch('matryoshka_monitor_source.private_write')
    @patch('matryoshka_monitor_source.fetch', return_value=[])
    def test_empty_cohort_is_saved_without_unbounded_queries(self, fetch, write):
        collect(None,None)
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(json.loads(write.call_args.args[1])['participants'],[])
