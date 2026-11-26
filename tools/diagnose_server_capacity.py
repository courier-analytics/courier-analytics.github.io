"""Read-only capacity and VPN contention snapshot; no credentials or command lines."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from collections import Counter


def run(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=20)
        return result.stdout if result.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''


def cpu():
    values = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
    return sum(values), values[3] + values[4], values[4], values[7]


def process(pid):
    root = Path('/proc') / str(pid)
    try:
        groups = root.joinpath('cgroup').read_text()
        units = re.findall(r'([\w@.\-]+\.service)', groups)
        return {'pid': int(pid), 'name': root.joinpath('comm').read_text().strip(), 'services': sorted(set(units))}
    except OSError:
        return {'pid': int(pid), 'exited': True}


def main():
    first = cpu()
    time.sleep(2)
    last = cpu()
    total = last[0] - first[0]
    report = {'cpu_count': os.cpu_count(), 'load_average': os.getloadavg(),
              'cpu_sample_seconds': 2, 'cpu_busy_percent': round(100 * (total - last[1] + first[1]) / total, 1) if total else None,
              'iowait_percent': round(100 * (last[2] - first[2]) / total, 1) if total else None,
              'steal_percent': round(100 * (last[3] - first[3]) / total, 1) if total else None}
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        if key in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'):
            memory[key + '_MiB'] = round(int(value.split()[0]) / 1024, 1)
    report['memory'] = memory
    disk = shutil.disk_usage('/')
    report['root_disk'] = {'used_percent': round(100 * disk.used / disk.total, 1), 'free_GiB': round(disk.free / 2**30, 2)}
    report['pressure'] = {name: Path('/proc/pressure', name).read_text().strip() for name in ('cpu', 'memory', 'io') if Path('/proc/pressure', name).exists()}
    locks = run(['lslocks', '--json', '--output', 'PID,PATH,MODE'])
    report['vpn_and_onec_locks'] = []
    if locks:
        for lock in json.loads(locks).get('locks', []):
            path = lock.get('path') or ''
            if 'courier' in path and ('vpn' in path or 'onec' in path or 'refresh.lock' in path):
                report['vpn_and_onec_locks'].append({**lock, 'process': process(lock['pid'])})
    report['openvpn_processes'] = [process(pid) for pid in run(['pgrep', '-x', 'openvpn']).split()]
    # No process arguments: these can contain tokens or credentials.
    report['top_processes'] = run(['ps', '-eo', 'pid,ppid,comm,pcpu,pmem,rss,etimes', '--sort=-pcpu']).splitlines()[:13]
    names = run(['systemctl', 'list-units', '--all', '--type=service', '--plain', '--no-legend', '--no-pager'])
    units = sorted(set(re.findall(r'\b(courier-[\w@.\-]+\.service)\b', names)))
    report['services'] = []
    patterns = {'vpn_queued': r'Corporate VPN resource queued', 'vpn_wait_expired': r'Corporate VPN queue wait expired|Corporate VPN still busy',
                'onec_busy': r'shared connection busy', 'timeouts': r'timeout|timed out', 'oom': r'out of memory|oom-kill'}
    for unit in units:
        props = run(['systemctl', 'show', unit, '-p', 'ActiveState', '-p', 'SubState', '-p', 'MemoryCurrent', '-p', 'MemoryPeak', '-p', 'CPUUsageNSec', '-p', 'NRestarts', '-p', 'ActiveEnterTimestamp', '-p', 'ExecMainStartTimestamp'])
        logs = run(['journalctl', '-u', unit, '--since', '24 hours ago', '-n', '3000', '-o', 'cat', '--no-pager'])
        counts = {key: len(re.findall(pattern, logs, re.I)) for key, pattern in patterns.items()}
        report['services'].append({'unit': unit, 'properties': dict(line.split('=', 1) for line in props.splitlines() if '=' in line), 'log_signals_last_24h_max_3000_lines': counts})
    report['timers'] = [line for line in run(['systemctl', 'list-timers', '--all', '--no-pager']).splitlines() if 'courier-' in line]
    report['note'] = 'Two-second CPU sample is not historical utilization. Process CPU is lifetime average. Log counts are signals, not unique failed jobs. No services, locks or tunnels changed.'
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
