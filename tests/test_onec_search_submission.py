import sys,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from onec_courier_card import clear_known_list_filters,submit_scoped_search
class Search(unittest.TestCase):
 def test_filter_callbacks_are_waited_for_and_all_visible_flags_rechecked(self):
  page=Mock();control=Mock();page.locator.return_value=control
  control.count.return_value=1;control.is_visible.return_value=True;control.evaluate.return_value=True
  clear_known_list_filters(page)
  self.assertEqual(control.click.call_count,5)
  self.assertEqual(page.wait_for_function.call_count,6)
  self.assertEqual(len(page.wait_for_function.call_args.kwargs['arg']),5)
 def test_unchanged_disabled_filters_are_not_clicked(self):
  page=Mock();control=page.locator.return_value;control.count.return_value=1;control.is_visible.return_value=True;control.evaluate.return_value=False
  clear_known_list_filters(page);control.click.assert_not_called()
 def test_search_commits_then_checks_exact_shop_and_query(self):
  page=Mock();search=Mock();point=Mock()
  search.get_attribute.return_value='form0_ПолеПоиска_i0';search.input_value.return_value='123';point.input_value.return_value='8889'
  submit_scoped_search(page,search,point,'123',8889)
  self.assertEqual([c.args[0] for c in search.press.call_args_list][-2:],['Enter','Tab'])
  self.assertEqual(page.wait_for_function.call_args.kwargs['arg'],{'search':'form0_ПолеПоиска_i0','query':'123','shop':'8889'})
 def test_changed_shop_aborts_even_if_search_matches(self):
  page=Mock();search=Mock();point=Mock();search.input_value.return_value='123';point.input_value.return_value='7745'
  with self.assertRaises(ValueError):submit_scoped_search(page,search,point,'123',8889)

 def test_id_search_requires_blank_point_and_exact_query(self):
  page=Mock();search=Mock();point=Mock()
  search.get_attribute.return_value='form0_ПолеПоиска_i0';search.input_value.return_value='1800050823';point.input_value.return_value=''
  submit_scoped_search(page,search,point,'1800050823',None)
  self.assertEqual(page.wait_for_function.call_args.kwargs['arg']['shop'],'')
  point.input_value.return_value='8889'
  with self.assertRaises(ValueError):submit_scoped_search(page,search,point,'1800050823',None)
