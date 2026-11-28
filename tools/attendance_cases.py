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
    for name,definition in [('read_attempts','INTEGER NOT NULL DEFAULT 0'),('next_attempt','REAL NOT NULL DEFAULT 0'),('last_read_error','TEXT'),('message_chat_id','INTEGER'),('actor_label','TEXT'),('courier_transport','TEXT'),('write_stage','TEXT'),('last_write_error','TEXT'),('cleanup_state','TEXT'),('cleanup_attempts','INTEGER NOT NULL DEFAULT 0'),('cleanup_after','REAL NOT NULL DEFAULT 0')]:
        if name not in columns:db.execute('ALTER TABLE cases ADD COLUMN '+name+' '+definition)
    db.execute('CREATE TABLE IF NOT EXISTS ledger (day TEXT,courier TEXT,state TEXT,case_id TEXT,PRIMARY KEY(day,courier))')
    db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT)');db.commit()
    return db

def fingerprint(row):
    facts={k:row.get(k) for k in ('date','shop_id','courier_id','slot_id','planned_start','actual_start','source_status','late_seconds','proposed_measure')}
    if row.get('case_kind')=='early_departure':
        facts.update({k:row.get(k) for k in ('case_kind','source_date','planned_end','actual_end','early_departure_seconds')})
    return hashlib.sha256(json.dumps(facts,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

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
            db.execute('UPDATE cases SET payload=?,state=?,current_limit=NULL,target_limit=NULL,observed=NULL,courier_transport=NULL,nonce=?,actor=NULL,read_attempts=0,next_attempt=0,notified=0 WHERE id=?',
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

def case_target(case,current=None,transport=None):
    p=case['payload'];current=case['current_limit'] if current is None else current
    if p['shop_id']==8353:
        from attendance_8353 import capped_target
        return capped_target(current,p.get('late_seconds'),transport if transport is not None else case.get('courier_transport'))
    return proposed_target(current,p['proposed_measure'])

def callback_decision(db,identity,nonce,actor,chat_id,message_id,action,config,now=None):
    from attendance_shop_policy import enabled
    if not enabled(config,get(db,identity)['payload']['shop_id']):raise ValueError('Attendance disabled for this shop')
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
            if case_target(case)!=case['target_limit']:raise ValueError('Displayed proposal mismatch')
        state='approved' if action=='apply' else 'skipped'
        db.execute('UPDATE cases SET state=?,actor=?,actor_label=?,notified=0 WHERE id=?',(state,actor,config.get('actor_label'),identity));db.commit();return state
    except Exception:db.rollback();raise

def claim_write(db,identity):
    db.execute('BEGIN IMMEDIATE')
    try:
        case=get(db,identity)
        if case['state']!='approved' or not case['actor'] or not case['message_id']:raise ValueError('Individual human approval absent')
        p=case['payload']
        courier=p['courier_id']
        if p.get('case_kind')=='early_departure':
            if p['shop_id']!=8889 or p.get('early_departure_seconds',0)<3600 or p.get('proposed_measure')!={'operation':'set','value':1}:raise ValueError('Invalid early departure approval')
            # A separately approved early departure can follow a verified lateness
            # change, but must never run over an unknown/in-flight earlier write.
            prior=db.execute('SELECT state FROM ledger WHERE day=? AND courier=?',(p['date'],courier)).fetchone()
            if prior and prior['state']!='applied':raise ValueError('Previous courier write requires verification')
            courier+=':early_departure'
        else:
            prior=db.execute('SELECT 1 FROM ledger WHERE day=? AND courier=?',(p['date'],courier+':early_departure')).fetchone()
            if prior:raise ValueError('Early departure already claimed; no later lateness decrease')
        db.execute('INSERT INTO ledger(day,courier,state,case_id) VALUES (?,?,?,?)',(p['date'],courier,'inflight',identity))
        db.execute("UPDATE cases SET state='applying' WHERE id=?",(identity,));db.commit()
    except Exception:db.rollback();raise
