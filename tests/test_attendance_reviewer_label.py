import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from attendance_bot import reviewer_label
class Labels(unittest.TestCase):
 def test_username_preferred_and_name_fallback(self):
  self.assertEqual(reviewer_label({'id':123,'username':'reviewer_1','first_name':'Иван'}),'@reviewer_1')
  self.assertEqual(reviewer_label({'id':123,'first_name':'Иван','last_name':'Иванов'}),'Иван Иванов')
  self.assertEqual(reviewer_label({'id':123}),'Участник группы')
  self.assertNotIn('\n',reviewer_label({'first_name':'Иван\nТест'}))
