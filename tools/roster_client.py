"""Use the site's own authenticated-profile -> 1C roster flow, without logging PII."""
import base64
import binascii
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import urlencode

from discover_scopes import items
from enrich_slots import atomic_json

WORKER = 'https://courator-api-proxy.vkusvill-curator.workers.dev'


class RosterError(RuntimeError):
    pass


def request(path, headers, proxy, form_file=None):
    allowed = (path == '/delivery/v1/courier/courier' or
               path == '/auth/api/v1/couriers/auth/1c' or
               re.fullmatch(r'/delivery/v1/couriers\?shopno=(5818|7745|4747)', path))
    if not allowed:
        raise RosterError('roster_path_not_allowed')
    if any('\n' in str(v) or '\r' in str(v) for v in headers.values()):
        raise RosterError('invalid_auth_headers')
    command = ['curl', '--silent', '--show-error', '--connect-timeout', '10',
               '--max-time', '40', '--max-filesize', '20000000', '--header', '@-',
               '--write-out', '\n%{http_code}']
    if proxy:
        command += ['--proxy', proxy, '--noproxy', '']
    if form_file is not None:
        # The actual name is read from a private file, not exposed in argv.
        command += ['--form', 'name=<' + str(form_file)]
    try:
        result = subprocess.run(command + [WORKER+path],
            input=''.join(key+': '+str(value)+'\n' for key, value in headers.items()),
            capture_output=True, text=True, timeout=50)
    except subprocess.TimeoutExpired:
        raise RosterError('roster_connection_timeout') from None
    if result.returncode:
        raise RosterError(f'roster_connection_curl_{result.returncode}')
    body, _, status = result.stdout.rpartition('\n')
    if status not in ('200', '204'):
        raise RosterError(f'roster_http_{status}')
    if not body.strip():
        return None
    try:
        value = json.loads(body)
    except ValueError:
        if re.fullmatch(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', body.strip()):
            return body.strip()
        raise RosterError('roster_response_not_json') from None
    if isinstance(value, dict) and value.get('code') not in (None, 0, '0') and (value.get('message') or value.get('error')):
        raise RosterError('roster_application_error')
    return value


def extract_token(value, depth=0):
    if depth > 4:
        return None
    if isinstance(value, str) and re.fullmatch(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', value.strip()):
        return value.strip()
    if isinstance(value, dict):
        for key in ('token', 'jwt', 'access_token', 'accessToken', 'data', 'result', 'auth'):
            token = extract_token(value.get(key), depth+1)
            if token:
                return token
    return None


def expires_at(token, now):
    # Used only for cache scheduling. The API validates the JWT signature.
    try:
        segment = token.split('.')[1]
        payload = json.loads(base64.urlsafe_b64decode(segment+'='*(-len(segment) % 4)))
        expiry = float(payload['exp'])
        return min(expiry, now+3600) if expiry > now else now
    except (ValueError, KeyError, IndexError, TypeError, binascii.Error, UnicodeError):
        return now+300


def one_c_token(primary, proxy, cache, source=Path('/root/curator-app.js'), force=False):
    fingerprint = hashlib.sha256(primary.encode()).hexdigest()
    now = time.time()
    try:
        saved = json.loads(cache.read_text())
        if (not force and saved.get('primary_session_hash') == fingerprint and
                saved.get('valid_until', 0) > now+60 and extract_token(saved.get('token'))):
            return saved['token']
    except (ValueError, OSError, TypeError):
        pass
    # Only the caller's own profile is used. No arbitrary name input is accepted.
    profile = request('/delivery/v1/courier/courier', {
        'Accept': 'application/json', 'Accept-Language': 'ru-RU',
        'x-vkusvill-device': 'seagull_team', 'Authorization': 'Bearer '+primary,
        'x-vkusvill-token': primary}, proxy)
    name = profile.get('name_courier') if isinstance(profile, dict) else None
    if not isinstance(name, str) or not name.strip():
        raise RosterError('own_profile_name_missing')
    try:
        javascript = source.read_text()
    except OSError:
        raise RosterError('source_client_configuration_missing') from None
    key = re.search(r'function Oq\(\)\{return[`"\']([^`"\']+)[`"\']', javascript)
    if not key:
        raise RosterError('source_client_configuration_unknown')
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8') as field:
        field.write(name.replace('\r', ' ').replace('\n', ' ').strip())
        field.flush()
        auth = request('/auth/api/v1/couriers/auth/1c', {
            'Accept': 'application/json, text/plain, */*',
            'x-vkusvill-device': 'seagull_team_1c', 'x-vkusvill-token': key.group(1)},
            proxy, form_file=Path(field.name))
    token = extract_token(auth)
    if not token:
        raise RosterError('one_c_session_not_received')
    atomic_json(cache, {'token': token, 'primary_session_hash': fingerprint,
                        'valid_until': expires_at(token, now)})
    return token


def normalize(payload, shop):
    if payload is None:
        rows = []
    else:
        rows = items(payload)
    if isinstance(payload, dict):
        if payload.get('has_more') or payload.get('next_page') or payload.get('next'):
            raise RosterError('roster_pagination_incomplete')
        for key in ('total', 'total_count'):
            if payload.get(key) is not None and int(payload[key]) > len(rows):
                raise RosterError('roster_pagination_incomplete')
    identities = set()
    for row in rows:
        if not isinstance(row, dict):
            raise RosterError('roster_row_format_unknown')
        identity = str(row.get('id') or '').strip()
        if not identity.isdigit():
            raise RosterError('roster_id_mapping_unknown')
        scope = row.get('shopno', row.get('shop_id'))
        if scope is not None and int(scope) != shop:
            raise RosterError('roster_scope_mismatch')
        identities.add(identity)
    return {'verified': True, 'courier_ids': sorted(identities),
            'source': 'site_one_c_couriers_filtered_by_shopno',
            'raw_rows': len(rows), 'duplicate_rows': len(rows)-len(identities)}


def get_rosters(primary, proxy, cache, shops=(5818, 7745, 4747), source=Path('/root/curator-app.js')):
    token = one_c_token(primary, proxy, cache, source)
    rosters, errors = {}, {}
    for shop in shops:
        headers = {'Accept': 'application/json', 'Accept-Language': 'ru-RU',
                   'Authorization': 'Bearer '+token, 'x-vkusvill-device': 'seagull_team_1c',
                   'x-vkusvill-token': token}
        try:
            payload = request('/delivery/v1/couriers?'+urlencode({'shopno': shop}), headers, proxy)
            rosters[shop] = normalize(payload, shop)
        except RosterError as error:
            errors[shop] = str(error)
    return rosters, errors
