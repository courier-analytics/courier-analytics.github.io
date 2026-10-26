"""Read the collector's route without executing an environment file."""
import os
from pathlib import Path
from urllib.parse import urlsplit


def configured_proxy(path=Path('/etc/courier-analytics/proxy.env')):
    value = os.environ.get('COURIER_PROXY_URL')
    if value is None:
        try:
            matches = [line.split('=', 1)[1].strip() for line in path.read_text().splitlines()
                       if line.startswith('COURIER_PROXY_URL=')]
        except FileNotFoundError:
            matches = []
        if len(matches) > 1:
            raise ValueError('Ambiguous proxy configuration')
        value = matches[0] if matches else 'socks5h://127.0.0.1:18080'
    if value:
        parsed = urlsplit(value)
        if parsed.scheme not in ('socks5h', 'http', 'https') or not parsed.hostname or parsed.username or parsed.password or '\n' in value or '\r' in value:
            raise ValueError('Invalid proxy configuration')
    return value
