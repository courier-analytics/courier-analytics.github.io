"""Reload bot code only when no worker is running. Never interrupt a 1C worker."""
import os
import signal
import sqlite3
import subprocess
import time
from pathlib import Path
UNIT='courier-attendance-bot.service'
def main(before_stop=None):
    pid=int(subprocess.check_output(['systemctl','show',UNIT,'-p','MainPID','--value'],text=True).strip())
    if pid<=0:raise SystemExit('Bot is not running; inspect service before starting.')
    os.kill(pid,signal.SIGSTOP)
    terminating=False
    try:
        deadline=time.monotonic()+3
        while not any(line.startswith('State:') and line.split()[1] in ('T','t') for line in Path(f'/proc/{pid}/status').read_text().splitlines()):
            if time.monotonic()>=deadline:raise SystemExit('Could not confirm idle inspection pause; update deferred.')
            time.sleep(.05)
        # A stopped parent cannot launch a worker between the check and SIGTERM.
        children=Path(f'/proc/{pid}/task/{pid}/children').read_text().strip()
        with sqlite3.connect('file:/opt/courier-analytics/private/attendance-bot/cases.sqlite3?mode=ro',uri=True) as db:
            applying=db.execute("SELECT count(*) FROM cases WHERE state='applying'").fetchone()[0]
        if children or applying:raise SystemExit('Bot is processing a task; update deferred. Run again after it finishes.')
        if before_stop is not None:before_stop()
        os.kill(pid,signal.SIGTERM)
        terminating=True
    finally:
        try:os.kill(pid,signal.SIGCONT)
        except ProcessLookupError:pass
    if terminating:
        deadline=time.monotonic()+30
        while Path(f'/proc/{pid}').exists():
            if time.monotonic()>=deadline:raise SystemExit('Graceful stop pending; no forced termination performed.')
            time.sleep(.2)
        subprocess.run(['systemctl','start',UNIT],check=True)
        print('Bot code reloaded without interrupting a worker.')
if __name__=='__main__':main()
