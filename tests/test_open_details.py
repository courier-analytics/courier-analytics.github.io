import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from open_details import export
class OpenDetailsTests(unittest.TestCase):
 def test_only_authorized_shop_and_display_fields(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'2026-11-09-7745.json'
   p.write_text(json.dumps({'kind':'courier_metric_details','date':'2026-11-09','shop_id':7745,'generated_at':'2026-11-09T12:00:00Z','metrics':{'planned_late':{'groups':[{'title':'Late','couriers':[{'name':'TEST','courier_id':'111111','phone':'SECRET','token':'SECRET','slots':[]}]}]},'medical':{'note':'PRIVATE'}}}))
   payload=export(d)
   self.assertIn('TEST',str(payload));self.assertNotIn('SECRET',str(payload));self.assertNotIn('medical',str(payload))
   data=json.loads(p.read_text());data['shop_id']=5818;p.write_text(json.dumps(data))
   with self.assertRaises(ValueError):export(d)
 def test_empty_input_cannot_erase_published_details(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):export(d)
