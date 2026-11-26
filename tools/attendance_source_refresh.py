"""Refresh attendance evidence in a separate process, never polling Telegram."""
import fcntl
import json
import os
from datetime import datetime
from attendance_cases import ROOT,connect
from attendance_review import TZ

def run_once(db,config,collector):
    try:
        collector(db,config)
    except (OSError,ValueError,RuntimeError,KeyError,TypeError) as error:
        from verify_server_proxy import error_code
        reason=error_code(error)
        db.execute("INSERT OR REPLACE INTO meta VALUES('last_source_error',?)",(reason,));db.commit()
        print('Evidence refresh failed:',reason,flush=True)
        return 1
    db.execute("INSERT OR REPLACE INTO meta VALUES('last_source_success',?)",(datetime.now(TZ).isoformat(),))
    db.execute("DELETE FROM meta WHERE key='last_source_error'");db.commit()
    return 0

def main():
    os.umask(0o077)
    with (ROOT/'source-refresh.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return 75
        from attendance_bot import collect,CONFIG
        config=json.loads(CONFIG.read_text())
        db=connect()
        try:return run_once(db,config,collect)
        finally:db.close()
if __name__=='__main__':raise SystemExit(main())
