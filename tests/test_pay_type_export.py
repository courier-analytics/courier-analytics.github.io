import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from pay_type_export import collect


def answer(rows):return (200,{'result':[{'status':'success','data':rows}]})

class PayExportTests(unittest.TestCase):
    @patch('pay_type_export.private_write')
    @patch('pay_type_export.chart_data')
    def test_verified_export_and_explicit_date_scope(self,api,write):
        api.side_effect=[answer([{'source_rows':2}]),answer([{'id_order':1},{'id_order':2}]),answer([{'source_rows':2}])]
        collect(None,'PRIVATE',[123])
        saved=json.loads(write.call_args.args[1])
        self.assertEqual(saved['received'],2)
        self.assertTrue(saved['complete'])
        for call in api.call_args_list:
            q=call.args[2]['queries'][0]
            self.assertEqual(q['granularity'],'date_supply')
            self.assertEqual(q['filters'][1]['val'],[123])
            self.assertNotIn('PRIVATE',json.dumps(q))

    @patch('pay_type_export.private_write')
    @patch('pay_type_export.chart_data')
    def test_truncation_keeps_previous_file_unchanged(self,api,write):
        api.side_effect=[answer([{'source_rows':2}]),answer([])]
        with self.assertRaises(ValueError):collect(None,None,[123])
        write.assert_not_called()

    @patch('pay_type_export.chart_data')
    def test_invalid_scope_never_queries_source(self,api):
        for ids in ([],[0],[-1],['123']):
            with self.assertRaises(ValueError):collect(None,None,ids)
        api.assert_not_called()
