"""Use the evidenced 1C login form; keep credentials and session details private."""
import getpass
import base64
import json
import os
from pathlib import Path
import stat
import re
import sys
import subprocess
import shlex
import tempfile
import zipfile
from urllib.parse import urlsplit

from prepare_openvpn import private_write

HOST = 'couriers.int.vkusvill.ru'
PATH = '/couriers/ru_RU/'
CREDENTIALS = Path('/root/courier-onec.json')


def corporate_interface(address):
    from powerbi_access import corporate_interface as resolve
    return resolve(address)


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


def wait_manual_login(page, completed, attempts=360):
    # input() here would block Playwright's synchronous event dispatch. Pump
    # events until the native login response arrives and the form is hidden.
    for _ in range(attempts):
        if page.is_closed():
            return False
        page.wait_for_timeout(500)
        if completed() and not page.locator('#userPassword').is_visible():
            return True
    return False


def compare_manual_inputs(page, expected, report, captured=None):
    if not page.url.startswith('https://' + HOST + PATH):
        raise ValueError('Unexpected origin for manual input comparison')
    page.locator('#userName').wait_for(state='visible', timeout=60000)
    def receive(value):
        keys = {'username_matches_vps', 'password_matches_vps'}
        if isinstance(value, dict) and set(value) == keys and all(type(v) is bool for v in value.values()):
            report['manual_input_vs_vps'] = value
    page.expose_function('__courierReportMatch', receive)
    if captured is not None:
        def capture(value):
            if (isinstance(value, dict) and set(value) == {'username', 'password'} and
                    all(isinstance(v, str) and v and len(v) <= 255 and
                        not any(ord(c) < 32 for c in v) for v in value.values())):
                captured[:] = [value]
        page.expose_function('__courierCaptureInput', capture)
    page.evaluate('''expected => {
        function compare(event) {
            const enter = event.type === 'keydown' && event.key === 'Enter' &&
                ['userName','userPassword'].includes(event.target.id);
            const click = event.type === 'pointerdown' && event.target.closest('#okButton');
            if (!enter && !click) return;
            const user = document.querySelector('#userName');
            const password = document.querySelector('#userPassword');
            if (user && password && expected) window.__courierReportMatch({
                username_matches_vps: user.value === expected.username,
                password_matches_vps: password.value === expected.password
            });
            if (user && password && window.__courierCaptureInput)
                window.__courierCaptureInput({username: user.value, password: password.value});
        }
        document.addEventListener('keydown', compare, true);
        document.addEventListener('pointerdown', compare, true);
    }''', expected)


def read_vps_credentials():
    # The user's existing SSH connection authenticates on /dev/tty. Capture
    # only stdout into memory; never echo or save the private JSON on the Mac.
    response = subprocess.run(['ssh', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'ConnectTimeout=20',
        '-o', 'ProxyCommand=nc -X 5 -x 127.0.0.1:10808 %h %p',
        'root@147.90.10.158', 'cat /root/courier-onec.json'],
        stdout=subprocess.PIPE, text=True, timeout=120)
    if response.returncode:
        raise ValueError('Could not read private VPS credentials for comparison')
    saved = json.loads(response.stdout)
    if not isinstance(saved, dict) or any(not isinstance(saved.get(k), str) or not saved[k]
                                         for k in ('username', 'password')):
        raise ValueError('Invalid private VPS credential format')
    return {k: saved[k] for k in ('username', 'password')}


def sync_verified_credentials(captured, authenticated):
    if not authenticated:
        return False
    if len(captured) != 1:
        raise ValueError('Successful manual input was not captured; VPS unchanged')
    # Password travels only in SSH stdin, never command arguments or local disk.
    code = '''import json,os,sys,tempfile,subprocess
data=json.load(sys.stdin)
if set(data)!={'username','password'} or not all(isinstance(v,str) and v and len(v)<=255 and not any(ord(c)<32 for c in v) for v in data.values()):
    raise SystemExit('Invalid credential input; VPS file unchanged')
fd,name=tempfile.mkstemp(prefix='.courier-onec-',dir='/root')
try:
    with os.fdopen(fd,'w') as stream:
        json.dump(data,stream)
    os.replace(name,'/root/courier-onec.json')
finally:
    if os.path.exists(name): os.unlink(name)
print('1C credentials synchronized privately; testing VPS login.',flush=True)
raise SystemExit(subprocess.run(['/opt/courier-analytics/onec-venv/bin/python','/opt/courier-analytics/dashboard-code/tools/probe_powerbi_vpn.py','--address','10.210.254.19','--onec-login']).returncode)
'''
    response = subprocess.run(['ssh', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'ConnectTimeout=20', '-o', 'ProxyCommand=nc -X 5 -x 127.0.0.1:10808 %h %p',
        'root@147.90.10.158', 'python3 -c '+shlex.quote(code)],
        input=json.dumps(captured[0]), text=True, timeout=300)
    captured.clear()
    print('VPS login verified: '+str(response.returncode == 0), flush=True)
    return response.returncode == 0


def open_roster_navigation(page):
    """Only open evidenced reference navigation, never edit or submit forms."""
    from playwright.sync_api import TimeoutError as BrowserTimeout
    for label in ('Самозанятые', 'Курьеры'):
        links = page.get_by_text(label, exact=True).and_(page.locator(':visible'))
        try:
            links.first.wait_for(state='visible', timeout=20000)
        except BrowserTimeout:
            return label
        # 1C can render the same caption on a wrapper and its inner span.
        # Prefer the evidenced leaf caption; never choose among distinct items.
        leaves = []
        for i in range(links.count()):
            link = links.nth(i)
            if link.evaluate('(e) => !Array.from(e.children).some(c => c.innerText?.trim() === e.innerText.trim())'):
                leaves.append(link)
        if len(leaves) != 1:
            return label
        leaves[0].click(timeout=5000)
        page.wait_for_timeout(3000)
    return None


def ensure_roster_filters(page, progress=None):
    """Restore only filter enablement; restore_values sets the actual comparisons and values."""
    prefix='form0_КомпоновщикНастроекПользовательскиеНастройкиЭлемент'
    for number,required in ((4,True),(5,True),(6,False),(7,True),(8,False)):
        identity=prefix+str(number)+'Использование'
        control=page.locator('[id="'+identity+'"]')
        if progress:progress(f'filter_{number}_visible')
        control.wait_for(state='visible',timeout=10000)
        selected=control.evaluate('(e)=>e.classList.contains("select")')
        if selected != required:
            if progress:progress(f'filter_{number}_click')
            control.click(timeout=5000)
            if progress:progress(f'filter_{number}_state')
            page.wait_for_function('''([id,required]) => {
                const e=document.getElementById(id);
                return e && e.classList.contains('select') === required;
            }''',arg=[identity,required],timeout=10000)
            page.wait_for_timeout(500)


def close_roster_popup(page):
    # A 1C popup can intercept clicks outside itself, including the caption.
    # Escape dismisses it without depending on a clickable background element.
    page.keyboard.press('Escape')
    page.wait_for_timeout(250)


def select_roster_shop(page):
    """Change only the list's point filter; no courier record is edited."""
    field = page.locator('[id="form0_НомерТочки_i0"]')
    field.wait_for(state='visible', timeout=20000)
    field.click()
    page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
    # 1C maintains its own edit buffer; fill() can leave the displayed value
    # different from the value committed by the framework.
    field.press('Control+A')
    field.press('Backspace')
    field.press_sequentially('7745', delay=100)
    field.press('Enter')
    field.press('Tab')
    page.wait_for_timeout(6000)
    if field.input_value().strip() != '7745':
        raise ValueError('1C list point filter was not retained')


def roster_filter_structure(page):
    # Only known list-filter values, never search text or courier form fields.
    return page.evaluate(r'''() => {
        const root = 'form0_КомпоновщикНастроекПользовательскиеНастройкиЭлемент';
        const ids = ['form0_НомерТочки_i0', 'form0_Служба_i0', ...[
            '4Значение_i0','5ВидСравненияЭлементаОтбора_i0',
            '7ВидСравненияЭлементаОтбора_i0','7Значение_i0'
        ].map(x => root+x)];
        const values = Object.fromEntries(ids.map(id => [id, document.getElementById(id)?.value ?? null]));
        const settings = Array.from(document.querySelectorAll('[id]'))
            .filter(e => [4,5,6,7,8].some(n => e.id.startsWith(root+n)))
            .slice(0,160).map(e => ({id:e.id, tag:e.tagName, class:e.className,
                role:e.getAttribute('role'), checked:e.getAttribute('aria-checked'),
                title:e.getAttribute('title'),
                text:e.tagName === 'INPUT' ? null : (e.textContent || '').trim().slice(0,500)}));
        const grid = Array.from(document.querySelectorAll('[id]'))
            .filter(e => e.id.startsWith('form0_') &&
                /Список|list|grid|scroll|pager/i.test(e.id)).slice(0,100)
            .map(e => ({id:e.id,tag:e.tagName,class:e.className,role:e.getAttribute('role')}));
        const table = document.getElementById('form0_Список');
        const grid_structure = table ? Array.from(table.querySelectorAll('*')).slice(0,250)
            .map(e => ({id:e.id,tag:e.tagName,class:e.className,role:e.getAttribute('role'),
                parent_id:e.parentElement?.id || '',children:e.children.length})) : [];
        const excluded_types = Array.from(document.querySelectorAll('.chipsItem[title]'))
            .map(e => e.getAttribute('title')).filter(t => /^\s*[0-9]+\s*-/.test(t));
        const enabled = n => document.getElementById(root+n+'Использование')?.classList.contains('select') === true;
        const excludedCodes = new Set(excluded_types.map(t => t.trim().split(/\s*-/)[0]));
        const typeBase=root+'5Значение';
        const typeChips=Array.from(document.querySelectorAll('[id]')).filter(e=>
            e.id.startsWith(typeBase+'_multipleValues_') && e.classList.contains('chipsItem') && Number.isInteger(parseInt(e.title,10)));
        const typeExtra=Number(document.getElementById(typeBase+'_multipleValues_more')?.textContent?.trim().replace('+','')||0);
        const type_count=typeChips.length+typeExtra;
        const type_scope_verified=type_count===2 && typeChips.length>0 && typeChips.every(e=>[6,9].includes(parseInt(e.title,10)));
        const search_empty = !(document.getElementById('form0_ФормаКоманднаяПанельСписокСтрокаПоиска_i0')?.value || '').trim();
        const verified = search_empty && type_scope_verified && values['form0_НомерТочки_i0'] === '7745' &&
            ['', 'Без отбора', 'No filter', 'Without filter'].includes(values['form0_Служба_i0']) &&
            ['Да','Yes'].includes(values[root+'4Значение_i0']) &&
            ['Не в списке','Not in list'].includes(values[root+'5ВидСравненияЭлементаОтбора_i0']) &&
            ['Не равно','Not equal'].includes(values[root+'7ВидСравненияЭлементаОтбора_i0']) &&
            values[root+'7Значение_i0'] === '1' && enabled(4) && enabled(5) && enabled(7) &&
            !enabled(6) && !enabled(8) && excludedCodes.size === 2 && excludedCodes.has('6') && excludedCodes.has('9');
        return {values,settings,grid,grid_structure,excluded_types,search_empty,type_count,filters_verified:verified,complete_roster:false};
    }''')


def capture_interface(page, private, inspect_roster=False, status=None):
    from playwright.sync_api import Error as BrowserError
    def mark(stage):
        if status is not None:status['stage']=stage
    mark('interface_main_surface')
    if page.locator('#userPassword').is_visible():
        raise ValueError('Cannot inspect interface while the password form is visible')
    page.locator('#mainSurface').wait_for(state='visible', timeout=30000)
    page.wait_for_timeout(3000)
    mark('roster_navigation')
    navigation_stopped_at = open_roster_navigation(page) if inspect_roster else None
    if inspect_roster and navigation_stopped_at is None:
        mark('roster_grid_ready')
        page.locator('[id="grid_form0_Список"] .gridBody').wait_for(state='visible',timeout=30000)
        page.wait_for_timeout(500)
        ensure_roster_filters(page,lambda stage:mark('before_point.'+stage))
        # The point change materializes the full comparison/list controls.
        # In the initial blank-point form type5 can be a scalar-only field.
        from onec_filters import restore_values
        mark('point_filter')
        select_roster_shop(page)
        ensure_roster_filters(page,lambda stage:mark('after_point.'+stage))
        restore_values(page,lambda stage:mark('after_point.'+stage))
        mark('excluded_types_popup')
        more = page.locator('[id="form0_КомпоновщикНастроекПользовательскиеНастройкиЭлемент5Значение_multipleValues_more"]')
        if more.is_visible():
            more.click()
            page.wait_for_timeout(500)
    structure = page.evaluate('''() => {
        const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
        return {
            controls: Array.from(document.querySelectorAll('button,[role=button],[role=menuitem],a'))
                .filter(e => visible(e) && (e.innerText || '').trim())
                .slice(0,200).map(e => ({id: e.id, role: e.getAttribute('role'),
                    text: e.innerText.trim().slice(0,160)})),
            fields: Array.from(document.querySelectorAll('#mainSurface input,#mainSurface select,[role=combobox],[role=checkbox]'))
                .filter(e => visible(e) && e.type !== 'password')
                .slice(0,100).map(e => {
                    const r = e.getBoundingClientRect();
                    return {id: e.id, tag: e.tagName, type: e.type || null,
                        role: e.getAttribute('role'), label: e.getAttribute('aria-label'),
                        disabled: !!e.disabled,
                        checked: e.type === 'checkbox' ? e.checked : e.getAttribute('aria-checked'),
                        bounds: {x:r.x,y:r.y,width:r.width,height:r.height}};
                }),
            labels: Array.from(document.querySelectorAll('#mainSurface *'))
                .filter(e => visible(e) && !e.children.length &&
                    !['INPUT','TEXTAREA','SCRIPT','STYLE'].includes(e.tagName) &&
                    (e.innerText || '').trim())
                .slice(0,400).map(e => ({id: e.id, tag: e.tagName,
                    text: e.innerText.trim().slice(0,160)})),
            column_headers: Array.from(document.querySelectorAll('th,[role=columnheader]'))
                .filter(visible).slice(0,50).map(e => (e.innerText || '').trim().slice(0,160))
        };
    }''')
    if inspect_roster:
        structure['navigation_stopped_at'] = navigation_stopped_at
        if navigation_stopped_at is None:
            structure['roster_filters'] = roster_filter_structure(page)
            mark('close_excluded_types_popup')
            close_roster_popup(page)
            ensure_roster_filters(page,lambda stage:mark('after_popup.'+stage))
            mark('roster_filters_validation')
            structure['roster_filters']=roster_filter_structure(page)
            if structure['roster_filters']['filters_verified'] is not True:
                raise ValueError('1C roster filters not verified')
            from onec_roster import sample_grid, inspect_export_dialog, export_id_list, verify_id_export
            mark('grid_sample')
            structure['roster_candidate'] = sample_grid(page)
            structure['roster_candidate']['filters_verified'] = structure['roster_filters']['filters_verified']
            mark('export_dialog')
            structure['export_dialog'] = inspect_export_dialog(page)
            if structure['export_dialog']['opened']:
                try:
                    mark('native_export')
                    structure['id_export'] = export_id_list(page, structure['roster_filters']['filters_verified'])
                except BrowserError:
                    structure['id_export'] = {'confirmed': False, 'reason': 'native_export_ui_operation_failed'}
                structure['native_roster'] = verify_id_export(structure['id_export'],
                    [row['courier_id'] for row in structure['roster_candidate']['couriers']])
    # Verified source data must not depend on an optional diagnostic screenshot.
    native = structure.get('native_roster', {})
    if native.get('verified') is True and structure.get('roster_filters', {}).get('filters_verified') is True:
        from onec_roster_cache import save
        count = save(native, structure['roster_filters'], private/'onec-rosters')
        mark('roster_cache_saved')
        print(f'1C verified roster saved privately: DS 7745, {count} couriers.', flush=True)
    # The bundle is private: it can include account/navigation labels. No
    # input values, whole DOM, HTTP bodies, headers, cookies or storage export.
    with tempfile.TemporaryDirectory(prefix='.onec-ui-', dir=private) as directory:
        folder = Path(directory)
        picture = folder/'interface.png'
        private_write(picture, '')
        mark('interface_screenshot')
        structure['screenshot_available']=False
        try:
            page.screenshot(path=str(picture),timeout=5000)
            structure['screenshot_available']=True
        except BrowserError:
            pass
        mark('interface_archive')
        fd, name = tempfile.mkstemp(prefix='.onec-ui-', dir=private)
        try:
            with os.fdopen(fd, 'wb') as output:
                with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
                    bundle.writestr('ui-structure.json', json.dumps(structure, ensure_ascii=False))
                    if structure['screenshot_available']:bundle.write(picture, 'interface.png')
            os.replace(name, private/'onec-interface.zip')
        finally:
            if os.path.exists(name):
                os.unlink(name)
    mark('interface_bundle_saved')
    print('1C interface saved privately: onec-interface.zip. No records edited.', flush=True)
    return structure


def save_failure_interface(page, private, stage):
    """Replace the prior archive with this run's safe diagnostic, even on UI timeout."""
    from datetime import datetime, timezone
    if page.locator('#userPassword').is_visible():
        raise ValueError('Cannot capture failure while login form is visible')
    data={'failure_stage':stage,'observed_at':datetime.now(timezone.utc).isoformat(),
          'roster_filters':roster_filter_structure(page),'screenshot_available':False}
    data['filter_selection_ui']=page.evaluate('''() => {
        const visible=e=>e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
        return Array.from(document.querySelectorAll('[id],[role=menuitem],[role=option],.submenuBlock'))
            .filter(e=>(/^form[1-9][0-9]*_/.test(e.id) || e.matches('[role=menuitem],[role=option],.submenuBlock')) && visible(e)).slice(0,200)
            .map(e=>({id:e.id,tag:e.tagName,class:e.className,title:e.getAttribute('title'),
                text:['INPUT','TEXTAREA'].includes(e.tagName)?null:(e.innerText||'').trim().slice(0,1000)}));
    }''')
    data['filter_settings_grids']=page.evaluate(r'''() => {
        return Array.from(document.querySelectorAll('[id]')).filter(e=>
            /^grid_form[1-9][0-9]*_/.test(e.id) && e.getClientRects().length).slice(0,8)
            .map(e=>({id:e.id,
                headers:Array.from(e.querySelectorAll('.gridHead .gridBox')).map(c=>(c.innerText||'').trim().slice(0,160)),
                rows:Array.from(e.querySelectorAll('.gridBody > .gridLine')).slice(0,80)
                    .map(r=>Array.from(r.children).filter(c=>c.classList.contains('gridBox'))
                        .map(c=>(c.innerText||'').trim().slice(0,300)))}));
    }''')
    with tempfile.TemporaryDirectory(prefix='.onec-failure-',dir=private) as folder:
        picture=Path(folder)/'interface.png'
        private_write(picture,'')
        try:
            page.screenshot(path=str(picture),timeout=5000)
            data['screenshot_available']=True
        except Exception:
            pass
        fd,name=tempfile.mkstemp(prefix='.onec-failure-',dir=private)
        try:
            with os.fdopen(fd,'wb') as output:
                with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
                    bundle.writestr('ui-structure.json',json.dumps(data,ensure_ascii=False))
                    if data['screenshot_available']:bundle.write(picture,'interface.png')
            os.replace(name,private/'onec-interface.zip')
        finally:
            if os.path.exists(name):os.unlink(name)


def check_login(address, private=Path('/opt/courier-analytics/private'), local_mac=False, comparison_credentials=None, sync_vps=False, inspect_ui=False, inspect_roster=False):
    from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
    if local_mac and (sys.platform != 'darwin' or address != '10.210.254.19'):
        raise ValueError('Local comparison requires the authorized Mac and fixed 1C address')
    credentials = None if local_mac else load_credentials()
    if sync_vps and not local_mac:
        raise ValueError('Credential synchronization requires local manual login')
    captured = []
    if not local_mac:
        corporate_interface(address)
    private.mkdir(parents=True, exist_ok=True)
    result = {'login_submitted': False, 'authenticated': False, 'login_http_statuses': [],
              'two_factor_required': False, 'password_change_required': False}
    if inspect_ui:
        result['interface_saved'] = False
    with sync_playwright() as playwright:
        options = {'headless': not local_mac}
        if local_mac:
            options['executable_path'] = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        if not local_mac:
            options['args'] = ['--no-proxy-server', '--disable-quic',
                               '--host-resolver-rules=MAP '+HOST+' '+address]
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(service_workers='allow' if local_mac else 'block', accept_downloads=False)
        # No TLS verification bypass, external redirects, credential URLs or
        # alternate network routes. Validate the VPN route before each request.
        def route_request(route):
            url = urlsplit(route.request.url)
            if url.scheme != 'https' or url.netloc != HOST or not url.path.startswith(PATH):
                route.abort()
                return
            try:
                if not local_mac:
                    corporate_interface(address)
            except (ValueError, OSError):
                route.abort()
                return
            route.continue_()
        if not local_mac:
            context.route('**/*', route_request)
            context.route_web_socket('**/*', lambda websocket: websocket.close())
        page = context.new_page()
        result['login_failures'] = []
        def dialog_received(dialog):
            shape = failure_shape(dialog.message)
            if shape['categories']:
                result['login_failures'].append(shape)
            dialog.dismiss()
        if not local_mac:
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
            if local_mac:
                if comparison_credentials is not None or sync_vps:
                    compare_manual_inputs(page, comparison_credentials, result, captured if sync_vps else None)
                print('Открылось отдельное окно Chrome. Войдите в 1С вручную. Проверка подождёт до трёх минут; в Терминале ничего нажимать не нужно.', flush=True)
                wait_manual_login(page, lambda: bool(final_response))
                result['login_submitted'] = bool(result['login_http_statuses'])
            else:
                # Showing the login dialog can follow an initial unauthenticated
                # HTTP 402. It is not the result of the supplied credentials.
                page.locator('#userName').wait_for(state='visible', timeout=60000)
                result['initial_login_http_count'] = len(result['login_http_statuses'])
                result['login_failures'] = []
                result['login_submitted'] = True
                result['input_check'] = submit_login(page, credentials)
                result['login_response_completed'] = wait_manual_login(
                    page, lambda: bool(final_response), attempts=90)
            result['authenticated'] = bool(final_response) and not page.locator('#userPassword').is_visible()
            result['two_factor_required'] = page.locator('#auth2FCodeField').is_visible()
            result['password_change_required'] = page.locator('#newPassword').is_visible()
            result['authenticated'] = result['authenticated'] and not (
                result['two_factor_required'] or result['password_change_required'])
            if result['authenticated']:
                result['login_failures'] = []
                if inspect_ui:
                    interface = capture_interface(page, private, inspect_roster=inspect_roster, status=result)
                    result['interface_saved'] = True
                    if inspect_roster:
                        result['roster_verified'] = interface.get('native_roster', {}).get('verified') is True and interface.get('roster_filters', {}).get('filters_verified') is True
                        result['roster_check'] = {
                            'filters_verified':interface.get('roster_filters',{}).get('filters_verified',False),
                            'export_reason':interface.get('id_export',{}).get('reason'),
                            'verification_reason':interface.get('native_roster',{}).get('reason'),
                            'count':interface.get('native_roster',{}).get('count')}
                # Only known navigation labels; never courier rows, account name,
                # full DOM, screenshots, response bodies or authentication tokens.
                labels = ('Курьеры', 'Справочники', 'Сотрудники', 'Отчеты', 'Отчёты', 'Доставка')
                result['navigation_labels'] = [text for text in labels if page.get_by_text(text, exact=True).count()]
            if local_mac:
                result['manual_authenticated'] = result['authenticated']
        except (BrowserTimeout,ValueError) as error:
            result['stage_timeout'] = isinstance(error,BrowserTimeout)
            if isinstance(error,ValueError):result['stage_validation_failed']=True
            if result['authenticated']:
                try:
                    save_failure_interface(page, private, result.get('stage','unknown'))
                    result['failure_snapshot_saved'] = True
                except Exception:
                    result['failure_snapshot_saved'] = False
        finally:
            context.close()
            browser.close()
    private_write(private/'onec-browser-status.json', json.dumps(result, ensure_ascii=False))
    print('1C browser login: '+json.dumps(result, ensure_ascii=False), flush=True)
    print('Verified 1C roster refreshed; metrics update in courier-refresh.service.' if result.get('roster_verified') else
          '1C roster not verified; previous private snapshot preserved.' if inspect_roster else
          'Login check only; public dashboard unchanged.', flush=True)
    if sync_vps and result['authenticated']:
        print('Ручной вход завершён. Теперь SSH запросит пароль сервера VPS для переноса подтверждённых реквизитов и проверки серверного входа.', flush=True)
        sync_verified_credentials(captured, result['authenticated'])
    return result['authenticated'] and (not inspect_ui or result['interface_saved']) and (not inspect_roster or result.get('roster_verified') is True)


if __name__ == '__main__':
    import tempfile
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compare-vps', action='store_true')
    parser.add_argument('--sync-vps', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('This entry point is only for local Mac comparison')
    try:
        expected = None
        if args.compare_vps:
            print('Сравнение с сохранёнными реквизитами VPS. SSH запросит пароль сервера VPS. Пароль 1С вводите затем только в открытом окне браузера.', flush=True)
            expected = read_vps_credentials()
        with tempfile.TemporaryDirectory(prefix='onec-local-check-') as directory:
            if args.sync_vps:
                print('После успешного ручного входа введённые реквизиты будут перенесены по SSH в приватный файл VPS. На Mac они не сохраняются.', flush=True)
            check_login('10.210.254.19', Path(directory), local_mac=True, comparison_credentials=expected, sync_vps=args.sync_vps)
    except Exception:
        raise SystemExit('Local browser comparison failed; private details hidden.') from None
