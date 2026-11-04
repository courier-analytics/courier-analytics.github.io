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

 def test_blank_point_scalar_form_selects_shop_before_restoring_values(self):
  import tempfile
  from onec_filters import restore_values as real_restore
  self.page.evaluate('''(p)=>{
    document.getElementById('form0_НомерТочки_i0').value='';
    window.savedControls=[p+'5ВидСравненияЭлементаОтбора_i0',p+'5ВидСравненияЭлементаОтбора_DLB'].map(id=>document.getElementById(id));
    window.savedControls.forEach(e=>e.remove());
  }''',PREFIX)
  def select(page):
   page.evaluate("()=>{document.getElementById('form0_НомерТочки_i0').value='7745';window.savedControls.forEach(e=>document.body.append(e));}")
   page.evaluate('''()=>{
    const grid=document.getElementById('grid_form0_Список');
    grid.innerHTML='<div class="gridHead"><div class="gridLine"><div class="gridBox">Id</div><div class="gridBox">Name</div><div class="gridBox">Active</div><div class="gridBox">Т.З.</div></div></div><div class="gridBody"><div class="gridLine"><div class="gridBox">111111</div><div class="gridBox">Test A</div><div class="gridBox"><i class="checkbox select"></i></div><div class="gridBox">5</div></div></div>';
   }''')
  def restore(page,progress=None):
   self.assertEqual(page.locator('[id="form0_НомерТочки_i0"]').input_value(),'7745')
   return real_restore(page,progress)
  export={'confirmed':True,'columns':['Id'],'only_selected':False,'documents':{'text_fields':[{'text':'Id\n111111\n222222'}]}}
  with tempfile.TemporaryDirectory() as directory,patch('onec_browser.open_roster_navigation',return_value=None),patch('onec_browser.select_roster_shop',side_effect=select),patch('onec_filters.restore_values',side_effect=restore) as restore_call,patch('onec_roster.inspect_export_dialog',return_value={'opened':True}),patch('onec_roster.export_id_list',return_value=export):
   result=capture_interface(self.page,Path(directory),inspect_roster=True)
   restore_call.assert_called_once()
   self.assertTrue(result['roster_filters']['filters_verified']);self.assertTrue(result['native_roster']['verified'])

 def settings_fixture(self,editor=False,duplicate=False):
  self.page.evaluate('''([p,editor,duplicate])=>{
    window.savedControls=[p+'5ВидСравненияЭлементаОтбора_i0',p+'5ВидСравненияЭлементаОтбора_DLB'].map(id=>document.getElementById(id));window.savedControls.forEach(e=>e.remove());window.settingsApplied=0;
    const more=document.createElement('button');more.id='form0_allActionsФормаКоманднаяПанель';more.textContent='Ещё';document.body.append(more);
    const configure=document.createElement('button');configure.id='form0_popup_ФормаНастройкаСписка';configure.textContent='Настроить список...';configure.hidden=true;document.body.append(configure);more.onclick=()=>configure.hidden=false;
    configure.onclick=()=>{
      configure.hidden=true;const dialog=document.createElement('div');dialog.id='form7_container';document.body.append(dialog);
      const tab=document.createElement('button');tab.textContent='Отбор';dialog.append(tab);
      const body=document.createElement('div');body.hidden=true;dialog.append(body);tab.onclick=()=>body.hidden=false;
      body.innerHTML='<div class="gridBody"><div class="gridLine"><span>ТипКурьера</span></div></div><div class="gridBody" id="filterRows"><div class="gridLine"><span>ТипКурьера</span><span id="comparisonCell">Равно</span></div></div>';
      if(duplicate){const row=document.createElement('div');row.className='gridLine';row.innerHTML='<span>ТипКурьера</span><span>Равно</span>';body.querySelector('#filterRows').append(row)}
      const cell=body.querySelector('#comparisonCell');
      const popup=document.createElement('div');popup.hidden=true;dialog.append(popup);const item=document.createElement('button');item.textContent='Не в списке';popup.append(item);
      item.onclick=()=>{popup.hidden=true;cell.textContent='Не в списке'};
      cell.ondblclick=()=>{
        if(!editor){popup.hidden=false;return}
        cell.innerHTML='';const input=document.createElement('input');input.id='form7_ActualComparison_i0';input.value='Равно';cell.append(input);
        const select=document.createElement('button');select.id='form7_ActualComparison_DLB';select.textContent='Select';select.onclick=()=>popup.hidden=false;cell.append(select);input.focus();
      };
      const finish=document.createElement('button');finish.textContent='Завершить редактирование';dialog.append(finish);finish.onclick=()=>{window.settingsApplied++;window.savedControls[0].value=cell.textContent;window.savedControls.forEach(e=>document.body.append(e));dialog.remove()};
    };
  }''',[PREFIX,editor,duplicate])

 def test_scalar_filter_uses_user_confirmed_configure_list_route(self):
  self.settings_fixture()
  restore_values(self.page)
  self.assertTrue(roster_filter_structure(self.page)['filters_verified'])
  self.assertEqual(self.page.evaluate('window.settingsApplied'),1)
  actions=self.page.evaluate('window.actions');restore_values(self.page)
  self.assertEqual(self.page.evaluate('window.actions'),actions)
  self.assertEqual(self.page.evaluate('window.settingsApplied'),1)

 def test_native_comparison_editor_uses_its_actual_dropdown(self):
  self.settings_fixture(editor=True)
  self.page.evaluate("()=>{const stale=document.createElement('div');stale.id='form9_container';stale.style.cssText='height:20px;visibility:hidden';document.body.append(stale)}")
  restore_values(self.page)
  self.assertTrue(roster_filter_structure(self.page)['filters_verified'])

 def test_ambiguous_settings_filter_rows_are_not_applied(self):
  self.settings_fixture(duplicate=True)
  with self.assertRaises(ValueError):restore_values(self.page)
  self.assertEqual(self.page.evaluate('window.settingsApplied'),0)

 def test_settings_already_on_filter_tab_does_not_click_ambiguous_filter_caption(self):
  self.settings_fixture()
  self.page.evaluate('''()=>{
    const configure=Array.from(document.querySelectorAll('button')).find(e=>e.textContent==='Настроить список...');
    const open=configure.onclick;configure.onclick=()=>{open();document.querySelector('#form7_container button').click();const title=document.createElement('span');title.textContent='Отбор';document.querySelector('#form7_container').append(title)};
  }''')
  restore_values(self.page)
  self.assertTrue(roster_filter_structure(self.page)['filters_verified'])

 def test_comparison_change_can_reset_list_and_hide_clear_button(self):
  self.settings_fixture()
  self.page.evaluate('''(p)=>{
    const configure=Array.from(document.querySelectorAll('button')).find(e=>e.textContent==='Настроить список...');
    const open=configure.onclick;configure.onclick=()=>{open();const finish=Array.from(document.querySelectorAll('#form7_container button')).find(e=>e.textContent==='Завершить редактирование');const apply=finish.onclick;
      finish.onclick=()=>{apply();window.types=[];window.renderTypes();document.getElementById(p+'5Значение_CLR').remove();const use=document.getElementById(p+'5Использование');use.classList.remove('select');document.getElementById(p+'5Значение_i0').disabled=true;use.addEventListener('click',()=>document.getElementById(p+'5Значение_i0').disabled=!use.classList.contains('select'))};
    };
  }''',PREFIX)
  restore_values(self.page)
  self.assertTrue(roster_filter_structure(self.page)['filters_verified'])

 def test_evidenced_settings_menu_id_opens_command_with_nbsp_caption(self):
  self.settings_fixture()
  self.page.evaluate("()=>document.getElementById('form0_popup_ФормаНастройкаСписка').textContent='Настроить\\u00a0список...'")
  restore_values(self.page)
  self.assertEqual(self.page.evaluate('window.settingsApplied'),1)
  self.assertTrue(roster_filter_structure(self.page)['filters_verified'])

 def test_nbsp_comparison_option_is_selected_and_its_value_is_verified(self):
  self.page.evaluate('''(p)=>{
    const field=document.getElementById(p+'5ВидСравненияЭлементаОтбора_i0');field.value='В\\u00a0списке';
    const item=Array.from(document.querySelectorAll('div')).find(e=>e.textContent==='Не в списке');
    item.textContent='Не\\u00a0в\\u00a0списке';item.onclick=()=>{window.actions++;field.value=item.textContent;item.parentElement.hidden=true};
  }''',PREFIX)
  restore_values(self.page)
  self.assertTrue(roster_filter_structure(self.page)['filters_verified'])

 def test_valid_nbsp_filter_values_do_not_trigger_unneeded_changes(self):
  self.page.evaluate('''(p)=>{
    document.getElementById(p+'5ВидСравненияЭлементаОтбора_i0').value='Не\\u00a0в\\u00a0списке';
    document.getElementById(p+'7ВидСравненияЭлементаОтбора_i0').value='Не\\u00a0равно';
    document.getElementById('form0_Служба_i0').value='Без\\u00a0отбора';
    window.types=['6 - Мобильный Авто Курьер','9 - Мобильный Вело Курьер'];window.renderTypes();
  }''',PREFIX)
  restore_values(self.page)
  self.assertEqual(self.page.evaluate('window.actions'),0)
  self.assertTrue(roster_filter_structure(self.page)['filters_verified'])

 def test_text_fallback_accepts_nbsp_and_normalized_wrapper_captions(self):
  from onec_filters import _choose
  self.page.set_content('<div id="wrapper"> <span>Настроить&nbsp;список...</span> </div><script>window.clicked=0;document.querySelector("span").onclick=()=>window.clicked++;</script>')
  _choose(self.page,('Настроить список...',))
  self.assertEqual(self.page.evaluate('window.clicked'),1)
