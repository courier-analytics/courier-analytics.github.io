import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from onec_courier_card import matching_row
class CardStudyTests(unittest.TestCase):
 def test_exact_name_id_and_row_index(self):
  data={'headings':['Id','Name'],'rows':[['1','Другое имя'],['123','ЖУКОВ  МАКСИМ СЕРГЕЕВИЧ']]}
  row=matching_row(data,'Жуков Максим Сергеевич')
  self.assertEqual(row['courier_id'],'123');self.assertEqual(row['row_index'],1)
 def test_duplicate_name_or_no_id_stops(self):
  for rows in [[['1','Жуков Максим'],['2','Жуков Максим']],[['','Жуков Максим']],[['1','Жуков Максимов']]]:
   with self.assertRaises(ValueError):matching_row({'headings':['Id','Name'],'rows':rows},'Жуков Максим')
if __name__=='__main__':unittest.main()
