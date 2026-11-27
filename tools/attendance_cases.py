"""Durable per-case human decisions. No approval by configuration or rule alone."""
import hashlib,json,os,secrets,sqlite3,time
from pathlib import Path
ROOT=Path('/opt/courier-analytics/private/attendance-bot')
DB=ROOT/'cases.sqlite3'
TERMINAL={'applied','skipped','withdrawn','uncertain'}

def connect(path=DB):
    path=Path(path);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=15);db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY,event TEXT UNIQUE,payload TEXT,state TEXT,current_limit INTEGER,target_limit INTEGER,observed REAL,message_id INTEGER,nonce TEXT,actor INTEGER,result TEXT,notified INTEGER DEFAULT 0)')
    columns={r[1] for r in db.execute('PRAGMA table_info(cases)')}
    for name,definition in [('read_attempts','INTEGER NOT NULL DEFAULT 0'),('next_attempt','REAL NOT NULL DEFAULT 0'),('last_read_error','TEXT'),('message_chat_id','INTEGER'),('actor_label','TEXT'),('notice_state','TEXT'),('message_kind','TEXT'),('cleanup_state','TEXT'),('cleanup_attempts','INTEGER NOT NULL DEFAULT 0'),('cleanup_after','REAL NOT NULL DEFAULT 0')]:
        if name not in columns:db.execute('ALTER TABLE cases ADD COLUMN '+name+' '+definition)
    db.execute('CREATE TABLE IF NOT EXISTS ledger (day TEXT,courier TEXT,state TEXT,case_id TEXT,PRIMARY KEY(day,courier))')
    db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT)');db.commit()
    return db

def fingerprint(row):
    return hashlib.sha256(json.dumps({k:row.get(k) for k in ('date','shop_id','courier_id','slot_id','planned_start','actual_start','source_status','late_seconds','proposed_measure')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def get(db,identity):
    row=db.execute('SELECT * FROM cases WHERE id=?',(identity,)).fetchone()
    if row is None:raise ValueError('Unknown review case')
    result=dict(row);result['payload']=json.loads(result['payload']);return result

def ingest(db,rows,ignored):
    live=set()
    for row in rows:
        identity=row['event_id'][:24];live.add(identity)
        existing=db.execute('SELECT * FROM cases WHERE id=?',(identity,)).fetchone()
        skip=any(x.get('date')==row['date'] and x.get('shop_id')==row['shop_id'] and str(x.get('courier_id'))==row['courier_id'] for x in ignored)
        state='skipped' if skip else 'held' if row['unresolved_facts'] or row['multiple_bookings_for_courier'] or not row.get('proposed_measure') else 'need_limit'
        if existing:
            if existing['state'] in TERMINAL or existing['state']=='applying':continue
            if fingerprint(json.loads(existing['payload']))==fingerprint(row):continue
            # Any factual change invalidates an earlier proposed/approved action.
            db.execute('UPDATE cases SET payload=?,state=?,current_limit=NULL,target_limit=NULL,observed=NULL,nonce=?,actor=NULL,read_attempts=0,next_attempt=0,notified=0 WHERE id=?',
                (json.dumps(row,ensure_ascii=False),state,secrets.token_hex(4),identity))
        else:
            db.execute('INSERT INTO cases(id,event,payload,state,nonce,notified) VALUES (?,?,?,?,?,?)',
                (identity,row['event_id'],json.dumps(row,ensure_ascii=False),state,secrets.token_hex(4),int(skip)))
    db.commit();return live

def proposed_target(current,measure):
    if type(current) is not int or current<1:raise ValueError('Current limit requires manual review')
    if measure.get('operation')=='set' and measure.get('value')==1:target=1
    elif measure.get('operation')=='subtract' and measure.get('value') in (1,2):target=current-measure['value']
    else:raise ValueError('Unrecognized measure')
    if not 1<=target<current:raise ValueError('No valid decrease; manual review required')
    return target

def callback_decision(db,identity,nonce,actor,chat_id,message_id,action,config,now=None):
    allowed=actor in config['approver_ids'] or (config.get('allow_group_members') is True and config.get('verified_member_id')==actor)
    if not allowed or chat_id!=config['chat_id']:raise ValueError('Not an authorized reviewer or group')
    if action not in ('apply','skip'):raise ValueError('Unknown action')
    now=time.time() if now is None else now
    db.execute('BEGIN IMMEDIATE')
    try:
        case=get(db,identity)
        if case.get('message_chat_id') is not None and case['message_chat_id']!=chat_id:raise ValueError('Message group mismatch')
        if case['state']!='pending_review' or case['nonce']!=nonce or case['message_id']!=message_id:raise ValueError('Stale or already handled button')
        if action=='apply':
            if case['target_limit'] is None:raise ValueError('No verified target limit')
            if not case['observed'] or case['observed']>now+120:raise ValueError('Limit observation timestamp invalid')
            if proposed_target(case['current_limit'],case['payload']['proposed_measure'])!=case['target_limit']:raise ValueError('Displayed proposal mismatch')
        state='approved' if action=='apply' else 'skipped'
        db.execute('UPDATE cases SET state=?,actor=?,actor_label=?,notified=0 WHERE id=?',(state,actor,config.get('actor_label'),identity));db.commit();return state
    except Exception:db.rollback();raise

def claim_write(db,identity):
    db.execute('BEGIN IMMEDIATE')
    try:
        case=get(db,identity)
        if case['state']!='approved' or not case['actor'] or not case['message_id']:raise ValueError('Individual human approval absent')
        p=case['payload']
        db.execute('INSERT INTO ledger(day,courier,state,case_id) VALUES (?,?,?,?)',(p['date'],p['courier_id'],'inflight',identity))
        db.execute("UPDATE cases SET state='applying' WHERE id=?",(identity,));db.commit()
    except Exception:db.rollback();raise
