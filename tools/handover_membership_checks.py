import sys,types,json,tempfile,unittest
from pathlib import Path
from datetime import datetime
stub=types.ModuleType('enrich_slots')
def atomic_json(path,data):
    path.write_text(json.dumps(data))
stub.atomic_json=atomic_json
sys.modules['enrich_slots']=stub
import live_card_sync as sync
from core import hourly
DAY='2026-11-18'
def row(key,cid='1',start='08:00',end='20:00',day=DAY):
 return dict(key=key,courier_id=cid,day=day,start=f'{day}T{start}:00+03:00',end=f'{day}T{end}:00+03:00',name='Courier',slot=start+'–'+end,phone='',source_status='expected')
class TestMembership(unittest.TestCase):
 def test_removed_and_changed_slot_dropped(self):
  old=row('old');new=row('new')
  display,window=sync.visible_records({'day':DAY,'rows':[old]},[new],[old],['old'],24)
  self.assertEqual([r['key'] for r in display],['new'])
  self.assertEqual(hourly(DAY,window,{})[8][2],1)
 def test_frozen_plan_not_resurrected(self):
  display,window=sync.visible_records({'day':DAY,'rows':[row('old')]},[],[],[],24)
  self.assertEqual(display,[]);self.assertEqual(window,[])
 def test_same_person_two_real_slots_count_once(self):
  live=[row('a'),row('b')]
  display,window=sync.visible_records({'day':DAY,'rows':[]},live,[],[],24)
  self.assertEqual(len(display),2);self.assertEqual(hourly(DAY,window,{})[8][2],1)
 def test_carry_in_in_hourly_not_today_list(self):
  prev=row('prev',start='23:00',end='23:59',day='2026-11-17');prev['end']=DAY+'T09:00:00+03:00'
  display,window=sync.visible_records({'day':DAY,'rows':[]},[prev],[],[],24)
  self.assertEqual(display,[]);self.assertEqual(hourly(DAY,window,{})[8][2],1)
 def test_unchanged_order_preserved(self):
  live=[row('a','1'),row('b','2')]
  display,_=sync.visible_records({'day':DAY,'rows':[]},live,live,['b','a'],24)
  self.assertEqual([r['key'] for r in display],['b','a'])
 def test_rewrite_notes_follow_keys_and_removed_values_cleared(self):
  from unittest.mock import patch
  old=[row('a','1'),row('b','2'),row('c','3')];live=[old[1],row('d','4')]
  class Sheets:
   def __init__(self):self.batches=[]
   def call(self,method,path,body=None):
    if path.startswith('?fields='):return {'sheets':[{'properties':{'title':'card','sheetId':1}}]}
    if path=='/developerMetadata:search':return {'matchedDeveloperMetadata':[{'developerMetadata':{'location':{'dimensionRange':{'sheetId':1,'startIndex':40}}}}]}
    if 'M4' in path:return {'values':[['a'],['b'],['c']]}
    if 'F4' in path:return {'values':[['note a','comment a'],['note b','comment b'],['note c','comment c']]}
    raise AssertionError(path)
   def batch(self,req):self.batches.append(req)
   def put(self,title,display,*args):self.display=display
  with tempfile.TemporaryDirectory() as tmp,patch.object(sync,'split_existing_card'),patch.object(sync,'_backup_once') as backup:
   sheets=Sheets();p={'day':DAY,'rows':old,'captured_at':DAY+'T00:00:00+03:00'}
   sync.sync_live_card(sheets,'card',p,live,{},hourly(DAY,live,{}),'',tmp)
   backup.assert_called_once_with(sheets,'card',1,force=True)
   req=sheets.batches[0];body=next(r['updateCells']['rows'] for r in req if 'updateCells' in r and r['updateCells']['start']['columnIndex']==0)
   vals=lambda i:[v['userEnteredValue'].get('stringValue',v['userEnteredValue'].get('numberValue')) for v in body[i]['values']]
   self.assertEqual(vals(0)[5:],['note b','comment b']);self.assertEqual(vals(1)[5:],['','']);self.assertEqual(vals(2),['']*7)
   # State retains removed-key lookup so an interrupted write can be retried.
   saved=json.loads((Path(tmp)/'display-plans'/(DAY+'.json')).read_text())
   self.assertIn('a',[r['key'] for r in saved['rows']])


class TestSheetsQuota(unittest.TestCase):
 def call_method(self):
  import ast
  from unittest.mock import Mock
  tree=ast.parse(Path(__file__).with_name('runner.py').read_text())
  cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Sheets')
  method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='call')
  clock=types.SimpleNamespace(sleep=Mock(),monotonic=lambda:0)
  ns={'clock':clock,'BASE':'https://example.invalid'}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'call','exec'),ns)
  return ns['call'],clock
 def test_quota_retries_rejected_request(self):
  from unittest.mock import Mock
  call,clock=self.call_method()
  obj=types.SimpleNamespace(session=Mock())
  obj.session.request.side_effect=[types.SimpleNamespace(status_code=429,headers={},ok=False),types.SimpleNamespace(status_code=200,ok=True,json=lambda:{'ok':True})]
  self.assertEqual(call(obj,'POST',':batchUpdate',{}),{'ok':True})
  clock.sleep.assert_any_call(65)
 def test_quota_retry_bounded(self):
  from unittest.mock import Mock
  call,_=self.call_method();obj=types.SimpleNamespace(session=Mock())
  obj.session.request.return_value=types.SimpleNamespace(status_code=429,headers={},ok=False)
  with self.assertRaisesRegex(RuntimeError,'sheets_http_429'):call(obj,'GET','')
  self.assertEqual(obj.session.request.call_count,4)
 def test_ambiguous_write_failure_not_retried(self):
  from unittest.mock import Mock
  call,_=self.call_method();obj=types.SimpleNamespace(session=Mock())
  obj.session.request.return_value=types.SimpleNamespace(status_code=500,ok=False)
  with self.assertRaisesRegex(RuntimeError,'sheets_http_500'):call(obj,'POST',':batchUpdate',{})
  self.assertEqual(obj.session.request.call_count,1)
if __name__=='__main__':unittest.main()
