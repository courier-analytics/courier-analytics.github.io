"""Inspect the authorized 1C web entry point without submitting credentials."""
import json
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

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

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input':
            kind = attrs.get('type', 'text').lower()
            if kind in ('text', 'password', 'submit', 'hidden'):
                self.inputs.append(kind)
        if tag == 'form':
            self.forms += 1
        if tag == 'script' and attrs.get('src'):
            # Never log query strings, fragments, cookies or embedded values.
            path = urlsplit(attrs['src']).path
            name = path.rsplit('/', 1)[-1]
            if re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', name):
                self.scripts.append(name)


def inspect_page(address, folder, private=Path('/opt/courier-analytics/private')):
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
    print('1C entry point: '+json.dumps(summary, ensure_ascii=False), flush=True)
    print('No 1C credentials submitted; no courier rows read; dashboard unchanged.', flush=True)
    return result.returncode == 0 and status in (200, 401, 403)
