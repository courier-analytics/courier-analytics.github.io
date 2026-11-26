import sys,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from repair_8889_shift_metric import repair
class Repair(unittest.TestCase):
 def test_only_one_metric_changes_and_scope_is_checked(self):
  day='2026-11-26';slot={'date':day,'slot_type':'limited','capacity':2,'couriers':[{'courier_id':'1'}]}
  feed={'records':[{'shop_id':8889,'date':day,'booked_places':1,'capacity':2,'metrics':{'slot_fill':{'value':50,'numerator':1,'denominator':2,'reason':None,'basis':'limited_slot_places'},'shift_marked':{'value':None,'numerator':None,'denominator':None,'reason':'assigned_roster_not_verified','basis':None}}}]}
  obs={'date':day,'scope_config':{'shops':[{'shop_id':8889,'scope_verified':True}]},'shops':[{'shop_id':8889,'slots':[slot]}]}
  old=copy.deepcopy(feed)
  out,_,_=repair(feed,obs,{'verified':True,'courier_ids':['1','2'],'basis':'onec_connected_auto_velo_employment_3_5'},day,set())
  self.assertEqual(out['records'][0]['metrics']['shift_marked']['value'],50)
  self.assertEqual(feed,old)
  self.assertEqual(out['records'][0]['metrics']['slot_fill'],old['records'][0]['metrics']['slot_fill'])
  obs['date']='2026-11-25'
  with self.assertRaises(ValueError):repair(feed,obs,{},day,set())
