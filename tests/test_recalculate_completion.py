import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from recalculate_completion import run
from enrich_slots import atomic_json
from calculate_metrics import metric
from completion_reporting import BASIS

class RecalculationTests(unittest.TestCase):
 def test_history_updates_only_seven_and_preserves_other_shops_and_private_details(self):
  day='2026-11-03'
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);feed=root/'feed.json';private=root/'private'
   row={'date':day,'shop_id':7745,'source':'slots_export','reported_at':day+'T20:00:00Z','booked_places':2,'capacity':3,'fill_percent':66.67,
       'metrics':{'planned_completion':metric(1,2,basis='slot_completion_by_actual_night_end_date'),'planned_late':metric(0,1,basis='frozen_plan_unique_couriers')}}
   other={**row,'shop_id':5818};atomic_json(feed,{'schema_version':1,'records':[row,other]})
   path=private/'details'/f'{day}-7745.json'
   atomic_json(path,{'kind':'courier_metric_details','schema_version':1,'date':day,'shop_id':7745,'metrics':{'planned_late':{'note':'KEEP'}}})
   slot={'date':day,'slot_type':'limited','slot_id':1,'scope_id':7745,'capacity':3,'time_from':'08:00','time_to':'20:00',
      'couriers':[{'courier_id':'111111','name':'TEST','shift_status':'Вышел','shift_start':day+'T08:00:00+03:00','shift_end':day+'T20:00:00+03:00'},
                  {'courier_id':'222222','shift_status':'Не вышел','shift_start':None,'shift_end':None}]}
   atomic_json(private/'completion-night-state/7745.json',{'days':{}})
   with patch('recalculate_completion.collect_slots',return_value=[{'available':True,'slots':[slot],'cluster_ids':[]}]),patch('recalculate_completion.resolve',side_effect=lambda slots,*_,**kw: (slots,{})),patch('recalculate_completion.completion'):
    result=run(feed,private,'secret',None)
   self.assertEqual(len(result),1)
   payload=json.loads(feed.read_text());updated=next(r for r in payload['records'] if r['shop_id']==7745)
   self.assertEqual(updated['metrics']['planned_completion']['value'],100)
   self.assertEqual(updated['metrics']['planned_completion']['basis'],BASIS)
   self.assertEqual(updated['metrics']['planned_late'],row['metrics']['planned_late'])
   self.assertEqual(next(r for r in payload['records'] if r['shop_id']==5818),other)
   self.assertNotIn('TEST',feed.read_text())
   detail=json.loads(path.read_text());self.assertEqual(detail['metrics']['planned_late']['note'],'KEEP')
   self.assertTrue(detail['metrics']['planned_completion']['reconciled'])
 def test_unavailable_history_does_not_relabel_old_percent_as_new(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);feed=root/'feed.json'
   atomic_json(feed,{'schema_version':1,'records':[{'date':'2026-11-03','shop_id':7745,'source':'slots_export','reported_at':'2026-11-03T20:00:00Z','booked_places':1,'capacity':2,'fill_percent':50,
      'metrics':{'planned_completion':metric(1,2,basis='slot_completion_by_actual_night_end_date')}}]})
   with patch('recalculate_completion.collect_slots',side_effect=RuntimeError('PRIVATE')):
    result=run(feed,root/'private','secret',None)
   self.assertEqual(result[0]['status'],'source_unavailable');self.assertIsNone(result[0]['planned_completion']['value'])
   self.assertNotIn('PRIVATE',str(result))
