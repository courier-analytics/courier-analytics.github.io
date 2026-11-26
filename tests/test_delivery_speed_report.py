import sys,unittest
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from delivery_speed_report import summarize
class Speed(unittest.TestCase):
 def test_per_order_average_dedup_and_missing_values(self):
  rows=[{'id_order':1,'shopno':4702,'date_order':'2026-11-19T10:00:00','date_delivery_start':'2026-11-19T10:10:00','date_delivered':'2026-11-19T10:30:00'},
        {'id_order':2,'shopno':4702,'date_order':'2026-11-20T10:00:00','date_delivery_start':None,'date_delivered':'2026-11-20T11:00:00'}]
  report=summarize(rows+[rows[0]],4702,date(2026,11,19),date(2026,11,26))
  self.assertEqual(report['successful_unique_orders'],2)
  self.assertEqual(report['metrics']['order_to_delivery']['average_minutes'],45)
  self.assertEqual(report['metrics']['courier_delivery_leg']['average_minutes'],20)
  self.assertEqual(report['metrics']['courier_delivery_leg']['missing_start'],1)
 def test_wrong_shop_and_wrong_date_rejected(self):
  row={'id_order':1,'shopno':8889,'date_delivered':'2026-11-19T10:30:00'}
  with self.assertRaises(ValueError):summarize([row],4702,date(2026,11,19),date(2026,11,26))
  row['shopno']=4702;row['date_delivered']='2026-11-26T00:00:00'
  with self.assertRaises(ValueError):summarize([row],4702,date(2026,11,19),date(2026,11,26))
 def test_diagnostic_hides_arbitrary_response_details(self):
  from unittest.mock import patch
  from delivery_speed_report import collect
  for error,reason in [(ValueError('Conflicting duplicate order'),'Conflicting duplicate order'),(ValueError('private response content'),'details_hidden')]:
   with patch('delivery_speed_report._collect',side_effect=error),patch('builtins.print') as output:
    with self.assertRaises(ValueError):collect(None,None,4702,'2026-11-19','2026-11-26')
    self.assertEqual(output.call_args.args,('Delivery report failed:','ValueError','reason='+reason))
