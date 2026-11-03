import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from onec_browser import wait_manual_login, compare_manual_inputs, capture_interface, open_roster_navigation, select_roster_shop, roster_filter_structure


@unittest.skipUnless(importlib.util.find_spec('playwright') and Path('/usr/lib/chromium/chromium').exists(),
                     'Optional local Chromium integration check')
class ManualLoginEventsTests(unittest.TestCase):
    def test_point_filter_changes_only_list_and_snapshot_excludes_other_values(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/lib/chromium/chromium',
                                                 headless=True, args=['--no-sandbox'])
            try:
                page = browser.new_page()
                prefix = 'form0_КомпоновщикНастроекПользовательскиеНастройкиЭлемент'
                page.set_content(f'''<input id="form0_НомерТочки_i0" onblur="window.point=this.value">
                    <input id="{prefix}4Значение_i0" value="Да">
                    <div id="{prefix}5Значение"><span>Мобильный Вело Курьер</span><span>Мобильный Авто Курьер</span></div>
                    <input id="search" value="PRIVATE_SEARCH"><input type="password" value="PRIVATE_SECRET">
                    <button onclick="window.edited=true">Записать</button>''')
                select_roster_shop(page)
                self.assertEqual(page.evaluate('window.point'), '7745')
                self.assertIsNone(page.evaluate('window.edited'))
                metadata = roster_filter_structure(page)
                self.assertEqual(metadata['values']['form0_НомерТочки_i0'], '7745')
                self.assertFalse(metadata['filters_verified'])
                self.assertFalse(metadata['complete_roster'])
                self.assertIn('Мобильный Авто Курьер', str(metadata))
                self.assertNotIn('PRIVATE_SEARCH', str(metadata))
                self.assertNotIn('PRIVATE_SECRET', str(metadata))
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
