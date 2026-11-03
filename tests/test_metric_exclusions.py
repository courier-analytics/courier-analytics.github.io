import sys,tempfile,json,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from metric_exclusions import load,views
from calculate_metrics import calculate
class ExplicitDisabledExclusionTests(unittest.TestCase):
 def test_private_exception_filters_view_without_mutating_frozen_plan_or_other_day(self):
  with tempfile.TemporaryDirectory() as d:
   folder=Path(d)/'metric-exclusions';folder.mkdir();(folder/'2026-11-03-7745.json').write_text(json.dumps({'date':'2026-11-03','shop_id':7745,'reason':'user_confirmed_disabled','courier_ids':['999999']}))
   ids=load(Path(d),'2026-11-03',7745);self.assertEqual(ids,{'999999'})
   self.assertEqual(load(Path(d),'2026-11-02',7745),set());self.assertEqual(load(Path(d),'2026-11-03',5818),set())
   slot={'date':'2026-11-03','slot_id':1,'slot_type':'limited','time_from':'07:00','time_to':'19:00','capacity':2,'couriers':[{'courier_id':'111111','shift_status':'Опоздал на 18 минут','shift_start':'2026-11-03T07:18:00+03:00','shift_end':None}]}
   plan={'verified':True,'date':'2026-11-03','slots':[{**slot,'couriers':[{'courier_id':'111111'},{'courier_id':'999999'}]}]}
   roster={'verified':True,'courier_ids':['111111','999999'],'names':{}}
   self.assertEqual(calculate([slot],'2026-11-03',roster,plan)['planned_attendance']['reason'],'planned_booking_missing_from_current_data')
   slots,population_plan,population=views([slot],plan,roster,ids)
   result=calculate(slots,'2026-11-03',population,population_plan)
   self.assertEqual(result['planned_attendance']['value'],100)
   self.assertEqual(result['planned_late']['value'],100)
   self.assertEqual(result['shift_marked']['denominator'],1)
   self.assertEqual(len(plan['slots'][0]['couriers']),2);self.assertEqual(len(roster['courier_ids']),2)
