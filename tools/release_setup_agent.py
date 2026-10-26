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
        fields = stat[stat.rfind(')')+2:].split()
        parent = int(fields[1])
        return {'pid': pid, 'parent': parent, 'command': command,
                'started': fields[19],
                'exe': (root/'exe').resolve(strict=True).name}
    except (OSError, ValueError, IndexError):
        return None


def is_installer(info):
    return bool(info and info['exe'] in ('bash', 'dash') and
                any(Path(arg).name == 'install_server_proxy.sh' for arg in info['command'][1:]))


def same_agent(expected, candidate):
    return bool(candidate and candidate['exe'] == 'systemd-tty-ask-password-agent'
                and all(candidate[key] == expected[key] for key in ('pid', 'parent', 'started')))


def stop_agent(info):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        candidate = process(info['pid'])
        if not candidate:
            return 'exited'
        parent = process(info['parent'])
        if not same_agent(info, candidate) or not parent or parent['exe'] != 'systemctl':
            return 'identity_changed_no_signal'
        try:
            os.kill(info['pid'], sig)
        except ProcessLookupError:
            return 'exited'
        for _ in range(5):
            time.sleep(.1)
            if process(info['pid']) is None:
                return 'exited_after_'+sig.name
    return 'still_running_after_signals'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', type=int, required=True)
    args = parser.parse_args()
    original = process(args.installer)
    if not is_installer(original):
        raise SystemExit('Installer is no longer running or identity does not match; no processes changed.')
    deadline = time.monotonic()+45
    count = 0
    attempted = set()
    while time.monotonic() < deadline:
        current = process(args.installer)
        if not current or current['command'] != original['command'] or current['started'] != original['started']:
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
            identity = pid, info['started']
            if identity in attempted:
                continue
            attempted.add(identity)
            # Recheck executable/parent just before signalling. Never signal
            # the password request process, VPN, SSH, proxy or systemctl itself.
            confirmed = process(pid)
            if same_agent(info, confirmed):
                result = stop_agent(info)
                if result.startswith('exited'):
                    count += 1
                print('Installer-owned systemd agent PID '+str(pid)+': '+result, flush=True)
        time.sleep(.5)
    else:
        children = [p['exe'] for p in (process(int(d.name)) for d in Path('/proc').iterdir() if d.name.isdigit())
                    if p and p['parent'] == args.installer]
        print('Installer still running; direct child executable names: '+', '.join(children), flush=True)
    print('Interactive agents closed: '+str(count)+'. VPN/password requests were not modified.', flush=True)
