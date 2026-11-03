import importlib.util
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from onec_roster import grid_rows,scan_grid,inspect_export_dialog

@unittest.skipUnless(importlib.util.find_spec('playwright') and Path('/usr/lib/chromium/chromium').exists(), 'Optional Chromium integration')
class RosterGridTests(unittest.TestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright
        self.p=sync_playwright().start()
        self.browser=self.p.chromium.launch(executable_path='/usr/lib/chromium/chromium',headless=True,args=['--no-sandbox'])
        self.page=self.browser.new_page()
        self.page.set_content('''<div id="grid_form0_Список" tabindex="0"><div class="gridHead"><div class="gridLine">
          <div class="gridBox">Id</div><div class="gridBox">Name</div><div class="gridBox">Phone</div>
          <div class="gridBox">Active</div><div class="gridBox">ИНН</div><div class="gridBox">Т.З.</div></div></div>
          <div class="gridBody"></div></div>
          <script>let index=0;const pages=[[101,102],[102,103],[104]];
          function render(){document.querySelector('.gridBody').innerHTML=pages[index].map(id=>
           `<div class="gridLine"><div class="gridBox">${id}</div><div class="gridBox">Courier ${id}</div>
            <div class="gridBox">PRIVATE_PHONE</div><div class="gridBox"><span class="checkbox select"></span></div>
            <div class="gridBox">PRIVATE_TAX_ID</div><div class="gridBox">5</div></div>`).join('')}
          document.addEventListener('keydown',e=>{if(e.key==='PageDown')index=Math.min(index+1,2);
            if(e.ctrlKey && e.key==='Home')index=0;if(e.ctrlKey && e.key==='End')index=2;render()});render();</script>''')
    def tearDown(self):
        self.browser.close();self.p.stop()
    def test_multiple_pages_are_deduplicated_and_sensitive_columns_not_exported(self):
        result=scan_grid(self.page,max_pages=5)
        self.assertEqual({r['courier_id'] for r in result['couriers']},{'101','102','103','104'})
        self.assertEqual(result['stop_reason'],'stationary_viewport')
        self.assertEqual(result['unseen_tail_ids'],[])
        self.assertFalse(result['complete_roster'])
        self.assertNotIn('PRIVATE_PHONE',str(result));self.assertNotIn('PRIVATE_TAX_ID',str(result))
    def test_truncated_traversal_reports_unseen_tail_and_never_claims_complete(self):
        result=scan_grid(self.page,max_pages=1)
        self.assertEqual(result['stop_reason'],'page_limit')
        self.assertEqual(result['unseen_tail_ids'],['104'])
        self.assertFalse(result['complete_roster'])
    def test_changed_headers_and_inactive_couriers_are_rejected(self):
        self.page.locator('.checkbox').first.evaluate('(e)=>e.classList.remove("select")')
        with self.assertRaises(ValueError):grid_rows(self.page)

        self.page.locator('.gridHead .gridBox').first.evaluate('(e)=>e.textContent="Changed"')
        with self.assertRaises(ValueError):grid_rows(self.page)

    def test_only_read_only_export_dialog_is_opened_not_confirmed(self):
        self.page.set_content('''
            <button id="form0_allActionsФормаКоманднаяПанель" onclick="document.querySelector('#form0_popup_ФормаВывестиСписок').hidden=false">Еще</button>
            <div id="form0_popup_ФормаВывестиСписок" hidden onclick="document.querySelector('#form1_dialog').hidden=false">Вывести список</div>
            <div id="form1_dialog" hidden><button id="form1_confirm" onclick="window.confirmed=true">ОК</button></div>''')
        result=inspect_export_dialog(self.page)
        self.assertTrue(result['opened'])
        self.assertFalse(result['confirmed'])
        self.assertIsNone(self.page.evaluate('window.confirmed'))

    def test_native_export_selects_ids_and_names_without_phones(self):
        from onec_roster import export_id_list, verify_id_export
        self.page.set_content('''<style>.checkbox{display:inline-block;width:18px;height:18px}</style><a id="form1_UnckeckAll" onclick="document.querySelectorAll('.checkbox').forEach(e=>e.classList.remove('select'))">Clear</a>
            <div id="form1_AvailableColumnsElement"><div class="gridBody">
             <div class="gridLine"><span class="checkbox select" onclick="this.classList.toggle('select')"></span><span>Id</span></div>
             <div class="gridLine"><span class="checkbox select" onclick="this.classList.toggle('select')"></span><span>Name</span></div>
             <div class="gridLine"><span class="checkbox select"></span><span>Phone</span></div></div></div>
            <div id="form1_OnlySelectedElement" class="checkbox" onclick="this.classList.toggle('select')"></div>
            <input id="form1_DocumentTypeElement_i0" value="Text document">
            <a id="form1_Ok" onclick="window.exported=true;document.querySelector('textarea').hidden=false;document.querySelector('#form1_DocumentTypeElement_i0').hidden=true">OK</a>
            <textarea hidden>Id	Name
1800115894	TEST_ONE
1800128719	TEST_TWO</textarea>''')
        self.assertFalse(export_id_list(self.page,False)['confirmed'])
        self.assertIsNone(self.page.evaluate('window.exported'))
        result=export_id_list(self.page,True)
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['columns'],['Id','Name'])
        self.assertFalse(result['only_selected'])
        verified=verify_id_export(result,['1800115894'])
        self.assertTrue(verified['verified'])
        self.assertEqual(verified['count'],2)


class NativeIdOutputTests(unittest.TestCase):
    def test_only_strict_unique_id_column_is_accepted(self):
        from onec_roster import parse_id_document,verify_id_export
        self.assertEqual(parse_id_document('Id\n1800115894\n1800128719\n'), ['1800115894','1800128719'])
        for text in ('Name\n1800115894', 'Id\n1800115894\n1800115894', 'Id\n1800115894\tPRIVATE_PHONE', 'Id\n', 'Id\n123'):
            with self.assertRaises(ValueError):parse_id_document(text)
        export={'confirmed':True,'columns':['Id'],'only_selected':False,
                'documents':{'text_fields':[{'text':'Id\n1800115894\n1800128719\n'}]}}
        self.assertTrue(verify_id_export(export,['1800115894'])['verified'])
        self.assertFalse(verify_id_export(export,['9999999999'])['verified'])
        export['only_selected']=True
        self.assertFalse(verify_id_export(export,[])['verified'])
