import ast,json,os,sys,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import MagicMock,patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from powerbi_medical import isolated_candidate_records
class PartialRefresh(unittest.TestCase):
 def test_bad_medical_shop_does_not_drop_verified_shop_or_invent_zero(self):
  with patch('builtins.print'):
   result=isolated_candidate_records([['ДС 7745',100,90,5,.15],['ДС 8889',None,None,None,None]],datetime.now(timezone.utc),shops=(7745,8889))
  self.assertEqual([r['shop_id'] for r in result['records']],[7745])
  self.assertEqual(result['unavailable_shops'][0]['shop_id'],8889)
 def test_contact_shops_save_without_global_export_and_preserve_old_timestamp(self):
  source=(Path(__file__).resolve().parents[1]/'tools/refresh_contact_phones.py').read_text()
  function=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='capture')
  with tempfile.TemporaryDirectory() as directory:
   target=Path(directory)/'contacts.json';target.write_text(json.dumps({'verified':True,'observed_at':'2026-11-20T00:00:00+00:00','couriers':[{'id':'999','name':'old','phone':'123'}]}))
   c=MagicMock();c.fresh_list.side_effect=lambda page,shop:page
   c.roster.inspect_export_dialog.return_value={'opened':True}
   c.private_write.side_effect=lambda path,text:path.write_text(text)
   ns={'c':c,'DONE':False,'os':os,'json':json,'datetime':datetime,'timezone':timezone,'Path':lambda unused:target,
       'parse':MagicMock(side_effect=[{str(i):{'id':str(i),'name':'new','phone':'456'}} for i in (1,2,3)])}
   exec(compile(ast.Module(body=[function],type_ignores=[]),'capture','exec'),ns)
   with patch.dict(os.environ,{'COURIER_CONTACTS_GLOBAL_EXPORT':'0'}),patch('builtins.print'):ns['capture'](MagicMock(),None)
   result=json.loads(target.read_text());self.assertFalse(result['global_directory_refreshed'])
   self.assertEqual(len(result['couriers']),4);self.assertTrue(ns['DONE'])
   old=next(r for r in result['couriers'] if r['id']=='999');self.assertEqual(old['observed_at'],'2026-11-20T00:00:00+00:00')
   self.assertEqual(c.roster.export_id_list.call_count,3)
if __name__=='__main__':unittest.main()
