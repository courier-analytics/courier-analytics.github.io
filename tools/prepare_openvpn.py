"""Prepare a restricted OpenVPN candidate; never start it or change the collector."""
import argparse
import ipaddress
import os
from pathlib import Path
import shlex
import socket
import tempfile

API_HOST = 'couriers-schedules.vkusvill.ru'
INLINE = {'ca', 'cert', 'key', 'tls-auth', 'tls-crypt', 'tls-crypt-v2'}
# Unknown options require review: profiles can otherwise execute local commands.
ALLOWED = set('client tls-client dev dev-type proto remote remote-random remote-random-hostname resolv-retry nobind persist-key persist-tun ca cert key tls-auth tls-crypt tls-crypt-v2 key-direction remote-cert-tls verify-x509-name cipher data-ciphers data-ciphers-fallback auth auth-user-pass auth-nocache auth-retry reneg-sec tls-version-min tls-version-max tls-cipher tls-ciphersuites verb mute explicit-exit-notify connect-retry connect-timeout connect-retry-max server-poll-timeout keepalive ping ping-restart ping-timer-rem tun-mtu mssfix sndbuf rcvbuf float fast-io setenv'.split())
REMOVED = {'redirect-gateway', 'redirect-private', 'route', 'route-ipv6', 'route-gateway', 'route-metric', 'route-nopull', 'pull-filter', 'dhcp-option', 'block-outside-dns', 'register-dns'}


def candidate(text, addresses, auth_path):
    lines, directives, embedded = [], set(), set()
    block = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if block:
            lines.append(raw)
            if line == '</' + block + '>':
                block = None
            continue
        if line.startswith('<'):
            tag = line[1:-1]
            if tag not in INLINE or line != '<' + tag + '>':
                raise ValueError('Unsupported inline block; contents hidden')
            if tag in embedded:
                raise ValueError('Duplicate inline block')
            embedded.add(tag)
            block = tag
            lines.append(line)
            continue
        args = shlex.split(line, comments=True)
        if not args:
            continue
        name = args[0].removeprefix('--')
        directives.add(name)
        if name in REMOVED or name in {'auth-user-pass', 'auth-nocache', 'auth-retry'}:
            continue
        if name not in ALLOWED:
            raise ValueError('Unsupported option: ' + name + '; values hidden')
        if name in INLINE and args[1:] != ['[inline]']:
            raise ValueError('External certificate/key file requires separate review: ' + name)
        if name == 'setenv' and args[1:] != ['CLIENT_CERT', '0']:
            raise ValueError('Unsupported environment option; values hidden')
        if name in {'dev', 'dev-type'} and args[1:] != ['tun']:
            raise ValueError('Only dev tun is supported')
        lines.append(line)
    if block:
        raise ValueError('Unclosed inline block')
    if 'remote' not in directives or 'dev' not in directives:
        raise ValueError('Profile must specify remote and dev tun')
    addresses = sorted({str(ipaddress.IPv4Address(a)) for a in addresses})
    if not addresses:
        raise ValueError('API IPv4 resolution failed')
    lines.extend(['', '# Candidate: no default-route or DNS changes.', 'route-nopull'])
    lines.extend('route ' + a + ' 255.255.255.255 vpn_gateway' for a in addresses)
    if 'auth-user-pass' in directives:
        lines.extend(['auth-user-pass ' + str(auth_path), 'auth-nocache', 'auth-retry none'])
    return '\n'.join(lines) + '\n', 'auth-user-pass' in directives


def private_write(path, content):
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            output.write(content)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, default=Path('/root/courier-openvpn.ovpn'))
    parser.add_argument('--output', type=Path, default=Path('/root/courier-openvpn-candidate.conf'))
    parser.add_argument('--auth', type=Path, default=Path('/root/courier-openvpn.auth'))
    args = parser.parse_args()
    if not args.auth.is_absolute() or any(c.isspace() for c in str(args.auth)):
        raise ValueError('Auth path must be absolute without whitespace')
    addresses = {r[4][0] for r in socket.getaddrinfo(API_HOST, 443, socket.AF_INET, socket.SOCK_STREAM)}
    config, needs_auth = candidate(args.profile.read_text(), addresses, args.auth)
    private_write(args.output, config)
    print('Restricted candidate prepared, permissions 600. Profile contents hidden.')
    print('Only API IPv4 destinations routed via VPN: ' + ', '.join(sorted(addresses)))
    print('Authentication file: ' + ('present' if args.auth.is_file() else 'missing') if needs_auth else 'Password authentication not requested.')
    print('VPN NOT started. DNS, SSH routes, collector and timers unchanged.')
    print('Corporate DNS/Superset/Power BI routes require separate verification.')


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        raise SystemExit(str(error))
    except OSError:
        raise SystemExit('Local file or DNS error; private details hidden.')
