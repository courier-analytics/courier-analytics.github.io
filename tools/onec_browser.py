"""Use the evidenced 1C login form; keep credentials and session details private."""
import getpass
import json
import os
from pathlib import Path
import stat
from urllib.parse import urlsplit

from onec_access import HOST, PATH
from powerbi_access import corporate_interface
from prepare_openvpn import private_write

CREDENTIALS = Path('/root/courier-onec.json')


def save_credentials(path=CREDENTIALS):
    if path.exists():
        print('Existing 1C credentials preserved.', flush=True)
        return
    username = getpass.getpass('1C username (hidden): ')
    password = getpass.getpass('1C password (hidden): ')
    if not username.strip() or not password or any(ord(c) < 32 for c in username+password):
        raise ValueError('Empty credentials or control characters are not accepted')
    private_write(path, json.dumps({'username': username, 'password': password}))
    print('1C credentials saved privately on this VPS.', flush=True)


def load_credentials(path=CREDENTIALS):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
        raise ValueError('1C credential file owner or permissions need correction')
    data = json.loads(path.read_text())
    if any(not isinstance(data.get(key), str) or not data[key] or any(ord(c) < 32 for c in data[key])
           for key in ('username', 'password')):
        raise ValueError('Invalid saved 1C credentials')
    return data


def final_login_shape(value):
    # Upa() in the supplied 1C loader reads these fields after authentication.
    if not isinstance(value, dict):
        return False
    return 'passwordExpirationStatus' in value or any(
        isinstance(v, dict) and 'passwordExpirationStatus' in v for v in value.values())


def check_login(address, private=Path('/opt/courier-analytics/private')):
    from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
    credentials = load_credentials()
    corporate_interface(address)
    private.mkdir(parents=True, exist_ok=True)
    result = {'login_submitted': False, 'authenticated': False, 'login_http_statuses': [],
              'two_factor_required': False, 'password_change_required': False}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=[
            '--no-proxy-server', '--disable-quic',
            '--host-resolver-rules=MAP '+HOST+' '+address])
        context = browser.new_context(service_workers='block', accept_downloads=False)
        # No TLS verification bypass, external redirects, credential URLs or
        # alternate network routes. Validate the VPN route before each request.
        def route_request(route):
            url = urlsplit(route.request.url)
            if url.scheme != 'https' or url.netloc != HOST or not url.path.startswith(PATH):
                route.abort()
                return
            try:
                corporate_interface(address)
            except (ValueError, OSError):
                route.abort()
                return
            route.continue_()
        context.route('**/*', route_request)
        context.route_web_socket('**/*', lambda websocket: websocket.close())
        page = context.new_page()
        page.on('dialog', lambda dialog: dialog.dismiss())
        final_response = []
        def response_received(response):
            if urlsplit(response.url).path != PATH+'e1cib/login':
                return
            result['login_http_statuses'].append(response.status)
            if response.status == 200:
                try:
                    data = response.json()
                    if final_login_shape(data) and response.header_value('vrs-session'):
                        final_response.append(True)
                except Exception:
                    pass
        page.on('response', response_received)
        try:
            page.goto('https://'+HOST+PATH, wait_until='domcontentloaded', timeout=60000)
            page.locator('#userName').wait_for(state='visible', timeout=60000)
            page.locator('#userName').fill(credentials['username'])
            page.locator('#userPassword').fill(credentials['password'])
            page.locator('#okButton').click()
            result['login_submitted'] = True
            try:
                page.wait_for_function("document.querySelector('#authWindow') && getComputedStyle(document.querySelector('#authWindow')).display === 'none'", timeout=45000)
            except BrowserTimeout:
                pass
            result['authenticated'] = bool(final_response) and not page.locator('#userPassword').is_visible()
            result['two_factor_required'] = page.locator('#auth2FCodeField').is_visible()
            result['password_change_required'] = page.locator('#newPassword').is_visible()
            result['authenticated'] = result['authenticated'] and not (
                result['two_factor_required'] or result['password_change_required'])
            if result['authenticated']:
                # Only known navigation labels; never courier rows, account name,
                # full DOM, screenshots, response bodies or authentication tokens.
                labels = ('Курьеры', 'Справочники', 'Сотрудники', 'Отчеты', 'Отчёты', 'Доставка')
                result['navigation_labels'] = [text for text in labels if page.get_by_text(text, exact=True).count()]
        except BrowserTimeout:
            result['stage_timeout'] = True
        finally:
            context.close()
            browser.close()
    private_write(private/'onec-browser-status.json', json.dumps(result, ensure_ascii=False))
    print('1C browser login: '+json.dumps(result, ensure_ascii=False), flush=True)
    print('Courier roster not queried; dashboard unchanged.', flush=True)
    return result['authenticated']
