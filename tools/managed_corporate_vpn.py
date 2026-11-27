"""Own the persistent corporate tunnel and its legacy exclusion lease."""
import os
from pathlib import Path
import signal
import subprocess
import time
from corporate_vpn_session import settings
from shared_vpn_resource import acquire

ROOT=Path('/etc/courier-vpn')
LOG=Path('/var/log/courier-corporate-vpn/private.log')


def main():
    os.umask(0o077)
    settings()
    lease=acquire(wait=600)
    worker=None
    def stop(*args):raise SystemExit(0)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        result=subprocess.run(['pgrep','-x','openvpn'],capture_output=True)
        if result.returncode!=1:
            print('Existing VPN process detected; not starting or stopping another tunnel',flush=True)
            return 75
        LOG.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        LOG.write_text('');LOG.chmod(0o600)
        worker=subprocess.Popen(['openvpn','--config',str(ROOT/'client.conf'),'--log',str(LOG),'--verb','3'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        connected=False
        started=time.monotonic()
        while worker.poll() is None:
            with LOG.open() as stream:
                stream.seek(max(0,LOG.stat().st_size-65536));tail=stream.read()
            if 'AUTH_FAILED' in tail:
                print('Managed VPN authentication rejected; automatic restarts disabled for this failure',flush=True)
                return 78
            if not connected and 'Initialization Sequence Completed' in tail:
                connected=True
                print('Managed corporate VPN connected; only configured host routes enabled',flush=True)
            if not connected and time.monotonic()-started>90:
                print('Managed VPN connection timeout; service will retry',flush=True)
                return 1
            time.sleep(1)
        if 'AUTH_FAILED' in LOG.read_text(errors='replace'):
            print('Managed VPN authentication rejected; automatic restarts disabled for this failure',flush=True)
            return 78
        print('Managed VPN process exited; service will retry',flush=True)
        return 1
    finally:
        if worker is not None and worker.poll() is None:
            worker.terminate()
            try:worker.wait(timeout=15)
            except subprocess.TimeoutExpired:
                worker.kill();worker.wait(timeout=5)
        lease.close()


if __name__=='__main__':raise SystemExit(main())
