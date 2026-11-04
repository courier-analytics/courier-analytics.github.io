import importlib.util,sys,unittest,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from onec_filters import restore_values,type_codes,PREFIX
from onec_browser import ensure_roster_filters,roster_filter_structure,capture_interface

@unittest.skipUnless(importlib.util.find_spec('playwright') and Path('/usr/lib/chromium/chromium').exists(),'Optional Chromium integration')
class SavedFilterValuesTests(unittest.TestCase):
 def setUp(self):
  from playwright.sync_api import sync_playwright
  self.p=sync_playwright().start();self.browser=self.p.chromium.launch(executable_path='/usr/lib/chromium/chromium',headless=True,args=['--no-sandbox']);self.page=self.browser.new_page()
  self.page.set_content('<style>.checkbox{display:inline-block;width:20px;height:20px}.gridBody{min-height:40px}</style><div id="mainSurface"><input id="form0_НомерТочки_i0" value="7745"><div id="grid_form0_Список"><div class="gridBody"><div class="gridLineEmpty"></div></div></div></div>')
  self.page.evaluate('''(prefix)=>{
    window.actions=0;window.types=['1 - Ночной авто курьер','20 - Ночной вело свой','7 - Ночной Вело Курьер'];
    for(const n of [4,5,6,7,8]){const e=document.createElement('div');e.id=prefix+n+'Использование';e.className='checkbox '+([4,5,7].includes(n)?'select':'');e.onclick=()=>{window.actions++;e.classList.toggle('select')};document.body.append(e)}
    function choice(base,value,options){
      const f=document.createElement('input');f.id=base+'_i0';f.value=value;f.readOnly=true;document.body.append(f);
      const p=document.createElement('div');p.hidden=true;document.body.append(p);
      for(const title of options){const e=document.createElement('div');e.textContent=title;e.onclick=()=>{window.actions++;f.value=title;p.hidden=true};p.append(e)}
      const b=document.createElement('button');b.id=base+'_DLB';b.textContent='Select';b.onclick=()=>{p.hidden=false};document.body.append(b);
    }
    choice('form0_Служба','Без отбора',['Без отбора','Other service']);
    choice(prefix+'4Значение','Да',['Да','Нет']);
    choice(prefix+'5ВидСравненияЭлементаОтбора','В списке',['В списке','Не в списке']);
    choice(prefix+'7ВидСравненияЭлементаОтбора','Не равно',['Равно','Не равно']);
    const employment=document.createElement('input');employment.id=prefix+'7Значение_i0';employment.value='1';document.body.append(employment);
    const types=document.createElement('div');document.body.append(types);
    window.renderTypes=()=>{types.innerHTML='';for(const [i,title] of window.types.entries()){const e=document.createElement('div');e.id=prefix+'5Значение_multipleValues_'+i;e.className='chipsItem';e.title=title;e.textContent=title;types.append(e)}};window.renderTypes();
    const b=document.createElement('button');b.id=prefix+'5Значение_CLR';b.textContent='Clear';b.onclick=()=>{window.actions++;window.types=[];window.renderTypes()};document.body.append(b);
    const field=document.createElement('input');field.id=prefix+'5Значение_i0';document.body.append(field);
    const list=document.createElement('div');document.body.append(list);
    field.addEventListener('input',()=>{list.innerHTML='';if(['6 - Мобильный Авто Курьер','9 - Мобильный Вело Курьер'].includes(field.value)){
      const option=document.createElement('div');option.textContent=field.value;option.onclick=()=>{window.actions++;window.types.push(option.textContent);window.renderTypes();field.value='';list.innerHTML=''};list.append(option);
    }});
  }''',PREFIX)
 def tearDown(self):self.browser.close();self.p.stop()
 def test_wrong_night_inclusion_filter_is_fully_restored_and_idempotent(self):
  self.assertFalse(roster_filter_structure(self.page)['filters_verified']);self.assertEqual(type_codes(self.page),{1,20,7})
  restore_values(self.page);ensure_roster_filters(self.page)
  self.assertTrue(roster_filter_structure(self.page)['filters_verified']);self.assertEqual(type_codes(self.page),{6,9})
  actions=self.page.evaluate('window.actions');restore_values(self.page);ensure_roster_filters(self.page)
  self.assertEqual(self.page.evaluate('window.actions'),actions)
 def test_access_employment_values_are_restored_too(self):
  self.page.evaluate('''(p)=>{document.getElementById(p+'4Значение_i0').value='Нет';document.getElementById(p+'7ВидСравненияЭлементаОтбора_i0').value='Равно';document.getElementById(p+'7Значение_i0').value='2';document.getElementById('form0_Служба_i0').value='Other service'}''',PREFIX)
  restore_values(self.page);self.assertTrue(roster_filter_structure(self.page)['filters_verified'])
 def test_ambiguous_dropdown_is_not_silently_selected(self):
  self.page.evaluate('''(p)=>{const b=document.getElementById(p+'5ВидСравненияЭлементаОтбора_DLB');b.addEventListener('click',()=>{const d=document.createElement('div');d.textContent='Не в списке';document.body.append(d)})}''',PREFIX)
  with self.assertRaises(ValueError):restore_values(self.page)
 def test_wrong_filter_is_rejected_before_sampling_or_export(self):
  import tempfile
  with tempfile.TemporaryDirectory() as directory,patch('onec_filters.restore_values'),patch('onec_browser.select_roster_shop'),patch('onec_browser.open_roster_navigation',return_value=None),patch('onec_roster.sample_grid') as sample,patch('onec_roster.export_id_list') as export:
   with self.assertRaises(ValueError):capture_interface(self.page,Path(directory),inspect_roster=True)
   sample.assert_not_called();export.assert_not_called()

 def test_reference_dropdown_fallback_commits_exact_codes_when_autocomplete_is_closed(self):
  self.page.evaluate('''(p)=>{
    const old=document.getElementById(p+'5Значение_i0');const field=old.cloneNode(true);old.replaceWith(field);
    const box=document.createElement('div');document.body.append(box);
    const button=document.createElement('button');button.id=p+'5Значение_DLB';button.textContent='Types';
    button.onclick=()=>{box.innerHTML='';for(const label of ['6 - Мобильный Авто Курьер','9 - Мобильный Вело Курьер']){
      const option=document.createElement('div');option.textContent=label;option.onclick=()=>{window.types.push(label);window.renderTypes();field.value='';box.innerHTML=''};box.append(option)
    }};document.body.append(button);
  }''',PREFIX)
  restore_values(self.page);self.assertTrue(roster_filter_structure(self.page)['filters_verified'])

 def test_unrelated_numeric_chips_do_not_establish_type_filter_contents(self):
  self.page.evaluate('''()=>{window.types=[];window.renderTypes();for(const title of ['6 - Мобильный Авто Курьер','9 - Мобильный Вело Курьер']){const e=document.createElement('div');e.className='chipsItem';e.title=title;document.body.append(e)}}''')
  self.assertFalse(roster_filter_structure(self.page)['filters_verified'])
 def test_saved_search_is_cleared_without_exporting_its_value(self):
  self.page.evaluate('''()=>{const base='form0_ФормаКоманднаяПанельСписокСтрокаПоиска';const f=document.createElement('input');f.id=base+'_i0';f.value='PRIVATE_SEARCH';document.body.append(f);const b=document.createElement('button');b.id=base+'_CLR';b.textContent='Clear search';b.onclick=()=>f.value='';document.body.append(b)}''')
  self.assertFalse(roster_filter_structure(self.page)['search_empty'])
  restore_values(self.page)
  data=roster_filter_structure(self.page);self.assertTrue(data['filters_verified']);self.assertNotIn('PRIVATE_SEARCH',json.dumps(data))

 def test_collapsed_overflow_is_opened_to_verify_the_second_selected_type(self):
  self.page.evaluate('''(p)=>{
    document.querySelectorAll('.chipsItem').forEach(e=>e.remove());
    const row=document.createElement('div');document.body.append(row);
    const popup=document.createElement('div');document.body.append(popup);
    window.renderTypes=()=>{row.innerHTML='';popup.innerHTML='';if(!window.types.length)return;
      const first=document.createElement('div');first.id=p+'5Значение_multipleValues_0';first.className='chipsItem';first.title=window.types[0];first.textContent=window.types[0];row.append(first);
      if(window.types.length>1){const more=document.createElement('button');more.id=p+'5Значение_multipleValues_more';more.textContent='+'+(window.types.length-1);
        more.onclick=()=>{popup.innerHTML='';popup.hidden=false;for(const title of window.types.slice(1)){const chip=document.createElement('div');chip.className='chipsItem';chip.title=title;chip.textContent=title;popup.append(chip)}};row.append(more)}
    };
    document.addEventListener('keydown',e=>{if(e.key==='Escape')popup.hidden=true});window.renderTypes();
  }''',PREFIX)
  restore_values(self.page);self.assertTrue(roster_filter_structure(self.page)['filters_verified'])
  self.assertEqual(type_codes(self.page),{6,9})
