import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from onec_courier_card import matching_row,matching_id_row,wait_for_courier_result,search_field_id,SEARCH_IDS
class CardStudyTests(unittest.TestCase):
 def test_exact_name_id_and_row_index(self):
  data={'headings':['Id','Name'],'rows':[['1','Другое имя'],['123','ЖУКОВ  МАКСИМ СЕРГЕЕВИЧ']]}
  row=matching_row(data,'Жуков Максим Сергеевич')
  self.assertEqual(row['courier_id'],'123');self.assertEqual(row['row_index'],1)
 def test_duplicate_name_or_no_id_stops(self):
  for rows in [[['1','Жуков Максим'],['2','Жуков Максим']],[['','Жуков Максим']],[['1','Жуков Максимов']]]:
   with self.assertRaises(ValueError):matching_row({'headings':['Id','Name'],'rows':rows},'Жуков Максим')
class IdSearchTests(unittest.TestCase):
 def test_id_disambiguates_same_name_without_weakening_identity(self):
  data={'headings':['Id','Name'],'rows':[['123','Одинаковое Имя'],['456','Одинаковое Имя']]}
  self.assertEqual(matching_id_row(data,'456','Одинаковое Имя')['row_index'],1)
  with self.assertRaisesRegex(ValueError,'courier_name_id_mismatch'):matching_id_row(data,'456','Другое Имя')
  with self.assertRaisesRegex(ValueError,'courier_id_not_found'):matching_id_row(data,'789','Одинаковое Имя')
class SearchControlTests(unittest.TestCase):
 def test_both_evidenced_layouts(self):
  for identity in SEARCH_IDS:
   self.assertEqual(search_field_id([{'id':'captionbarField_i0'},{'id':identity,'disabled':False,'readOnly':False}]),identity)
 def test_global_unknown_disabled_or_ambiguous_controls_rejected(self):
  for fields in [[{'id':'captionbarField_i0'}],[{'id':SEARCH_IDS[0],'disabled':True}],[{'id':SEARCH_IDS[0],'readOnly':True}],[{'id':i} for i in SEARCH_IDS]]:
   with self.assertRaises(ValueError):search_field_id(fields)
if __name__=='__main__':unittest.main()

class ResultWaitTests(unittest.TestCase):
 def test_empty_and_changing_results_are_waited_for(self):
  from unittest.mock import MagicMock,patch
  empty={'headings':['Id','Name'],'rows':[]}
  target={'headings':['Id','Name'],'rows':[['123','Тест Имя']]}
  with patch('onec_courier_card._grid',side_effect=[empty,empty,target,target]):
   data,row=wait_for_courier_result(MagicMock(),'Тест Имя','123',attempts=6)
  self.assertEqual(row['courier_id'],'123')
 def test_wrong_identity_never_opens_and_wait_is_bounded(self):
  from unittest.mock import MagicMock,patch
  page=MagicMock();wrong={'headings':['Id','Name'],'rows':[['456','Тест Имя']]}
  with patch('onec_courier_card._grid',return_value=wrong),self.assertRaisesRegex(ValueError,'courier_id_not_found'):
   wait_for_courier_result(page,'Тест Имя','123',attempts=3)
  self.assertEqual(page.wait_for_timeout.call_count,3)

class CardIdentityWait(unittest.TestCase):
 def test_exact_identity_and_name_are_required_before_readback(self):
  from unittest.mock import MagicMock
  from onec_courier_card import wait_for_card_identity
  page=MagicMock()
  wait_for_card_identity(page,'Тест Имя','123')
  call=page.wait_for_function.call_args
  self.assertEqual(call.kwargs['arg'],{'name':'Тест Имя','identity':'123'})
  self.assertEqual(call.kwargs['timeout'],20000)
  self.assertIn('Идентификатор_i0',call.args[0])
