"""Private Superset credentials and read-only authentication checks."""
import argparse
import getpass
import http.cookiejar
import json
from pathlib import Path
import urllib.error
import urllib.request

from prepare_openvpn import private_write

BASE = 'https://superset.svc.vkusvill.ru'
CREDENTIALS = Path('/root/courier-superset.json')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api(opener, path, payload=None, token=None):
    headers = {'Accept': 'application/json'}
    body = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        body = json.dumps(payload).encode()
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(BASE + path, data=body, headers=headers)
    try:
        with opener.open(request, timeout=12) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        error.close()
        return error.code, None


def check_login():
    try:
        if CREDENTIALS.stat().st_mode & 0o077:
            raise ValueError('Credential permissions must be 600')
        saved = json.loads(CREDENTIALS.read_text())
        provider = saved['provider']
        if provider not in ('ldap', 'db'):
            raise ValueError('Invalid authentication provider')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), NoRedirect())
        status, data = api(opener, '/api/v1/security/login', {
            'username': saved['username'], 'password': saved['password'],
            'provider': provider, 'refresh': False})
        print('Superset login HTTP: ' + str(status), flush=True)
        if status != 200 or not isinstance(data, dict) or not isinstance(data.get('access_token'), str) or not data['access_token']:
            return False
        token = data['access_token']
        status, me = api(opener, '/api/v1/me/', token=token)
        print('Superset authenticated identity HTTP: ' + str(status), flush=True)
        if status != 200 or not isinstance(me, dict) or not isinstance(me.get('result'), dict):
            return False
        status, _ = api(opener, '/api/v1/dataset/6856', token=token)
        print('Schedule dataset 6856 metadata HTTP: ' + str(status), flush=True)
        print('No tokens, personal data or dataset contents printed. Nothing published.', flush=True)
        return True
    except (OSError, ValueError, KeyError, TypeError):
        print('Superset check failed: file, network, TLS or response format; details hidden.', flush=True)
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--save', action='store_true')
    parser.add_argument('--provider', choices=('ldap', 'db'), default='ldap')
    args = parser.parse_args()
    if not args.save:
        raise SystemExit(0 if check_login() else 1)
    username = getpass.getpass('Superset username (hidden): ').strip()
    password = getpass.getpass('Superset password (hidden): ')
    if not username or not password or any(c in username + password for c in '\r\n'):
        raise SystemExit('Empty/invalid input. Credentials unchanged.')
    private_write(CREDENTIALS, json.dumps({'username': username, 'password': password,
                                         'provider': args.provider}))
    print('Superset credentials saved privately, permissions 600. No login attempted.')


if __name__ == '__main__':
    main()
