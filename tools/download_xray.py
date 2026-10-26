"""Download a pinned official Xray artifact and verify SHA-256 before extraction."""
import argparse
import hashlib
import io
import os
from pathlib import Path
import platform
import tempfile
import urllib.request
from zipfile import ZipFile

VERSION = 'v26.10.21'
# Obtained from the official GitHub Release asset digest via verified HTTPS.
SHA256 = '0eec3ed4163c273d8c8bf821f7d219e257921cf584aa3fb970715e458e631978'
URL = f'https://github.com/XTLS/Xray-core/releases/download/{VERSION}/Xray-linux-64.zip'


def verified_binary(archive):
    if hashlib.sha256(archive).hexdigest() != SHA256:
        raise ValueError('Official artifact checksum mismatch')
    with ZipFile(io.BytesIO(archive)) as zipped:
        info = zipped.getinfo('xray')
        if info.file_size > 200_000_000:
            raise ValueError('Unexpected binary size')
        return zipped.read('xray')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'amd64'):
        raise SystemExit('This pinned package is for Linux x86_64 only')
    request = urllib.request.Request(URL, headers={'User-Agent': 'courier-proxy-installer'})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            archive = response.read(100_000_001)
        if len(archive) > 100_000_000:
            raise ValueError('Artifact exceeds size limit')
        binary = verified_binary(archive)
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.xray-', dir=args.destination.parent)
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(binary)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o755)
            os.replace(temporary, args.destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        print('Verified official Xray', VERSION, 'installed; SHA-256 matched.')
    except (ValueError, KeyError, OSError):
        raise SystemExit('Artifact download or verification failed; binary not replaced.')
