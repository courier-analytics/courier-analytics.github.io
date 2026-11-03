from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from onec_roster_cache import save,load,BASIS,MOSCOW
from enrich_slots import atomic_json
from refresh_all_shops import refresh

class NativeRosterCacheTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc);self.day=self.now.astimezone(MOSCOW).date().isoformat()
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.native={'verified':True,'courier_ids':['111111','222222'],'count':2}
        save(self.native,{'filters_verified':True},self.folder/'onec-rosters',self.now)
        self.path=self.folder/'onec-rosters/7745.json'
    def tearDown(self):self.temp.cleanup()
    def test_verified_snapshot_is_private_and_current(self):
        result=load(self.path,self.day,self.now)
        self.assertEqual(result['count'],2);self.assertEqual(result['basis'],BASIS)
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)
    def test_stale_future_and_historical_snapshot_rejected(self):
        for now,day in [(self.now+timedelta(hours=3),self.day),(self.now-timedelta(seconds=1),self.day),(self.now,'2020-01-01')]:
            with self.assertRaises(ValueError):load(self.path,day,now)
    def test_unverified_empty_and_duplicate_rosters_rejected(self):
        for native in [{'verified':False,'courier_ids':['111111'],'count':1},
                       {'verified':True,'courier_ids':[],'count':0},
                       {'verified':True,'courier_ids':['111111','111111'],'count':2}]:
            with self.assertRaises(ValueError):save(native,{'filters_verified':True},self.folder/'bad',self.now)
        with self.assertRaises(ValueError):save(self.native,{'filters_verified':False},self.folder/'bad',self.now)
    def test_current_native_base_wins_over_five_day_override_and_stale_has_no_fallback(self):
        def audit(day,token,proxy,directory,extra_details=False):
            directory.mkdir(parents=True,exist_ok=True)
            atomic_json(directory/'all-shops-observations.json',{'shops':[{'shop_id':7745,'slots':[{
                'date':day,'slot_id':1,'slot_type':'limited','scope_kind':'shopno','scope_id':7745,
                'time_from':'07:00','time_to':'19:00','capacity':2,
                'couriers':[{'courier_id':i,'shift_status':'Ожидается выход','shift_start':None,'shift_end':None}
                            for i in ['111111','333333']]}]}]})
            return {'shops':[{'shop_id':7745}]}
        def run():
            with patch('refresh_all_shops.audit',side_effect=audit), patch('refresh_all_shops.resolve_overnight',side_effect=lambda slots,*a:(slots,{})), patch('refresh_all_shops.collect_active_base') as old:
                result=refresh(self.day,'secret','',self.folder,self.folder/'public.json',active_base=True)
                old.assert_not_called()
            return result
        run()
        public=(self.folder/'public.json').read_text();metric=json.loads(public)['records'][0]['metrics']['shift_marked']
        self.assertEqual((metric['numerator'],metric['denominator'],metric['value'],metric['basis']),(1,2,50.0,BASIS))
        self.assertNotIn('111111',public);self.assertNotIn('courier_ids',public)
        data=json.loads(self.path.read_text());data['observed_at']=(self.now-timedelta(hours=3)).isoformat();atomic_json(self.path,data)
        run()
        metric=json.loads((self.folder/'public.json').read_text())['records'][0]['metrics']['shift_marked']
        self.assertIsNone(metric['value']);self.assertEqual(metric['reason'],'assigned_roster_not_verified')
