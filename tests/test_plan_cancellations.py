import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from plan_cancellations import collect
from calculate_metrics import calculate
from courier_details import build

class CancellationTests(unittest.TestCase):
 def setUp(self):
  self.day='2026-11-05'
  self.slot={'date':self.day,'slot_type':'limited','slot_id':123,'scope_kind':'shopno','scope_id':7745,'capacity':2,
    'time_from':'08:00','time_to':'20:00','couriers':[{'courier_id':'111111'},{'courier_id':'222222'}]}
  self.plan={'verified':True,'date':self.day,'captured_at':'2026-11-04T23:59:50+03:00','slots':[self.slot]}
  self.current=[{**self.slot,'couriers':[{'courier_id':'222222','name':'TEST_B','shift_status':'Вышел',
    'shift_start':self.day+'T08:20:00+03:00','shift_end':None}]}]
  self.person={'id':'111111','fio':'TEST_A','date_start':'2026-11-04T16:25:00+03:00',
    'date_end':self.day+'T07:15:02+03:00','deleted_by':'TEST_ACTOR','phone':'PRIVATE_PHONE'}
  self.history={'items':[{'slot_id':123,'date':self.day,'shopno':7745,'time_from':'08:00','time_to':'20:00','couriers':[self.person]}]}
 def collect(self):
  with patch('plan_cancellations.api_get',return_value=self.history) as request:
   rows=collect(self.day,7745,self.plan,self.current,'secret','proxy')
   self.assertEqual(request.call_count,1)
   return rows
 def test_confirmed_removal_unblocks_attendance_and_lateness_without_changing_frozen_plan(self):
  before=copy.deepcopy((self.plan,self.current,self.history))
  cancelled=self.collect();self.assertEqual(len(cancelled),1)
  self.assertNotIn('PRIVATE_PHONE',str(cancelled))
  plan={**self.plan,'cancellations':cancelled}
  m=calculate(self.current,self.day,plan=plan)
  self.assertEqual((m['planned_attendance']['numerator'],m['planned_attendance']['denominator']),(1,2))
  self.assertEqual((m['planned_late']['numerator'],m['planned_late']['denominator']),(1,1))
  details=build(self.day,{'shop_id':7745,'slots':self.current},m,plan=plan)
  attendance=details['metrics']['planned_attendance'];self.assertTrue(attendance['reconciled'])
  groups={g['title']:g for g in attendance['groups']}
  self.assertEqual(groups['Не вышли по статусу источника']['count'],0)
  self.assertEqual(groups['Нет подтверждённых данных']['count'],0)
  removed=groups['Снятые смены — история']['couriers'][0]
  self.assertEqual(removed['name'],'TEST_A');self.assertEqual(removed['slots'][0]['removed_by'],'TEST_ACTOR')
  self.assertEqual(removed['slots'][0]['removed_at'],self.person['date_end'])
  self.assertTrue(details['metrics']['planned_late']['reconciled'])
  self.assertEqual(before,(self.plan,self.current,self.history))
 def test_missing_history_is_not_assumed_to_be_cancellation(self):
  for change in ({'date_end':None},{'date_end':'2026-11-04T21:00:00+03:00'},
      {'date_start':'2026-11-05T00:10:00+03:00'},{'date_end':'2099-11-05T07:15:00+03:00'}):
   with self.subTest(change=change):
    self.history['items'][0]['couriers']=[{**self.person,**change}]
    self.assertEqual(self.collect(),[])
  with patch('plan_cancellations.api_get',side_effect=RuntimeError('private detail')):
   self.assertEqual(collect(self.day,7745,self.plan,self.current,'secret','proxy'),[])
  self.assertEqual(calculate(self.current,self.day,plan=self.plan)['planned_attendance']['reason'],'planned_booking_missing_from_current_data')
 def test_wrong_scope_times_and_ambiguous_history_do_not_match(self):
  original=copy.deepcopy(self.history)
  for field,value in [('date','2026-11-04'),('shopno',5818),('time_from','09:00'),('slot_id',124)]:
   self.history=copy.deepcopy(original);self.history['items'][0][field]=value
   self.assertEqual(self.collect(),[])
  self.history=copy.deepcopy(original);self.history['items'].append(copy.deepcopy(self.history['items'][0]))
  self.assertEqual(self.collect(),[])
 def test_actual_rebooked_arrival_takes_precedence_and_removal_is_still_visible(self):
  self.current.append({**self.slot,'slot_id':124,'couriers':[{'courier_id':'111111','shift_status':'Вышел',
    'shift_start':self.day+'T08:00:00+03:00','shift_end':None}]})
  plan={**self.plan,'cancellations':self.collect()}
  m=calculate(self.current,self.day,plan=plan)
  self.assertEqual(m['planned_attendance']['value'],100)
  self.assertEqual(m['planned_late']['value'],50)
  detail=build(self.day,{'shop_id':7745,'slots':self.current},m,plan=plan)
  self.assertEqual(detail['metrics']['planned_attendance']['groups'][-1]['count'],1)
 def test_multiple_actual_starts_remain_unresolved_despite_removal_history(self):
  for identity,hour in [(124,'08'),(125,'09')]:
   self.current.append({**self.slot,'slot_id':identity,'couriers':[{'courier_id':'111111','shift_status':'Вышел',
    'shift_start':self.day+'T'+hour+':00:00+03:00','shift_end':None}]})
  plan={**self.plan,'cancellations':self.collect()}
  self.assertIsNone(calculate(self.current,self.day,plan=plan)['planned_attendance']['value'])
 def test_present_booking_and_missing_capture_do_not_fetch_history(self):
  for plan,current in [(self.plan,[self.slot]),({**self.plan,'captured_at':None},self.current)]:
   with patch('plan_cancellations.api_get') as request:
    self.assertEqual(collect(self.day,7745,plan,current,'secret','proxy'),[]);request.assert_not_called()
 def test_refresh_collects_history_and_keeps_names_only_in_private_details(self):
  import tempfile,json
  from enrich_slots import atomic_json
  from refresh_all_shops import refresh
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);private=root/'private';feed=root/'feed.json'
   atomic_json(private/'plans'/('plan-'+self.day+'.json'),{'verified':True,'date':self.day,
    'completed_at':self.plan['captured_at'],'shops':[{'shop_id':7745,'slots':[self.slot]}]})
   def audit(day,token,proxy,folder,**kwargs):
    atomic_json(folder/'all-shops-observations.json',{'shops':[{'shop_id':7745,'slots':self.current}]})
    return {}
   with patch('refresh_all_shops.audit',side_effect=audit),patch('refresh_all_shops.resolve_overnight',side_effect=lambda slots,*_,**kw: (slots,{})),patch('plan_cancellations.api_get',return_value=self.history):
    refresh(self.day,'secret',None,private,feed)
   public=json.loads(feed.read_text());metric=public['records'][0]['metrics']['planned_attendance']
   self.assertEqual((metric['numerator'],metric['denominator']),(1,2))
   self.assertNotIn('TEST_ACTOR',feed.read_text());self.assertNotIn('TEST_A',feed.read_text());self.assertNotIn('courier_id',feed.read_text())
   detail=json.loads((private/'details'/f'{self.day}-7745.json').read_text())
   self.assertTrue(detail['metrics']['planned_attendance']['reconciled'])
   self.assertIn('TEST_ACTOR',str(detail))
