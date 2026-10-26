"""Release only interactive systemd agents spawned below this proxy installer."""
import argparse
import os
from pathlib import Path
import signal
import time


def process(pid):
    root = Path('/proc')/str(pid)
    try:
        command = (root/'cmdline').read_bytes().split(b'\0')
        command = [part.decode(errors='replace') for part in command if part]
        stat = (root/'stat').read_text()
        parent = int(stat[stat.rfind(')')+2:].split()[1])
        return {'pid': pid, 'parent': parent, 'command': command,
                'exe': (root/'exe').resolve(strict=True).name}
    except (OSError, ValueError, IndexError):
        return None


def is_installer(info):
    return bool(info and info['exe'] in ('bash', 'dash') and
                any(Path(arg).name == 'install_server_proxy.sh' for arg in info['command'][1:]))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', type=int, required=True)
    args = parser.parse_args()
    original = process(args.installer)
    if not is_installer(original):
        raise SystemExit('Installer is no longer running or identity does not match; no processes changed.')
    deadline = time.monotonic()+45
    count = 0
    while time.monotonic() < deadline:
        current = process(args.installer)
        if not current or current['command'] != original['command']:
            print('Original installer exited. Read its result in the original terminal.', flush=True)
            break
        processes = {int(p.name): process(int(p.name)) for p in Path('/proc').iterdir() if p.name.isdigit()}
        descendants = {args.installer}
        for _ in range(8):
            descendants.update(pid for pid, info in processes.items() if info and info['parent'] in descendants)
        for pid in descendants-{args.installer}:
            info = processes.get(pid)
            if not info or info['exe'] != 'systemd-tty-ask-password-agent':
                continue
            parent = processes.get(info['parent'])
            if not parent or parent['exe'] != 'systemctl':
                continue
            # Recheck executable/parent just before signalling. Never signal
            # the password request process, VPN, SSH, proxy or systemctl itself.
            confirmed = process(pid)
            if confirmed and confirmed['exe'] == info['exe'] and confirmed['parent'] == info['parent']:
                try:
                    os.kill(pid, signal.SIGTERM)
                    count += 1
                    print('Closed installer-owned interactive systemd agent PID '+str(pid), flush=True)
                except ProcessLookupError:
                    pass
        time.sleep(.5)
    else:
        children = [p['exe'] for p in (process(int(d.name)) for d in Path('/proc').iterdir() if d.name.isdigit())
                    if p and p['parent'] == args.installer]
        print('Installer still running; direct child executable names: '+', '.join(children), flush=True)
    print('Interactive agents closed: '+str(count)+'. VPN/password requests were not modified.', flush=True)
