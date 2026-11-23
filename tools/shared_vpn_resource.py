"""Serialize corporate VPN sessions across Superset, 1C and Power BI.

The open lease must remain referenced until tunnel cleanup has finished.
"""
import fcntl,os,time
from pathlib import Path
LOCK=Path('/run/lock/courier-corporate-vpn.lock')
def acquire(path=LOCK,wait=120):
 handle=Path(path).open('a')
 deadline=time.monotonic()+wait;announced=False
 try:
  while True:
   try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB);return handle
   except BlockingIOError:
    if time.monotonic()>=deadline:raise RuntimeError('Corporate VPN queue wait expired; no tunnel started')
    if not announced:print('Corporate VPN resource queued; waiting for current job',flush=True);announced=True
    time.sleep(min(1,max(0,deadline-time.monotonic())))
 except BaseException:handle.close();raise
