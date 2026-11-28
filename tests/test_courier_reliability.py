import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from courier_reliability import retry_allowed,age
class Recovery(unittest.TestCase):
 def test_first_attempt_allowed_and_cooldown_enforced(self):
  self.assertTrue(retry_allowed([],1000));self.assertFalse(retry_allowed([900],1000));self.assertTrue(retry_allowed([600],1000))
 def test_rolling_budget_prevents_authentication_loop(self):
  self.assertFalse(retry_allowed([100,500,900],1500));self.assertTrue(retry_allowed([100,500,900],3800))
 def test_stale_missing_and_future_heartbeats_are_not_healthy(self):
  self.assertEqual(age('1970-01-01T00:10:00+00:00',1000),400)
  self.assertEqual(age(None,1000),float('inf'))
  self.assertEqual(age('1970-01-01T01:00:00+00:00',1000),float('inf'))
class WatchSafety(unittest.TestCase):
 def test_active_vpn_is_never_restarted_and_failed_retries_are_bounded(self):
  import tempfile,json
  from unittest.mock import patch
  import courier_reliability as watch
  for status,attempts,expected in [('active',[],0),('failed',[],1),('failed',[100,500,900],0)]:
   with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);state=root/'state.json';state.write_text(json.dumps({'vpn_attempts':attempts}))
    with patch.object(watch,'ROOT',root),patch.object(watch,'STATE',state),patch.object(watch.time,'time',return_value=1500),patch.object(watch,'collect',return_value=(['vpn_unavailable'],{'managed_vpn':True,'vpn':{'ActiveState':status}})),patch.object(watch,'notify'),patch.object(watch,'run',return_value=(0,'')) as run:
     watch.main()
     self.assertEqual(run.call_count,expected)
     if expected:self.assertEqual(run.call_args.args[0],['systemctl','start','--no-block',watch.VPN])
 def test_uncertain_technical_notice_is_not_duplicated(self):
  import tempfile,json
  from unittest.mock import patch
  import courier_reliability as watch
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);config=root/'alerts.json';config.write_text('{"enabled":true,"chat_id":-100123}')
   with patch.object(watch,'ALERTS',config),patch.object(watch,'STATE',root/'state.json'),patch('late_bot_group.load_token',return_value='hidden'),patch('late_bot_group.api',side_effect=RuntimeError('network')) as api:
    state={};watch.notify(state,['vpn_unavailable'],1500);watch.notify(state,['vpn_unavailable'],1600)
    self.assertEqual(api.call_count,1);self.assertEqual(state['notice_delivery'],'uncertain')
class HeldCaseMonitoring(unittest.TestCase):
 def test_failed_reads_stay_visible_after_leaving_queue(self):
  import tempfile,json,sqlite3
  from datetime import datetime
  from unittest.mock import patch
  import courier_reliability as watch
  now=1806400000
  day=datetime.fromtimestamp(now,watch.TZ).date().isoformat()
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);config=root/'config.json';config.write_text(json.dumps({'disabled_attendance_shops':[7745]}))
   database=root/'cases.sqlite3'
   with sqlite3.connect(database) as db:
    db.execute('CREATE TABLE meta(key TEXT,value TEXT)')
    stamp=datetime.fromtimestamp(now,watch.TZ).isoformat()
    db.executemany('INSERT INTO meta VALUES(?,?)',[('last_loop',stamp),('last_source_success',stamp)])
    db.execute('CREATE TABLE cases(id TEXT,payload TEXT,state TEXT,read_attempts INT)')
    for identity,shop,status,attempts in [('failed',8889,'held',3),('smaller_pool',9107,'held',0),('disabled',7745,'uncertain',1)]:
     db.execute('INSERT INTO cases VALUES(?,?,?,?)',(identity,json.dumps({'date':day,'shop_id':shop}),status,attempts))
   with patch.object(watch,'Path',side_effect=[config,database]),patch.object(watch,'MODE',root/'absent'),patch.object(watch,'service',return_value={'ActiveState':'active'}):
    state={};issues,details=watch.collect(state,now)
   self.assertEqual(issues,['reads_held'])
   self.assertEqual(state['pending_since'],{})
   self.assertEqual(details['today_states'],{'held':2})
