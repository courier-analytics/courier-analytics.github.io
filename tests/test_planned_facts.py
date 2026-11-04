import unittest,sys,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from calculate_metrics import calculate
from courier_details import build

class RebookedNoShowTests(unittest.TestCase):
 def inputs(self):
  planned={'date':'2026-11-04','slot_type':'limited','slot_id':1,'scope_id':7745,'time_from':'07:00','time_to':'19:00','capacity':2,
           'couriers':[{'courier_id':'111111','name':'Test A','shift_status':'Ожидается'}]}
  other=copy.deepcopy(planned);other.update(slot_id=2,time_from='09:00',time_to='21:00')
  other['couriers']=[{'courier_id':'111111','name':'Test A','shift_status':'Не вышел','shift_start':None,'shift_end':None}]
  arrived=copy.deepcopy(planned);arrived['couriers']=[{'courier_id':'222222','shift_status':'Вышел','shift_start':'2026-11-04T07:00:00+03:00','shift_end':None}]
  plan={'verified':True,'date':planned['date'],'slots':[planned,copy.deepcopy(arrived)]}
  return plan,[arrived,other]
 def test_explicit_no_show_rebooking_keeps_original_denominator_and_reconciles_details(self):
  plan,slots=self.inputs();original=copy.deepcopy((plan,slots));m=calculate(slots,plan['date'],plan=plan)
  self.assertEqual((m['planned_attendance']['numerator'],m['planned_attendance']['denominator']),(1,2))
  self.assertEqual(m['planned_late']['value'],0)
  detail=build(plan['date'],{'shop_id':7745,'slots':slots},m,plan=plan)
  self.assertTrue(detail['metrics']['planned_attendance']['reconciled'])
  group=next(g for g in detail['metrics']['planned_attendance']['groups'] if g['title']=='Не вышли по статусу источника')
  self.assertEqual(group['couriers'][0]['slots'][0]['fact_source_slot_id'],'2')
  self.assertEqual((plan,slots),original)
 def test_absent_unknown_arrived_or_multiple_planned_bookings_are_not_guessed(self):
  for state in ['Ожидается','Вышел',None]:
   plan,slots=self.inputs();slots[1]['couriers'][0]['shift_status']=state
   self.assertEqual(calculate(slots,plan['date'],plan=plan)['planned_attendance']['reason'],'planned_booking_missing_from_current_data')
  plan,slots=self.inputs();slots.pop()
  self.assertIsNone(calculate(slots,plan['date'],plan=plan)['planned_attendance']['value'])
  plan,slots=self.inputs();plan['slots'].append(copy.deepcopy(plan['slots'][0]));plan['slots'][-1]['slot_id']=3
  self.assertIsNone(calculate(slots,plan['date'],plan=plan)['planned_attendance']['value'])

 def test_no_show_with_actual_shift_facts_or_other_conflicting_record_is_not_matched(self):
  for field in ['shift_start','shift_end']:
   plan,slots=self.inputs();slots[1]['couriers'][0][field]='2026-11-04T09:00:00+03:00'
   self.assertIsNone(calculate(slots,plan['date'],plan=plan)['planned_attendance']['value'])
  plan,slots=self.inputs();extra=copy.deepcopy(slots[1]);extra['slot_id']=4
  extra['couriers'][0]['shift_status']='Ожидается';slots.append(extra)
  self.assertIsNone(calculate(slots,plan['date'],plan=plan)['planned_attendance']['value'])

 def test_rebooked_arrival_uses_original_plan_time_and_keeps_plan_population(self):
  plan,slots=self.inputs();person=slots[1]['couriers'][0]
  person.update(shift_status='Вышел',shift_start='2026-11-04T09:00:00+03:00')
  original=copy.deepcopy((plan,slots));m=calculate(slots,plan['date'],plan=plan)
  self.assertEqual((m['planned_attendance']['numerator'],m['planned_attendance']['denominator']),(2,2))
  self.assertEqual((m['planned_late']['numerator'],m['planned_late']['denominator']),(1,2))
  d=build(plan['date'],{'shop_id':7745,'slots':slots},m,plan=plan)
  self.assertTrue(d['metrics']['planned_late']['reconciled'])
  late=next(g for g in d['metrics']['planned_late']['groups'] if g['title']=='Опоздали от 15 минут')
  self.assertEqual(late['couriers'][0]['slots'][0]['late_seconds'],7200)
  self.assertEqual((plan,slots),original)

 def test_conflicting_actual_starts_and_midnight_placeholder_do_not_match(self):
  plan,slots=self.inputs();person=slots[1]['couriers'][0]
  person.update(shift_status='Вышел',shift_start='2026-11-04T09:00:00+03:00')
  extra=copy.deepcopy(slots[1]);extra['slot_id']=3;extra['couriers'][0]['shift_start']='2026-11-04T10:00:00+03:00';slots.append(extra)
  self.assertIsNone(calculate(slots,plan['date'],plan=plan)['planned_attendance']['value'])
  slots.pop();person['shift_start']='2026-11-04T00:00:00+03:00'
  self.assertIsNone(calculate(slots,plan['date'],plan=plan)['planned_attendance']['value'])
