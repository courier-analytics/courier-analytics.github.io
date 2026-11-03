from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from courier_details import build
from calculate_metrics import calculate
class NamedDetailTests(unittest.TestCase):
    def test_groups_match_aggregates_and_exclude_unneeded_personal_fields(self):
        day='2026-11-03'
        people=[{'courier_id':'111111','name':'TEST_ONE','shift_status':'Опоздал на 18 минут','shift_start':day+'T07:18:00+03:00','shift_end':day+'T19:00:00+03:00','phone':'PRIVATE_PHONE'},
                {'courier_id':'222222','name':'TEST_TWO','shift_status':'Не вышел','shift_start':None,'shift_end':None}]
        slot={'date':day,'slot_id':1,'slot_type':'limited','time_from':'07:00','time_to':'19:00','capacity':3,'couriers':people,'scope_id':7745}
        plan={'verified':True,'date':day,'slots':[{**slot,'couriers':[{'courier_id':'111111'},{'courier_id':'222222'}]}]}
        roster={'verified':True,'courier_ids':['111111','333333'],'names':{'333333':'TEST_THREE'}}
        metrics=calculate([slot],day,roster,plan)
        detail=build(day,{'shop_id':7745,'slots':[slot]},metrics,roster,plan)
        marked=detail['metrics']['shift_marked'];self.assertTrue(marked['reconciled'])
        self.assertEqual([g['count'] for g in marked['groups']],[1,1,1])
        self.assertEqual(marked['groups'][1]['couriers'][0]['name'],'TEST_THREE')
        late=detail['metrics']['planned_late'];self.assertTrue(late['reconciled'])
        self.assertEqual(late['groups'][0]['couriers'][0]['slots'][0]['late_seconds'],1080)
        self.assertNotIn('PRIVATE_PHONE',str(detail));self.assertNotIn("'phone'",str(detail))
    def test_name_export_parses_only_allowed_columns(self):
        from onec_roster import verify_id_export
        export={'confirmed':True,'columns':['Id','Name'],'only_selected':False,'documents':{'text_fields':[{'text':'Id\tName\n111111\tTEST_NAME\n222222\tOTHER_NAME\n'}]}}
        result=verify_id_export(export,['111111'])
        self.assertTrue(result['verified']);self.assertEqual(result['names']['111111'],'TEST_NAME')
        export['documents']['text_fields'][0]['text']='Id\tName\tPhone\n111111\tTEST_NAME\tPRIVATE_PHONE'
        self.assertFalse(verify_id_export(export,[])['verified'])
