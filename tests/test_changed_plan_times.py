import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from calculate_metrics import calculate
from courier_details import build
class ChangedPlanTests(unittest.TestCase):
 def test_original_start_controls_aggregate_and_named_details(self):
  day='2026-11-09'
  person={'courier_id':'111111','shift_status':'Опоздал на 2 часа','shift_start':day+'T11:10:00+03:00','shift_end':day+'T23:00:00+03:00'}
  slot={'date':day,'slot_type':'limited','slot_id':1,'scope_id':7745,'time_from':'09:00','time_to':'23:00','capacity':1,'couriers':[person]}
  plan={'verified':True,'date':day,'slots':[{**slot,'time_from':'11:00'}]}
  metrics=calculate([slot],day,plan=plan)
  self.assertEqual(metrics['planned_attendance']['value'],100)
  self.assertEqual(metrics['planned_late']['value'],0)
  detail=build(day,{'shop_id':7745,'slots':[slot]},metrics,plan=plan)
  self.assertTrue(detail['metrics']['planned_late']['reconciled'])
  person['shift_start']=None
  metrics=calculate([slot],day,plan=plan)
  self.assertEqual(metrics['planned_attendance']['value'],100)
  self.assertIsNone(metrics['planned_late']['value'])
  self.assertEqual(slot['time_from'],'09:00')
  self.assertEqual(plan['slots'][0]['time_from'],'11:00')
