"""Separate credentials and lock for read-only secondary 1C tasks."""
import json
from pathlib import Path
import stat
from onec_browser import load_credentials,CREDENTIALS
SECONDARY=Path('/root/courier-onec-secondary.json')
ENABLED=Path('/etc/superset-telegram/onec-secondary.json')
PRIMARY_LOCK=Path('/opt/courier-analytics/onec-roster.lock')
SECONDARY_LOCK=Path('/opt/courier-analytics/onec-secondary.lock')


def secondary_credentials():
    primary=load_credentials(CREDENTIALS);secondary=load_credentials(SECONDARY)
    if primary['username'].strip().casefold()==secondary['username'].strip().casefold():
        raise ValueError('Secondary 1C account must differ from primary')
    return SECONDARY


def pool_account():
    if not ENABLED.exists():return 'primary',PRIMARY_LOCK
    info=ENABLED.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o077:
        raise ValueError('Secondary account mode permissions invalid')
    if json.loads(ENABLED.read_text()).get('pool_reads') is not True:
        raise ValueError('Secondary account mode invalid')
    secondary_credentials()
    return 'secondary',SECONDARY_LOCK
