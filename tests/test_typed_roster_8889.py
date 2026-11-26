import sys,unittest,tempfile,json
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from typed_roster_8889 import normalize,load_for_day
class TypedRoster(unittest.TestCase):
 def setUp(self):
  self.now=datetime(2026,11,26,10,tzinfo=timezone.utc)
  self.data={'8889':{'shop_id':8889,'verified':True,'connected_only':True,'observed_at':self.now.isoformat(),'couriers':[{'courier_id':str(i),'courier_type_name':t,'employment_type':e} for i,t,e in [(1,'Авто',3),(2,'Вело',5),(3,'Мобильный Авто Курьер',3),(4,'Авто',1),(5,'Матрешка Авто',3)]]}}
 def test_exact_requested_policy(self):
  self.assertEqual(normalize(self.data,'2026-11-26',self.now)['courier_ids'],['1','2'])
 def test_no_stale_unverified_or_backdated_roster(self):
  with self.assertRaises(ValueError):normalize(self.data,'2026-11-25',self.now)
  self.data['8889']['observed_at']='2026-11-20T10:00:00+00:00'
  with self.assertRaises(ValueError):normalize(self.data,'2026-11-26',self.now)
 def test_archive_roundtrip(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);source=root/'source.json';source.write_text(json.dumps(self.data))
   roster=load_for_day(root,'2026-11-26',self.now,source)
   self.assertEqual(roster['count'],2)
   later=datetime(2026,11,27,10,tzinfo=timezone.utc)
   self.assertEqual(load_for_day(root,'2026-11-26',later,source)['courier_ids'],['1','2'])

class TypedMetric(unittest.TestCase):
 def test_counts_only_selected_ids_and_deduplicates_bookings(self):
  from calculate_metrics import calculate
  slot={'date':'2026-11-26','slot_type':'limited','capacity':5,'couriers':[{'courier_id':i} for i in ['1','1','3']]}
  result=calculate([slot],'2026-11-26',roster={'verified':True,'courier_ids':['1','2'],'basis':'onec_connected_auto_velo_employment_3_5'})
  self.assertEqual(result['shift_marked']['value'],50)
  self.assertEqual(result['shift_marked']['numerator'],1)
  self.assertEqual(result['shift_marked']['denominator'],2)

class RefreshIntegration(unittest.TestCase):
 def test_verified_8889_roster_is_not_overwritten_by_schedule_base(self):
  from unittest.mock import patch
  from enrich_slots import atomic_json
  from refresh_all_shops import refresh
  def audit(day,token,proxy,directory,extra_details=False):
   directory.mkdir(parents=True,exist_ok=True)
   atomic_json(directory/'all-shops-observations.json',{'shops':[{'shop_id':8889,'slots':[{'date':day,'slot_id':1,'slot_type':'limited','scope_kind':'shopno','scope_id':8889,'time_from':'07:00','time_to':'19:00','capacity':2,'couriers':[{'courier_id':'1','shift_status':'Вышел','shift_start':day+'T07:00:00+03:00','shift_end':None,'booked_at':'2026-11-25T16:00:00+03:00'}]}]}]})
   return {'shops':[{'shop_id':8889}]}
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   with patch('refresh_all_shops.audit',side_effect=audit),patch('refresh_all_shops.resolve_overnight',side_effect=lambda slots,*a,**kw:(slots,{})),patch('typed_roster_8889.load_for_day',return_value={'verified':True,'courier_ids':['1','2'],'basis':'onec_connected_auto_velo_employment_3_5'}),patch('refresh_all_shops.collect_active_base') as active:
    refresh('2026-11-26','fixture','',root/'private',root/'feed.json',active_base=True)
   self.assertFalse(active.called)
   metric=json.loads((root/'feed.json').read_text())['records'][0]['metrics']['shift_marked']
   self.assertEqual(metric['value'],50)
   self.assertEqual(metric['basis'],'onec_connected_auto_velo_employment_3_5')
