"""DS9107 registration, source isolation, and no invented observations."""
import ast,json,sys,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from dashboard_shops import SHOPS,TARGETS
from discover_scopes import discover
from powerbi_medical import candidate_records
from medical_feed import validate
from refresh_all_shops import refresh
from enrich_slots import atomic_json

class Dashboard9107Tests(unittest.TestCase):
 def test_catalogue_selects_exact_ds_and_its_cluster(self):
  self.assertIn(9107,TARGETS)
  cfg=discover([{'id':9107}],[{'id':10,'name':'9107 ДС'},{'id':11,'name':'19107 другой ДС'}])
  shop=next(s for s in cfg['shops'] if s['shop_id']==9107)
  self.assertEqual(shop['cluster_ids'],[10]);self.assertTrue(shop['scope_verified'])
 def test_medical_9107_is_valid_and_nearby_number_is_not_a_match(self):
  rows=[[str(s)+' ДС',10,8,2,.4] for s in (5818,7745,9107)]
  result=validate(candidate_records(rows,datetime(2026,11,19,10,tzinfo=timezone.utc)))
  self.assertEqual(result['records'][-1]['shop_id'],9107)
  self.assertEqual(result['records'][-1]['value'],60)
  rows[-1][0]='91070 другой ДС'
  result=candidate_records(rows,datetime(2026,11,19,10,tzinfo=timezone.utc))
  self.assertNotIn(9107,[r['shop_id'] for r in result['records']])
 def test_observation_enters_feed_but_names_stay_private(self):
  day='2026-11-19'
  slot={'date':day,'slot_id':9107,'slot_type':'limited','scope_kind':'shopno','scope_id':9107,
        'time_from':'07:00','time_to':'19:00','capacity':2,'occupied':1,
        'couriers':[{'courier_id':'123','name':'Private Test Name','shift_status':'Вышел',
                     'shift_start':day+'T07:00:00+03:00','shift_end':None,'booked_at':'2026-11-18T16:00:00+03:00'}]}
  def audit(day,token,proxy,folder,extra_details=False):
   folder.mkdir(parents=True,exist_ok=True)
   atomic_json(folder/'all-shops-observations.json',{'shops':[{'shop_id':9107,'slots':[slot]}]})
   return {'shops':[{'shop_id':9107}]}
  with tempfile.TemporaryDirectory() as folder:
   folder=Path(folder)
   with patch('refresh_all_shops.audit',side_effect=audit),patch('refresh_all_shops.resolve_overnight',side_effect=lambda slots,*a,**k:(slots,{})):
    refresh(day,'test','',folder/'private',folder/'feed.json')
   raw=(folder/'feed.json').read_text();feed=json.loads(raw)
   self.assertEqual(feed['records'][0]['shop_id'],9107)
   self.assertEqual(feed['records'][0]['metrics']['slot_fill']['value'],50)
   self.assertEqual(feed['records'][0]['metrics']['shift_marked']['reason'],'assigned_roster_not_verified')
   self.assertEqual(feed['records'][0]['metrics']['unplanned_work']['reason'],'frozen_plan_missing')
   self.assertNotIn('Private Test Name',raw);self.assertNotIn('courier_id',raw)
   self.assertTrue((folder/'private/details'/f'{day}-9107.json').is_file())
 def test_page_has_clean_history_and_every_picker_links_back(self):
  page=(ROOT/'9107.html').read_text()
  self.assertIn('const dates = ["19.11"]',page)
  self.assertIn('<option value="9107" selected>',page)
  self.assertNotIn('courierOpenDetails=true',page)
  for name in ['index.html','7745.html','dashboard.html','8889.html','4747.html','8092.html','9107.html']:
   text=(ROOT/name).read_text()
   self.assertIn('<option value="9107"',text)
   self.assertIn('"9107":"9107.html"',text)
  app=ast.parse((ROOT/'tools/private_web/app.py').read_text())
  node=next(n for n in app.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='FILES' for t in n.targets))
  self.assertIn('9107.html',ast.literal_eval(node.value))
if __name__=='__main__':unittest.main()
