"""Borrow a managed tunnel concurrently, or own an isolated legacy test tunnel."""
from contextlib import contextmanager
import fcntl
import ipaddress
import json
from pathlib import Path
import subprocess
import tempfile
import time
from prepare_openvpn import private_write
from shared_vpn_resource import acquire, VPNBusy

SETTINGS=Path('/etc/courier-vpn/shared.json')
USERS=Path('/run/lock/courier-vpn-users.lock')
SERVICE='courier-corporate-vpn.service'


def settings(path=SETTINGS):
    info=path.lstat()
    if not path.is_file() or path.is_symlink() or info.st_uid!=0 or info.st_mode & 0o077:
        raise ValueError('Managed VPN settings permissions invalid')
    data=json.loads(path.read_text())
    if data.get('interface')!='tun42' or not isinstance(data.get('addresses'),list) or not data['addresses']:
        raise ValueError('Managed VPN settings invalid')
    for address in data['addresses']:
        if not ipaddress.IPv4Address(address).is_private:raise ValueError('Managed VPN requires corporate private destinations')
    return data


def ready(addresses,data):
    if subprocess.run(['systemctl','is-active','--quiet',SERVICE],capture_output=True,timeout=5).returncode:
        return False
    for address in addresses:
        result=subprocess.run(['ip','-j','route','get',address],capture_output=True,text=True,timeout=5)
        try:routes=json.loads(result.stdout) if result.returncode==0 else []
        except ValueError:return False
        if not isinstance(routes,list) or len(routes)!=1 or routes[0].get('dev')!=data['interface']:return False
    return True


@contextmanager
def session(config,addresses,seconds=240,wait=120):
    addresses=list(addresses)
    if SETTINGS.exists():
        # Shared users lease permits concurrent collectors, but lets maintenance
        # drain all active clients before stopping the managed service.
        with USERS.open('a') as users:
            try:fcntl.flock(users,fcntl.LOCK_SH|fcntl.LOCK_NB)
            except BlockingIOError:raise VPNBusy('Managed VPN maintenance; collection deferred') from None
            data=settings()
            if not set(addresses)<=set(data['addresses']):raise ValueError('Destination missing from managed VPN allowlist')
            if not ready(addresses,data):raise VPNBusy('Managed VPN not ready; no temporary tunnel started')
            with tempfile.TemporaryDirectory(prefix='courier-vpn-client-',dir='/root') as directory:
                print('Using managed corporate VPN; collector will not stop the tunnel',flush=True)
                yield Path(directory)
        return
    lease=acquire(wait=wait)
    try:
        if subprocess.run(['pgrep','-x','openvpn'],capture_output=True).returncode!=1:
            raise VPNBusy('Another VPN exists; no tunnel started')
        with tempfile.TemporaryDirectory(prefix='courier-vpn-test-',dir='/root') as directory:
            folder=Path(directory);profile=folder/'candidate.conf';log=folder/'private.log'
            private_write(profile,config);private_write(log,'')
            worker=subprocess.Popen(['timeout','--signal=TERM','--kill-after=5s',str(seconds)+'s','openvpn','--config',str(profile),'--log',str(log),'--verb','3'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+60
                while time.monotonic()<deadline:
                    contents=log.read_text(errors='replace')
                    if 'Initialization Sequence Completed' in contents:break
                    if worker.poll() is not None or 'AUTH_FAILED' in contents:raise ValueError('Temporary VPN connection failed; private details hidden')
                    time.sleep(.5)
                else:raise ValueError('Temporary VPN connection timeout')
                print('Temporary corporate VPN connected',flush=True)
                yield folder
            finally:
                if worker.poll() is None:
                    worker.terminate()
                    try:worker.wait(timeout=7)
                    except subprocess.TimeoutExpired:
                        worker.kill();worker.wait(timeout=3)
                print('Temporary VPN stopped; managed service unchanged',flush=True)
    finally:lease.close()
