import sys,unittest
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from attendance_early_departure import evidence
class EarlyDeparture(unittest.TestCase):
 def slot(self):return {'date':'2026-11-28','time_from':'08:00','time_to':'18:00'}
 def person(self,end):return {'shift_status':'Вышел','shift_start':'2026-11-28T08:00:00+03:00','shift_end':end}
 def test_inclusive_hour_boundary(self):
  now=datetime.fromisoformat('2026-11-28T19:00:00+03:00')
  self.assertIsNone(evidence(self.slot(),self.person('2026-11-28T17:00:01+03:00'),now))
  self.assertEqual(evidence(self.slot(),self.person('2026-11-28T17:00:00+03:00'),now)['early_departure_seconds'],3600)
 def test_missing_naive_future_or_daily_cut_never_penalized(self):
  now=datetime.fromisoformat('2026-11-28T19:00:00+03:00')
  for end in (None,'2026-11-28T17:00:00','2026-11-28T07:00:00+03:00','2026-11-29T17:00:00+03:00'):
   self.assertIsNone(evidence(self.slot(),self.person(end),now))
  slot={**self.slot(),'time_from':'20:00','time_to':'08:00'}
  person={**self.person('2026-11-28T23:59:59+03:00'),'shift_start':'2026-11-28T20:00:00+03:00'}
  self.assertIsNone(evidence(slot,person,datetime.fromisoformat('2026-11-29T09:00:00+03:00')))
 def test_overnight_end_uses_following_day(self):
  slot={**self.slot(),'time_from':'20:00','time_to':'08:00'}
  person={**self.person('2026-11-29T07:00:00+03:00'),'shift_start':'2026-11-28T20:00:00+03:00'}
  self.assertEqual(evidence(slot,person,datetime.fromisoformat('2026-11-29T09:00:00+03:00'))['early_departure_seconds'],3600)
class ApprovalSeparation(unittest.TestCase):
 def test_late_and_early_same_booking_are_distinct_cases(self):
  from attendance_review import review_rows
  slot={'date':'2026-11-28','slot_id':1,'slot_type':'limited','scope_kind':'shopno','scope_id':8889,'time_from':'08:00','time_to':'18:00',
        'couriers':[{'courier_id':'123','name':'Test Courier','shift_status':'Опоздал','shift_start':'2026-11-28T09:00:00+03:00','shift_end':'2026-11-28T17:00:00+03:00'}]}
  rows=review_rows({'shops':[{'shop_id':8889,'slots':[slot]}]},'2026-11-28',datetime.fromisoformat('2026-11-28T19:00:00+03:00'))
  self.assertEqual(len(rows),2);self.assertNotEqual(rows[0]['event_id'],rows[1]['event_id'])
  self.assertTrue(all(not r['multiple_bookings_for_courier'] for r in rows))
  self.assertEqual(rows[1]['proposed_measure'],{'operation':'set','value':1})
  slot['scope_id']=9107
  self.assertEqual(len(review_rows({'shops':[{'shop_id':9107,'slots':[slot]}]},'2026-11-28',datetime.fromisoformat('2026-11-28T19:00:00+03:00'))),1)
 def test_end_fact_changes_invalidate_approval_fingerprint(self):
  from attendance_cases import fingerprint
  row={'case_kind':'early_departure','actual_end':'2026-11-28T17:00:00+03:00'}
  self.assertNotEqual(fingerprint(row),fingerprint({**row,'actual_end':'2026-11-28T16:00:00+03:00'}))
 def test_separate_daily_claim_requires_confirmed_previous_write_and_cannot_repeat(self):
  import tempfile,json,sqlite3
  from attendance_cases import connect,claim_write
  for previous in ('applied','inflight','uncertain'):
   with tempfile.TemporaryDirectory() as folder:
    with connect(Path(folder)/'cases.db') as db:
     payload={'date':'2026-11-28','shop_id':8889,'courier_id':'123','case_kind':'early_departure','early_departure_seconds':3600,'proposed_measure':{'operation':'set','value':1}}
     db.execute('INSERT INTO cases(id,event,payload,state,actor,message_id) VALUES(?,?,?,?,?,?)',('early','early',json.dumps(payload),'approved',111,999))
     db.execute('INSERT INTO ledger VALUES(?,?,?,?)',(payload['date'],'123',previous,'late'));db.commit()
     if previous=='applied':
      claim_write(db,'early')
      self.assertEqual(db.execute("SELECT count(*) FROM ledger").fetchone()[0],2)
      db.execute("UPDATE cases SET state='approved' WHERE id='early'");db.commit()
      with self.assertRaises(sqlite3.IntegrityError):claim_write(db,'early')
     else:
      with self.assertRaises(ValueError):claim_write(db,'early')
      self.assertEqual(db.execute('SELECT state FROM cases').fetchone()[0],'approved')

 def test_overnight_case_belongs_to_actual_finish_day(self):
  from attendance_early_departure import review_rows
  slot={'date':'2026-11-28','slot_id':1,'slot_type':'limited','scope_kind':'shopno','scope_id':8889,'time_from':'20:00','time_to':'08:00',
        'couriers':[{'courier_id':'123','name':'Test Courier','shift_status':'Вышел','shift_start':'2026-11-28T20:00:00+03:00','shift_end':'2026-11-29T07:00:00+03:00'}]}
  rows=review_rows({'shops':[{'shop_id':8889,'slots':[slot]}]},'2026-11-28',datetime.fromisoformat('2026-11-29T06:00:00+00:00'))
  self.assertEqual(rows[0]['date'],'2026-11-29');self.assertEqual(rows[0]['source_date'],'2026-11-28')
 def test_message_shows_early_departure_facts_and_pool_one(self):
  from attendance_bot import message
  payload={'shop_id':8889,'date':'2026-11-28','name':'Test Courier','courier_id':'123','planned_start':'08:00','source_status':'Вышел',
           'case_kind':'early_departure','planned_end':'18:00','actual_end':'17:00','early_departure_seconds':3600}
  text=message({'payload':payload,'current_limit':8,'target_limit':1})
  self.assertIn('ранний уход',text);self.assertIn('Плановый конец: 18:00',text);self.assertIn('Фактический конец: 17:00',text)
  self.assertIn('Предлагаемый лимит: 1',text)
 def test_collect_recovers_yesterday_slot_finishing_early_today(self):
  import tempfile,json
  from unittest.mock import patch
  import attendance_bot as bot
  from attendance_cases import connect
  now=datetime.fromisoformat('2026-11-28T09:00:00+03:00')
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);token=root/'token.json';token.write_text('{"token":"fixture"}')
   slot={'date':'2026-11-27','slot_id':1,'slot_type':'limited','scope_kind':'shopno','scope_id':8889,'time_from':'20:00','time_to':'08:00',
         'couriers':[{'courier_id':'123','name':'Test Courier','shift_status':'Вышел','shift_start':'2026-11-27T20:00:00+03:00','shift_end':'2026-11-28T07:00:00+03:00'}]}
   def audit(day,token,proxy,directory,extra_details,targets):
    directory.mkdir(parents=True,exist_ok=True)
    shops=[{'shop_id':shop,'slots':[slot] if day=='2026-11-27' and shop==8889 else []} for shop in targets]
    (directory/'all-shops-observations.json').write_text(json.dumps({'shops':shops}))
    return {'shops':[{'shop_id':shop,'scope_verified':True} for shop in targets]}
   with connect(root/'cases.db') as db,patch.object(bot,'ROOT',root),patch.object(bot,'Path',side_effect=lambda value:token if value=='/root/curator-session.json' else Path(value)),patch.object(bot,'datetime') as clock,patch.object(bot,'audit',side_effect=audit),patch.object(bot,'configured_proxy',return_value=None):
    clock.now.return_value=now
    bot.collect(db,{'disabled_attendance_shops':[7745]})
    rows=db.execute('SELECT payload,state FROM cases').fetchall()
    self.assertEqual(len(rows),1);payload=json.loads(rows[0]['payload'])
    self.assertEqual(payload['date'],'2026-11-28');self.assertEqual(payload['source_date'],'2026-11-27')
    self.assertEqual(rows[0]['state'],'need_limit')
