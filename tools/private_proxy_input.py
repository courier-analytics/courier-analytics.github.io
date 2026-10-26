"""Read a private VLESS link/subscription on the VPS without exposing it in argv."""
import argparse
import base64
import getpass
import json
from pathlib import Path
import urllib.parse
import urllib.request
import urllib.error
from uuid import UUID

from enrich_slots import atomic_json
from prepare_proxy_config import canonical_config


class ImportProblem(ValueError):
    """Contains only a fixed diagnostic code, never subscription content."""


def uri_node(link):
    url = urllib.parse.urlsplit(link.strip())
    if url.scheme != 'vless' or not url.hostname or not url.username or url.password:
        raise ValueError('Expected one VLESS URI')
    identity = str(UUID(urllib.parse.unquote(url.username)))
    query = urllib.parse.parse_qs(url.query, keep_blank_values=True)
    if any(len(values) != 1 for values in query.values()):
        raise ValueError('Repeated connection parameters')
    q = {key: values[0] for key, values in query.items()}
    if any(q.get(k, '').lower() not in ('', '0', 'false') for k in ('allowInsecure', 'insecure', 'skipCertVerify')):
        raise ValueError('TLS verification must remain enabled')
    security, network = q.get('security', 'tls'), q.get('type', 'tcp')
    if security not in ('tls', 'reality') or network not in ('tcp', 'raw', 'ws', 'grpc', 'xhttp'):
        raise ValueError('Unsupported connection type')
    user = {'id': identity, 'encryption': q.get('encryption', 'none')}
    if q.get('flow'):
        user['flow'] = q['flow']
    stream = {'network': network, 'security': security}
    settings = {'serverName': q.get('sni') or url.hostname, 'fingerprint': q.get('fp') or 'chrome'}
    if security == 'reality':
        settings.update(publicKey=q.get('pbk', ''), shortId=q.get('sid', ''))
        if q.get('spx'):
            settings['spiderX'] = q['spx']
        stream['realitySettings'] = settings
    else:
        if q.get('alpn'):
            settings['alpn'] = q['alpn'].split(',')
        stream['tlsSettings'] = settings
    if network == 'ws':
        stream['wsSettings'] = {'path': q.get('path', '/'), 'headers': {'Host': q.get('host') or url.hostname}}
    elif network == 'grpc':
        stream['grpcSettings'] = {'serviceName': q.get('serviceName', ''), 'multiMode': q.get('mode') == 'multi'}
    elif network == 'xhttp':
        stream['xhttpSettings'] = {'path': q.get('path', '/'), 'host': q.get('host', ''), 'mode': q.get('mode', 'auto')}
    node = {'protocol': 'vless', 'settings': {'vnext': [
        {'address': url.hostname, 'port': url.port or 443, 'users': [user]}]}, 'streamSettings': stream}
    canonical_config(node)
    return node


def parse_nodes(text):
    if len(text) > 2_000_000:
        raise ValueError('Input too large')
    text = text.strip()
    if not text:
        raise ImportProblem('empty_input_or_response')
    if text.startswith('happ://crypt'):
        raise ImportProblem('encrypted_happ_link_requires_standard_vless_export')
    if text.startswith('<'):
        raise ImportProblem('subscription_returned_html_not_connection_configuration')
    if text.startswith(('{', '[')):
        try:
            data = json.loads(text)
        except ValueError:
            raise ImportProblem('invalid_json_configuration') from None
        choices = data if isinstance(data, list) else [data]
        nodes = []
        for choice in choices:
            if isinstance(choice, dict) and isinstance(choice.get('outbounds'), list):
                candidates = [o for o in choice['outbounds'] if isinstance(o, dict) and o.get('protocol') == 'vless']
            else:
                candidates = [choice]
            for candidate in candidates:
                try:
                    canonical_config(candidate)
                    nodes.append(candidate)
                except (ValueError, TypeError, KeyError):
                    continue
        if not nodes:
            raise ImportProblem('json_has_no_supported_xray_vless_nodes')
        return nodes
    if 'vless://' not in text:
        try:
            encoded = ''.join(text.split())
            text = base64.b64decode(encoded+'='*(-len(encoded) % 4), altchars=b'-_', validate=True).decode()
        except (ValueError, UnicodeError):
            raise ImportProblem('not_vless_json_or_standard_base64_subscription') from None
        if text.strip().startswith(('{', '[', '<', 'happ://crypt')):
            return parse_nodes(text)
    nodes = []
    for line in text.splitlines():
        if line.strip().startswith('vless://'):
            try:
                nodes.append(uri_node(line))
            except (ValueError, TypeError, KeyError):
                continue
    if not nodes:
        raise ImportProblem('no_supported_vless_nodes_or_connection_parameters_invalid')
    return nodes


class HTTPSOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != 'https':
            raise ValueError('Subscription redirect must use HTTPS')
        return super().redirect_request(request, fp, code, message, headers, newurl)


def read_nodes(value):
    value = value.strip()
    for prefix in ('happ://add/', 'happ://add-profile/'):
        if value.startswith(prefix):
            value = urllib.parse.unquote(value[len(prefix):])
            break
    if value.startswith('happ://crypt'):
        raise ImportProblem('encrypted_happ_link_requires_standard_vless_export')
    if value.startswith('https://'):
        parsed = urllib.parse.urlsplit(value)
        if not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Invalid subscription URL')
        request = urllib.request.Request(value, headers={'User-Agent': 'courier-proxy-setup'})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), HTTPSOnlyRedirect())
        try:
            with opener.open(request, timeout=40) as response:
                content = response.read(2_000_001)
        except urllib.error.HTTPError as error:
            raise ImportProblem('subscription_http_'+str(error.code)) from None
        except (urllib.error.URLError, OSError):
            raise ImportProblem('subscription_connection_or_tls_failed') from None
        if len(content) > 2_000_000:
            raise ValueError('Subscription too large')
        value = content.decode('utf-8-sig')
    return parse_nodes(value)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/root/courier-private-node.json'))
    args = parser.parse_args()
    try:
        if not __import__('sys').stdin.isatty():
            raise ValueError('Use ssh -t for a private interactive prompt')
        private = getpass.getpass('Private VLESS link or HTTPS subscription (hidden): ').strip()
        nodes = read_nodes(private)
        index = 0
        if len(nodes) > 1:
            answer = input(f'Supported nodes: {len(nodes)}. Choose number [1]: ').strip() or '1'
            index = int(answer)-1
            if not 0 <= index < len(nodes):
                raise ValueError('Invalid node number')
        atomic_json(args.output, nodes[index])
        print('Private node saved, permissions 600. Secret not printed. Working network unchanged.')
    except ImportProblem as error:
        raise SystemExit('Private import failed: '+str(error)+'. Working network unchanged; secrets hidden.')
    except (ValueError, OSError, TypeError, KeyError, UnicodeError, EOFError):
        raise SystemExit('Private import failed. Need a standard VLESS link, Xray JSON or VLESS subscription. Working network unchanged; secrets hidden.')
