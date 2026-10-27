"""Install the private Mac/RDP audit package without manual attachment downloads."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from zipfile import ZipFile

PACKAGE_SHA256 = '6602bbb6db16f47e258e17209be95cbf1a441f527d648bddac7b365a3bddeafb'
PACKAGE_FILES = {'audit_1c_v45_mac.py', 'run_1c_mac.command', 'README_MAC.md'}
AAD = b'audit-1c-v45-mac'


def download(url):
    if not url.startswith('https://raw.githubusercontent.com/courier-analytics/courier-analytics.github.io/'):
        raise ValueError('Unexpected package origin')
    result = subprocess.run(['/usr/bin/curl', '--fail', '--silent', '--show-error', '--location',
        '--proto', '=https', '--proto-redir', '=https', '--connect-timeout', '15', '--max-time', '90',
        '--retry', '2', '--max-filesize', '4000000', url], capture_output=True, check=True)
    if len(result.stdout) > 4_000_000:
        raise ValueError('Package too large')
    return result.stdout


def unpack(blob, key, destination):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if hashlib.sha256(blob).hexdigest() != PACKAGE_SHA256:
        raise ValueError('Package checksum failed')
    decrypted = AESGCM(bytes.fromhex(key)).decrypt(blob[:12], blob[12:], AAD)
    with ZipFile(io.BytesIO(decrypted)) as zipped:
        names = zipped.namelist()
        if len(names) != 3 or set(names) != PACKAGE_FILES:
            raise ValueError('Unexpected package files')
        # Verify every entry before writing; never use extractall.
        for item in zipped.infolist():
            if item.is_dir() or item.file_size > 2_000_000 or ((item.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError('Invalid package entry')
        for name in names:
            fd = os.open(destination/name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as out:
                out.write(zipped.read(name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-url', required=True)
    parser.add_argument('--unpack-into', type=Path)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('Этот установщик запускается в Terminal на Маке, не на VPS/Windows.')
    os.umask(0o077)
    # The key is supplied over stdin; never place it in URLs, argv or the public repository.
    key = sys.stdin.readline().strip()
    if len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
        raise ValueError('Invalid installation key')
    if args.unpack_into:
        folder = args.unpack_into
        unpack(download(args.package_url), key, folder)
        print('Файлы установлены:', folder, flush=True)
        print('Следующий запуск: bash '+shlex.quote(str(folder/'run_1c_mac.command')), flush=True)
        # stdin of this installer is a key pipe. Explicitly reopen the terminal
        # so the launch menu, calibration prompts and RDP tests remain interactive.
        with open('/dev/tty', 'r') as tty:
            return subprocess.run(['bash', str(folder/'run_1c_mac.command')], stdin=tty).returncode
    downloads = Path.home()/'Downloads'
    downloads.mkdir(exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='audit-1c-mac-', dir=downloads))
    print('Создаю отдельное окружение Python:', folder, flush=True)
    environment = folder/'.venv-1c'
    subprocess.run([sys.executable, '-m', 'venv', str(environment)], check=True)
    python = environment/'bin/python'
    print('Устанавливаю зависимости. Системный Python не меняется.', flush=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
        'cryptography', 'pyautogui', 'pyperclip', 'pillow',
        'pyobjc-framework-Cocoa', 'pyobjc-framework-Quartz'], check=True)
    return subprocess.run([str(python), str(Path(__file__).resolve()),
        '--package-url', args.package_url, '--unpack-into', str(folder)],
        input=key+'\n', text=True).returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit('Установка остановлена пользователем.')
    except Exception:
        raise SystemExit('Установка не завершена. Проверь доступ к GitHub/PyPI и Python 3. Ключ и содержимое пакета не выводились.')
