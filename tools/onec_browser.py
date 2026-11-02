"""Use the evidenced 1C login form; keep credentials and session details private."""
import getpass
import base64
import json
import os
from pathlib import Path
import stat
import re
from urllib.parse import urlsplit

from onec_access import HOST, PATH
from powerbi_access import corporate_interface
from prepare_openvpn import private_write

CREDENTIALS = Path('/root/courier-onec.json')


def save_credentials(path=CREDENTIALS, replace=False):
    if path.exists() and not replace:
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


def failure_shape(text):
    """Keep numeric error reasons and fixed categories, never server messages."""
    reasons, descriptions = [], [text]
    try:
        stack = [json.loads(text)]
        for _ in range(30):
            if not stack:
                break
            node = stack.pop()
            if not isinstance(node, dict):
                continue
            for key in ('reason', 'reason_2fa'):
                if type(node.get(key)) is int:
                    reasons.append(node[key])
            description = node.get('descr')
            if isinstance(description, str):
                if node.get('encoded'):
                    try:
                        description = base64.b64decode(description, validate=True).decode('utf-8')
                    except (ValueError, UnicodeError):
                        description = ''
                descriptions.append(description)
            stack.extend(node.get(key) for key in ('exception', 'inner'))
    except ValueError:
        pass
    combined = '\n'.join(descriptions).lower()
    rules = {
        'credentials_rejected': r'(?:неверн|неправильн).{0,60}(?:парол|пользовател)|invalid.{0,40}(?:password|user)|authentication failed',
        'license_unavailable': r'лицензи|licen[cs]e',
        'access_denied': r'недостаточно прав|доступ запрещ|access denied',
        'account_locked': r'пользовател.{0,40}заблок|account.{0,20}lock',
        'two_factor': r'двухфактор|two.factor|2fa',
        'password_expired': r'парол.{0,40}(?:ист[её]к|просроч)|password.{0,30}expir'}
    return {'reason_codes': sorted(set(reasons)), 'categories': [
        name for name, pattern in rules.items() if re.search(pattern, combined, re.S)]}


def submit_login(page, credentials):
    """Type into native controls and verify contents before the Enter handler."""
    username, password = page.locator('#userName'), page.locator('#userPassword')
    username.wait_for(state='visible', timeout=60000)
    for field, value in ((username, credentials['username']), (password, credentials['password'])):
        field.click()
        # The supplied 1C focus handler schedules select() asynchronously.
        page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        field.fill('')
        field.press_sequentially(value, delay=35)
    matched = {'username_matches_saved': username.input_value() == credentials['username'],
               'password_matches_saved': password.input_value() == credentials['password']}
    if not all(matched.values()):
        raise ValueError('1C input differs from saved credentials; login was not submitted')
    # Observe only equality booleans at the actual submit event, before the
    # 1C key handler. Never retain input values in the diagnostic object.
    page.evaluate('''expected => {
        document.addEventListener('keydown', event => {
            if (event.key === 'Enter' && event.target.id === 'userPassword') {
                window.__courierInputCheck = {
                    username_matches_saved: document.querySelector('#userName').value === expected.username,
                    password_matches_saved: document.querySelector('#userPassword').value === expected.password
                };
            }
        }, {capture: true, once: true});
    }''', credentials)
    password.press('Enter')
    at_submit = page.evaluate('() => window.__courierInputCheck || null')
    if not at_submit or not all(at_submit.values()):
        raise ValueError('1C submit event input check failed')
    return {**matched, 'matches_at_submit': True, 'submit_method': 'native_keyboard_enter'}


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
        result['login_failures'] = []
        def dialog_received(dialog):
            shape = failure_shape(dialog.message)
            if shape['categories']:
                result['login_failures'].append(shape)
            dialog.dismiss()
        page.on('dialog', dialog_received)
        final_response = []
        def response_received(response):
            if urlsplit(response.url).path != PATH+'e1cib/login':
                return
            result['login_http_statuses'].append(response.status)
            if response.status != 200:
                try:
                    text = response.text()
                    result['login_failures'].append(failure_shape(text))
                    private_write(private/'onec-login-error-response.txt', text)
                except Exception:
                    result['error_response_unavailable'] = True
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
            result['input_check'] = submit_login(page, credentials)
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
