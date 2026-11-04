import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from onec_browser import wait_manual_login, compare_manual_inputs, capture_interface, open_roster_navigation, select_roster_shop, roster_filter_structure, ensure_roster_filters, save_failure_interface, close_roster_popup


@unittest.skipUnless(importlib.util.find_spec('playwright') and Path('/usr/lib/chromium/chromium').exists(),
                     'Optional local Chromium integration check')
class ManualLoginEventsTests(unittest.TestCase):
    def test_popup_closes_with_escape_when_caption_cannot_receive_clicks(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(executable_path='/usr/lib/chromium/chromium',headless=True,args=['--no-sandbox'])
            try:
                page=browser.new_page()
                page.set_content('''<div id="captionbarTitle" style="pointer-events:none">Caption</div>
                    <div id="popup">Excluded types</div><script>
                    document.addEventListener('keydown',e=>{if(e.key==='Escape')document.querySelector('#popup').hidden=true});
                    </script>''')
                close_roster_popup(page)
                self.assertFalse(page.locator('#popup').is_visible())
            finally:browser.close()

    def test_required_filter_checkbox_is_restored_and_second_pass_does_not_toggle_it_off(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(executable_path='/usr/lib/chromium/chromium',headless=True,args=['--no-sandbox'])
            try:
                page=browser.new_page();prefix='form0_КомпоновщикНастроекПользовательскиеНастройкиЭлемент'
                controls=''.join(f'<div id="{prefix}{n}Использование" class="checkbox {"select" if n in (4,6,7,8) else ""}" onclick="window.toggles++;setTimeout(()=>this.classList.toggle(\'select\'),50)"></div>' for n in (4,5,6,7,8))
                page.set_content('<style>.checkbox{width:20px;height:20px}</style><script>window.toggles=0</script>'+controls)
                stages=[]
                ensure_roster_filters(page,stages.append)
                self.assertIn('filter_5_state',stages)
                selected=page.locator('.checkbox.select').evaluate_all('(es)=>es.map(e=>e.id)')
                self.assertEqual(set(selected),{prefix+str(n)+'Использование' for n in (4,5,7)})
                self.assertEqual(page.evaluate('window.toggles'),3)
                ensure_roster_filters(page)
                self.assertEqual(page.evaluate('window.toggles'),3)
            finally:browser.close()

    def test_timeout_archive_replaces_old_snapshot_even_when_screenshot_fails(self):
        import tempfile,zipfile,json
        from unittest.mock import patch
        from playwright.sync_api import sync_playwright,TimeoutError
        with sync_playwright() as playwright,tempfile.TemporaryDirectory() as folder:
            browser=playwright.chromium.launch(executable_path='/usr/lib/chromium/chromium',headless=True,args=['--no-sandbox'])
            try:
                page=browser.new_page();page.set_content('<input type="password" id="userPassword" style="display:none" value="DO_NOT_EXPORT"><div id="mainSurface"></div>')
                archive=Path(folder)/'onec-interface.zip';archive.write_bytes(b'old snapshot')
                with patch.object(page,'screenshot',side_effect=TimeoutError('PRIVATE_ERROR_DETAIL')):
                    save_failure_interface(page,Path(folder),'before_point.filter_5_state')
                self.assertEqual(archive.stat().st_mode & 0o777,0o600)
                with zipfile.ZipFile(archive) as bundle:
                    raw=bundle.read('ui-structure.json').decode();data=json.loads(raw)
                    self.assertEqual(data['failure_stage'],'before_point.filter_5_state')
                    self.assertFalse(data['screenshot_available'])
                    self.assertNotIn('DO_NOT_EXPORT',raw);self.assertNotIn('PRIVATE_ERROR_DETAIL',raw)
            finally:browser.close()

    def test_point_filter_changes_only_list_and_snapshot_excludes_other_values(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/lib/chromium/chromium',
                                                 headless=True, args=['--no-sandbox'])
            try:
                page = browser.new_page()
                prefix = 'form0_КомпоновщикНастроекПользовательскиеНастройкиЭлемент'
                page.set_content(f'''<input id="form0_НомерТочки_i0"
                    onkeydown="if(event.key === 'Enter')window.point=this.value"
                    onkeyup="if(event.key === '5')window.typed=true">
                    <input id="{prefix}4Значение_i0" value="Да">
                    <div id="{prefix}5Значение"><span>Мобильный Вело Курьер</span><span>Мобильный Авто Курьер</span></div>
                    <input id="search" value="PRIVATE_SEARCH"><input type="password" value="PRIVATE_SECRET">
                    <button onclick="window.edited=true">Записать</button>''')
                select_roster_shop(page)
                self.assertEqual(page.evaluate('window.point'), '7745')
                self.assertTrue(page.evaluate('window.typed'))
                self.assertIsNone(page.evaluate('window.edited'))
                metadata = roster_filter_structure(page)
                self.assertEqual(metadata['values']['form0_НомерТочки_i0'], '7745')
                self.assertFalse(metadata['filters_verified'])
                self.assertFalse(metadata['complete_roster'])
                self.assertIn('Мобильный Авто Курьер', str(metadata))
                self.assertNotIn('PRIVATE_SEARCH', str(metadata))
                self.assertNotIn('PRIVATE_SECRET', str(metadata))
                page.evaluate('''(root) => {
                    const values = {'form0_Служба_i0':'Без отбора'};
                    values[root+'5ВидСравненияЭлементаОтбора_i0']='Not in list';
                    values[root+'7ВидСравненияЭлементаОтбора_i0']='Not equal';
                    values[root+'7Значение_i0']='1';
                    for(const [id,value] of Object.entries(values)){
                        const e=document.createElement('input');e.id=id;e.value=value;document.body.append(e);
                    }
                    for(const n of [4,5,7]){
                        const e=document.createElement('div');e.id=root+n+'Использование';e.className='checkbox select';document.body.append(e);
                    }
                    for(const title of ['6 - Мобильный Авто Курьер','9 - Мобильный Вело Курьер']){
                        const e=document.createElement('div');e.className='chipsItem';e.title=title;document.body.append(e);
                    }
                }''', prefix)
                self.assertTrue(roster_filter_structure(page)['filters_verified'])
                page.evaluate('''() => {const e=document.createElement('div');e.className='chipsItem';e.title='3 - Другой тип';document.body.append(e)}''')
                self.assertFalse(roster_filter_structure(page)['filters_verified'])
            finally:
                browser.close()

    def test_roster_navigation_opens_only_reference_and_list(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/lib/chromium/chromium',
                                                 headless=True, args=['--no-sandbox'])
            try:
                page = browser.new_page()
                page.set_content('''<div id="mainSurface" hidden>
                    <span hidden>Самозанятые</span>
                    <div onclick="document.querySelector('#couriers').hidden=false"><span>Самозанятые</span></div>
                    <span id="couriers" hidden onclick="document.querySelector('#result').hidden=false">Курьеры</span>
                    <div id="result" hidden>Список курьеров</div>
                    <button onclick="window.edited=true">Создать</button></div>
                    <script>setTimeout(()=>document.querySelector('#mainSurface').hidden=false,750)</script>''')
                self.assertIsNone(open_roster_navigation(page))
                self.assertTrue(page.locator('#result').is_visible())
                self.assertIsNone(page.evaluate('window.edited'))
                page.set_content('<span>Самозанятые</span><span>Самозанятые</span>')
                self.assertEqual(open_roster_navigation(page), 'Самозанятые')
            finally:
                browser.close()

    def test_manual_credentials_compare_reports_only_equality_flags(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/lib/chromium/chromium',
                                                 headless=True, args=['--no-sandbox'])
            try:
                page = browser.new_page()
                page.route('**/*', lambda route: route.fulfill(content_type='text/html',
                    body='<input id="userName"><input id="userPassword" type="password"><button id="okButton">Login</button>'))
                page.goto('https://couriers.int.vkusvill.ru/couriers/ru_RU/')
                report = {}
                captured = []
                compare_manual_inputs(page, {'username': 'expected-user', 'password': 'expected-secret'}, report, captured)
                page.locator('#userName').fill('expected-user')
                page.locator('#userPassword').fill('different-secret')
                page.locator('#okButton').click()
                page.wait_for_timeout(50)
                self.assertEqual(report['manual_input_vs_vps'], {
                    'username_matches_vps': True, 'password_matches_vps': False})
                self.assertNotIn('secret', str(report))
                self.assertEqual(captured[0]['password'], 'different-secret')
                page.locator('#userPassword').fill('expected-secret')
                page.locator('#userPassword').press('Enter')
                page.wait_for_timeout(50)
                self.assertTrue(report['manual_input_vs_vps']['password_matches_vps'])
            finally:
                browser.close()

    def test_private_interface_bundle_does_not_export_input_values(self):
        import tempfile, zipfile
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright, tempfile.TemporaryDirectory() as directory:
            browser = playwright.chromium.launch(executable_path='/usr/lib/chromium/chromium',
                                                 headless=True, args=['--no-sandbox'])
            try:
                page = browser.new_page()
                page.set_content('<input id="userPassword" type="password" style="display:none" value="PRIVATE_SECRET"><div id="mainSurface"><button>Курьеры</button><span>Справочники</span><input value="PRIVATE_FIELD"></div>')
                capture_interface(page, Path(directory))
                archive = Path(directory)/'onec-interface.zip'
                self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
                with zipfile.ZipFile(archive) as bundle:
                    metadata = bundle.read('ui-structure.json').decode()
                    self.assertNotIn('PRIVATE_SECRET', metadata)
                    self.assertNotIn('PRIVATE_FIELD', metadata)
                    self.assertIn('Справочники', metadata)
                    self.assertIn('Курьеры', metadata)
                    self.assertEqual(set(bundle.namelist()), {'ui-structure.json', 'interface.png'})
            finally:
                browser.close()

    def test_verified_all_row_export_is_saved_without_scanning_or_a_screenshot(self):
        import tempfile,json,zipfile
        from unittest.mock import patch
        from playwright.sync_api import sync_playwright,TimeoutError
        from onec_roster_cache import load,MOSCOW
        from datetime import datetime
        with sync_playwright() as playwright,tempfile.TemporaryDirectory() as directory:
            browser=playwright.chromium.launch(executable_path='/usr/lib/chromium/chromium',headless=True,args=['--no-sandbox'])
            try:
                page=browser.new_page()
                page.set_content('''<div id="mainSurface"><div id="grid_form0_Список" style="pointer-events:none">
                  <div class="gridHead"><div class="gridLine"><div class="gridBox">Id</div><div class="gridBox">Name</div><div class="gridBox">Active</div><div class="gridBox">Т.З.</div></div></div>
                  <div class="gridBody"><div class="gridLine"><div class="gridBox">111111</div><div class="gridBox">Test A</div><div class="gridBox"><i class="checkbox select"></i></div><div class="gridBox">5</div></div></div>
                </div></div>''')
                export={'confirmed':True,'columns':['Id'],'only_selected':False,'documents':{'text_fields':[{'text':'Id\n111111\n222222'}]}}
                folder=Path(directory)
                def screenshot(**kwargs):
                    # A validated cache already exists even if the screenshot now fails.
                    self.assertEqual(load(folder/'onec-rosters/7745.json',datetime.now(MOSCOW).date().isoformat())['count'],2)
                    raise TimeoutError('PRIVATE_BROWSER_DETAIL')
                with patch('onec_browser.open_roster_navigation',return_value=None),patch('onec_browser.ensure_roster_filters'),patch('onec_browser.select_roster_shop'),patch('onec_browser.roster_filter_structure',return_value={'filters_verified':True}),patch('onec_roster.scan_grid',side_effect=TimeoutError('must not scroll')) as scan,patch('onec_roster.inspect_export_dialog',return_value={'opened':True}),patch('onec_roster.export_id_list',return_value=export),patch.object(page,'screenshot',side_effect=screenshot):
                    result=capture_interface(page,folder,inspect_roster=True)
                scan.assert_not_called()
                self.assertTrue(result['native_roster']['verified']);self.assertFalse(result['screenshot_available'])
                with zipfile.ZipFile(folder/'onec-interface.zip') as bundle:
                    self.assertEqual(bundle.namelist(),['ui-structure.json'])
                    self.assertNotIn('PRIVATE_BROWSER_DETAIL',bundle.read('ui-structure.json').decode())
            finally:browser.close()

    def test_hidden_login_form_does_not_end_wait_before_final_server_response(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/lib/chromium/chromium',
                                                 headless=True, args=['--no-sandbox'])
            try:
                page = browser.new_page()
                completed = []
                page.on('response', lambda response: completed.append(True)
                        if response.url.endswith('/final-login') else None)
                def route(request):
                    if request.request.url.endswith('/final-login'):
                        request.fulfill(status=200, body='ok')
                    else:
                        request.fulfill(content_type='text/html', body='''<input id="userPassword" style="display:none">
                            <script>setTimeout(()=>fetch('/final-login'),750);</script>''')
                page.route('**/*', route)
                page.goto('https://login.example.invalid/')
                self.assertFalse(page.locator('#userPassword').is_visible())
                self.assertFalse(completed)
                self.assertTrue(wait_manual_login(page, lambda: bool(completed), attempts=10))
                self.assertTrue(completed)
            finally:
                browser.close()

    def test_wait_keeps_browser_requests_and_response_callbacks_running(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/lib/chromium/chromium',
                                                 headless=True, args=['--no-sandbox'])
            try:
                page = browser.new_page()
                completed = []
                page.on('response', lambda response: completed.append(True)
                        if response.url.endswith('/manual-login') else None)
                def route(request):
                    if request.request.url.endswith('/manual-login'):
                        request.fulfill(status=200, body='ok')
                    else:
                        request.fulfill(content_type='text/html', body='''<input id="userPassword" type="password">
                            <script>setTimeout(()=>fetch('/manual-login').then(()=>{
                            document.querySelector('#userPassword').style.display='none';}),200);</script>''')
                page.route('**/*', route)
                page.goto('https://login.example.invalid/')
                self.assertTrue(wait_manual_login(page, lambda: bool(completed), attempts=10))
            finally:
                browser.close()
