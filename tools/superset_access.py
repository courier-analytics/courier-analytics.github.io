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
    headers = {'Accept': 'application/json', 'Referer': BASE + '/',
               'User-Agent': 'courier-analytics-superset/1.0'}
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
        try:
            data = json.loads(error.read(65536))
        except (ValueError, OSError, TypeError):
            data = None
        finally:
            error.close()
        return error.code, data


def login_diagnostic(data):
    # Return categories only, never server messages (may echo submitted credentials).
    message = data.get('message') if isinstance(data, dict) else None
    fields = [key for key in ('provider', 'username', 'password', 'refresh')
              if isinstance(message, dict) and key in message]
    return {'validation_fields': fields,
            'csrf_related': 'csrf' in json.dumps(data, ensure_ascii=True).lower()}


def dataset_structure(identity, result):
    # Schema only. Never return rows, SQL, owners or connection details.
    columns = result.get('columns') if isinstance(result.get('columns'), list) else []
    metrics = result.get('metrics') if isinstance(result.get('metrics'), list) else []
    return {'dataset_id': identity, 'table_name': result.get('table_name'),
            'columns': [{'name': c.get('column_name'), 'type': c.get('type'),
                         'is_datetime': bool(c.get('is_dttm'))} for c in columns if isinstance(c, dict)],
            'metrics': [m.get('metric_name') for m in metrics if isinstance(m, dict)]}


def inspect_metadata(opener, token, schedule=None):
    structures = []
    for identity in (6856, 6802, 4778):
        if identity == 6856 and schedule is not None:
            status, data = 200, schedule
        else:
            status, data = api(opener, '/api/v1/dataset/' + str(identity), token=token)
        result = data.get('result') if isinstance(data, dict) else None
        if status != 200 or not isinstance(result, dict):
            print('Dataset ' + str(identity) + ' metadata HTTP: ' + str(status), flush=True)
            continue
        schema = dataset_structure(identity, result)
        structures.append(schema)
        print('Dataset schema: ' + json.dumps(schema, ensure_ascii=False), flush=True)
    folder = Path('/opt/courier-analytics/private')
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_write(folder / 'superset-dataset-schema.json', json.dumps(structures, ensure_ascii=False, indent=2))
    print('Schema saved privately. No data rows queried; metric formulas not yet validated.', flush=True)


def check_protected_endpoints(opener, token, inspect_datasets=False):
    status, me = api(opener, '/api/v1/me/', token=token)
    print('Superset authenticated identity HTTP: ' + str(status), flush=True)
    identity_ok = status == 200 and isinstance(me, dict) and isinstance(me.get('result'), dict)
    status, csrf = api(opener, '/api/v1/security/csrf_token/', token=token)
    print('Superset authenticated CSRF HTTP: ' + str(status), flush=True)
    csrf_ok = status == 200 and isinstance(csrf, dict) and isinstance(csrf.get('result'), str) and bool(csrf['result'])
    if csrf_ok:
        opener.addheaders = list(opener.addheaders) + [('X-CSRFToken', csrf['result'])]
    status, dataset = api(opener, '/api/v1/dataset/6856', token=token)
    print('Schedule dataset 6856 metadata HTTP: ' + str(status), flush=True)
    dataset_ok = status == 200 and isinstance(dataset, dict) and isinstance(dataset.get('result'), dict)
    print('Dataset metadata access: ' + ('confirmed' if dataset_ok else 'not confirmed'), flush=True)
    for label, response in (('identity', me), ('csrf', csrf), ('dataset', dataset)):
        text = json.dumps(response).lower()
        print('Safe token diagnostic: ' + json.dumps({
            'endpoint': label, 'expired_reported': 'expired' in text,
            'signature_error_reported': 'signature' in text,
            'missing_authorization_reported': 'missing authorization' in text,
            'subject_error_reported': 'subject must be' in text}), flush=True)
    print('No tokens, personal data or dataset contents printed. Nothing published.', flush=True)
    if inspect_datasets and (csrf_ok or dataset_ok):
        inspect_metadata(opener, token, dataset if dataset_ok else None)
    return identity_ok or csrf_ok or dataset_ok


def check_login(provider_override=None, inspect_datasets=False):
    try:
        if CREDENTIALS.stat().st_mode & 0o077:
            raise ValueError('Credential permissions must be 600')
        saved = json.loads(CREDENTIALS.read_text())
        provider = provider_override or saved['provider']
        if provider not in ('ldap', 'db'):
            raise ValueError('Invalid authentication provider')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), NoRedirect())
        status, data = api(opener, '/api/v1/security/login', {
            'username': saved['username'], 'password': saved['password'],
            'provider': provider, 'refresh': False})
        print('Superset login HTTP: ' + str(status) + '; provider=' + provider, flush=True)
        if status != 200:
            print('Safe login diagnostic: ' + json.dumps(login_diagnostic(data)), flush=True)
        if status != 200 or not isinstance(data, dict) or not isinstance(data.get('access_token'), str) or not data['access_token']:
            return False
        token = data['access_token']
        return check_protected_endpoints(opener, token, inspect_datasets)
    except (OSError, ValueError, KeyError, TypeError):
        print('Superset check failed: file, network, TLS or response format; details hidden.', flush=True)
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--save', action='store_true')
    parser.add_argument('--provider', choices=('ldap', 'db'), default='ldap')
    args = parser.parse_args()
    if not args.save:
        raise SystemExit(0 if check_login(args.provider) else 1)
    username = getpass.getpass('Superset username (hidden): ').strip()
    password = getpass.getpass('Superset password (hidden): ')
    if not username or not password or any(c in username + password for c in '\r\n'):
        raise SystemExit('Empty/invalid input. Credentials unchanged.')
    private_write(CREDENTIALS, json.dumps({'username': username, 'password': password,
                                         'provider': args.provider}))
    print('Superset credentials saved privately, permissions 600. No login attempted.')


if __name__ == '__main__':
    main()
