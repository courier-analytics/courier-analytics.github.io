import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from onec_browser import wait_manual_login


@unittest.skipUnless(importlib.util.find_spec('playwright') and Path('/usr/lib/chromium/chromium').exists(),
                     'Optional local Chromium integration check')
class ManualLoginEventsTests(unittest.TestCase):
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
