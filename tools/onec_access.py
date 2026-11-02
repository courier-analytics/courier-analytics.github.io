"""Inspect the authorized 1C web entry point without submitting credentials."""
import json
import os
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import zipfile
import tempfile
from urllib.parse import urlsplit, urljoin

from powerbi_access import corporate_interface
from prepare_openvpn import private_write
from probe_powerbi_vpn import private_address, response_metadata

HOST = 'couriers.int.vkusvill.ru'
PATH = '/couriers/ru_RU/'


class LoginShape(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs = []
        self.scripts = []
        self.forms = 0
        self.script_urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input':
            kind = attrs.get('type', 'text').lower()
            if kind in ('text', 'password', 'submit', 'hidden'):
                self.inputs.append(kind)
        if tag == 'form':
            self.forms += 1
        if tag == 'script' and attrs.get('src'):
            self.script_urls.append(attrs['src'])
            # Never log query strings, fragments, cookies or embedded values.
            path = urlsplit(attrs['src']).path
            name = path.rsplit('/', 1)[-1]
            if re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', name):
                self.scripts.append(name)


def asset_path(value, parent=PATH):
    url = urlsplit(urljoin('https://' + HOST + parent, value))
    if (url.scheme != 'https' or url.netloc != HOST or url.fragment or
            not re.fullmatch(re.escape(PATH) + r'(?:scripts/[A-Za-z0-9_-]+\.js|(?:mainform|authform)\.html)', url.path) or
            (url.query and not re.fullmatch(r'sysver=[0-9.]{1,40}', url.query))):
        raise ValueError('Unexpected 1C static resource URL')
    return url.path + ('?' + url.query if url.query else '')


def collect_assets(address, interface, folder, private, page):
    version = re.search(r'var\s+VERSION\s*=\s*["\']([0-9.]{1,40})["\']', page)
    if not version:
        raise ValueError('1C version missing from entry page')
    suffix = '?sysver=' + version.group(1)
    queue = [PATH + name + suffix for name in ('mainform.html', 'authform.html')]
    seen, files, total = set(), {'entry.html': page.encode()}, 0
    manifest = []
    while queue:
        path = asset_path(queue.pop(0))
        if path in seen:
            continue
        if len(seen) >= 12:
            raise ValueError('1C static resource limit reached')
        seen.add(path)
        output = folder/'onec-asset'
        private_write(output, '')
        command = ['curl', '--disable', '--proxy', '', '--noproxy', '*',
            '--interface', interface, '--silent', '--connect-timeout', '5', '--max-time', '12',
            '--max-filesize', '12000000', '--resolve', f'{HOST}:443:{address}',
            '--output', str(output), '--write-out', '%{http_code}', 'https://' + HOST + path]
        result = subprocess.run(command, capture_output=True, text=True, timeout=16)
        name = urlsplit(path).path.removeprefix(PATH)
        manifest.append({'file': name, 'curl_exit': result.returncode, 'http_status': result.stdout.strip()})
        if result.returncode or result.stdout.strip() != '200':
            continue
        data = output.read_bytes()
        total += len(data)
        if total > 24000000:
            raise ValueError('1C static resource bundle too large')
        files[name] = data
        if name.endswith('.html'):
            parser = LoginShape()
            parser.feed(data.decode('utf-8', errors='replace'))
            queue.extend(asset_path(src, urlsplit(path).path) for src in parser.script_urls)
    if 'mainform.html' not in files or 'authform.html' not in files:
        raise ValueError('1C login form resources unavailable')
    archive = folder/'onec-login-assets.zip'
    private_write(archive, '')
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)
        bundle.writestr('manifest.json', json.dumps(manifest))
    fd, name = tempfile.mkstemp(prefix='.onec-assets-', dir=private)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(archive.read_bytes())
        os.replace(name, private/'onec-login-assets.zip')
    finally:
        if os.path.exists(name):
            os.unlink(name)
    print('1C static login bundle saved privately; resources: '+str(len(files)), flush=True)


def inspect_page(address, folder, private=Path('/opt/courier-analytics/private'), assets=False):
    address = private_address(address)
    interface = corporate_interface(address)
    headers, body = folder/'onec-headers', folder/'onec-page'
    for file in (headers, body):
        private_write(file, '')
    command = ['curl', '--disable', '--proxy', '', '--noproxy', '*',
        '--interface', interface, '--silent', '--connect-timeout', '8', '--max-time', '25',
        '--max-filesize', '2000000', '--resolve', f'{HOST}:443:{address}',
        '--dump-header', str(headers), '--output', str(body), '--write-out', '%{http_code}',
        'https://' + HOST + PATH]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    code = result.stdout.strip()
    status = int(code) if re.fullmatch(r'[1-5][0-9]{2}', code) else None
    text = body.read_text(errors='replace')
    header_text = headers.read_text(errors='replace')
    parser = LoginShape()
    parser.feed(text)
    locations = re.findall(r'^Location:\s*([^\r\n]+)', header_text, re.I | re.M)
    location = urlsplit(locations[-1]) if locations else None
    summary = {'curl_exit': result.returncode, 'http_status': status,
        'auth_schemes': response_metadata(header_text), 'forms': parser.forms,
        'input_types': parser.inputs[:30], 'script_files': parser.scripts[:30],
        'one_c_markers': bool(re.search(r'1c:enterprise|1c enterprise|1с:предприятие|v8version|webclient', text, re.I)),
        'redirect_host': location.hostname if location else None,
        'redirect_same_host': bool(location and (not location.hostname or location.hostname == HOST)),
        'certificate_validation_failed': result.returncode == 60}
    if not result.returncode and status in (200, 401, 403):
        private.mkdir(parents=True, exist_ok=True)
        private_write(private/'onec-login-page.html', text)
        private_write(private/'onec-login-shape.json', json.dumps(summary, ensure_ascii=False))
        if assets and status == 200:
            collect_assets(address, interface, folder, private, text)
    print('1C entry point: '+json.dumps(summary, ensure_ascii=False), flush=True)
    print('No 1C credentials submitted; no courier rows read; dashboard unchanged.', flush=True)
    return result.returncode == 0 and status in (200, 401, 403)
