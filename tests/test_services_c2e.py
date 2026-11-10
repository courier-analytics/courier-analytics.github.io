import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from services_pilot import collect
from services_report_render import render
class C2ETests(unittest.TestCase):
 def test_native_metric_has_same_filters_as_other_metrics(self):
  metrics=['qty_orders_delivered','qty_couriers','share_collection_delay_all','share_all_0_sla_offline','avg_order_time']
  schema={'result':{'metrics':[{'metric_name':m} for m in metrics],'columns':[{'column_name':c} for c in ['shopno','date_supply','delivery_type_group']]}}
  with patch('services_pilot.api',return_value=(200,schema)),patch('services_pilot.private_write'),patch('services_pilot.chart_data',return_value=(200,{'result':[{'status':'success','data':[{'shopno':9107,'avg_order_time':62.23}]}]})) as query:
   collect(None,'TOKEN')
  self.assertEqual(query.call_count,2)
  for call in query.call_args_list:
   p=call.args[2];self.assertEqual(p['datasource']['id'],3035);self.assertEqual(p['queries'][0]['metrics'],metrics)
   self.assertEqual(p['queries'][0]['filters'][0]['val'],[9107])
 def test_minutes_not_percentage_and_delta_uses_previous_day(self):
  samples=[]
  for day,value in [('2026-11-08',50),('2026-11-09',62.23)]:
   samples.append({'date':day,'http_status':200,'rows':[{'shopno':9107,'qty_orders_delivered':100,'qty_couriers':5,'avg_order_time':value}]})
  result=render({'samples':samples})
  self.assertIn('62.23 мин',result);self.assertIn('↑12.2 мин',result);self.assertNotIn('6223',result)
  samples[1]['rows'][0]['avg_order_time']=None
  self.assertIn('Нет данных',render({'samples':samples}))
