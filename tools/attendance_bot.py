"""Attendance review bot: two authorized humans, one explicit decision per case."""
import fcntl,json,os,re,secrets,signal,subprocess,sys,time
from datetime import datetime
from pathlib import Path
from attendance_cases import connect,get,ingest,DB,ROOT,TERMINAL
from attendance_review import review_rows,TZ,START
from late_bot_group import load_token,api
from audit_sources import audit
from proxy_config import configured_proxy
CONFIG=Path('/etc/superset-telegram/late-group.json')

def message(case):
    p=case['payload'];minutes=p.get('late_seconds')
    late='\nОпоздание: '+str(round(minutes/60,2))+' мин.' if minutes is not None else ''
    text=f"ДС {p['shop_id']} · {p['date']}\n{p['name']} · ID {p['courier_id']}\nНачало слота: {p['planned_start']}\nСтатус источника: {p['source_status']}"+late
    if case['current_limit'] is not None:text+='\nТекущий лимит: '+str(case['current_limit'])
    if case['target_limit'] is not None:text+='\nПредлагаемый лимит: '+str(case['target_limit'])+'\nПроверьте обстоятельства перед подтверждением.'
    else:text+='\nФакты или допустимый лимит требуют ручной проверки. Применение недоступно.'
    return text

def buttons(case):
    result=[]
    if case['target_limit'] is not None:result.append({'text':'Применить','callback_data':'att:a:'+case['id']+':'+case['nonce']})
    result.append({'text':'Пропустить','callback_data':'att:s:'+case['id']+':'+case['nonce']})
    return {'inline_keyboard':[result]}

def collect(db,config):
    day=datetime.now(TZ).date()
    if day<START:return
    token=json.loads(Path('/root/curator-session.json').read_text())['token']
    folder=ROOT/'source'/day.isoformat()
    summary=audit(day.isoformat(),token,configured_proxy(),folder,extra_details=False)
    if not {8889,7745,9107}<={s['shop_id'] for s in summary['shops'] if s.get('scope_verified')}:raise ValueError('All three source scopes must be verified')
    rows=review_rows(json.loads((folder/'all-shops-observations.json').read_text()),day.isoformat())
    live=ingest(db,rows,config.get('ignored_cases',[]))
    for row in db.execute('SELECT id,state,payload FROM cases').fetchall():
        p=json.loads(row['payload'])
        if row['state'] not in TERMINAL|{'applying'} and (p['date']!=day.isoformat() or row['id'] not in live):
            db.execute("UPDATE cases SET state='withdrawn',notified=0 WHERE id=?",(row['id'],))
    db.commit()

def handle_callback(db,update,config,token):
    from attendance_cases import callback_decision
    q=update.get('callback_query');
    if not isinstance(q,dict):return
    data=q.get('data','')
    if not data.startswith('att:'):return
    try:
        match=re.fullmatch(r'att:([as]):([0-9a-f]{24}):([0-9a-f]{8})',data)
        if not match:raise ValueError('Invalid callback')
        action,identity,nonce=match.groups();actor=q['from']['id'];msg=q['message']
        if q['from'].get('is_bot') or actor not in config['approver_ids']:raise ValueError('Not an approver')
        member=api(token,'getChatMember',{'chat_id':config['chat_id'],'user_id':actor})
        if member.get('status') not in ('administrator','creator'):raise ValueError('Admin rights required')
        outcome=callback_decision(db,identity,nonce,actor,msg['chat']['id'],msg['message_id'],'apply' if action=='a' else 'skip',config)
        answer='Подтверждение принято; проверяем данные и сохраняем в 1С.' if outcome=='approved' else 'Пропущено.' if outcome=='skipped' else 'Лимит устарел. Перечитаем и запросим подтверждение заново.'
        # Strip buttons immediately; durable database state is the authority.
        try:api(token,'editMessageReplyMarkup',{'chat_id':config['chat_id'],'message_id':msg['message_id'],'reply_markup':{'inline_keyboard':[]}})
        except RuntimeError:pass
    except (ValueError,KeyError,TypeError):answer='Кнопка устарела, уже обработана или у вас нет права подтверждения.'
    api(token,'answerCallbackQuery',{'callback_query_id':q['id'],'text':answer})

def notify(db,config,token):
    for row in db.execute("SELECT id FROM cases WHERE state IN ('ready','held') AND notified=0").fetchall():
        case=get(db,row['id'])
        if case['state']=='ready' and (not case['observed'] or time.time()-case['observed']>300):
            db.execute("UPDATE cases SET state='need_limit' WHERE id=?",(case['id'],));db.commit();continue
        db.execute("UPDATE cases SET state='sending' WHERE id=?",(case['id'],));db.commit()
        try:
            sent=api(token,'sendMessage',{'chat_id':config['chat_id'],'text':message(case),'reply_markup':buttons(case)})
            if type(sent.get('message_id')) is not int:raise RuntimeError('Message unconfirmed')
            db.execute("UPDATE cases SET state='pending_review',message_id=?,notified=1 WHERE id=?",(sent['message_id'],case['id']));db.commit()
        except RuntimeError:
            db.execute("UPDATE cases SET state='delivery_uncertain',notified=1 WHERE id=?",(case['id'],));db.commit();raise
    for row in db.execute("SELECT id FROM cases WHERE state IN ('applied','skipped','withdrawn','uncertain') AND notified=0").fetchall():
        case=get(db,row['id']);p=case['payload']
        labels={'applied':'Сохранено в 1С и проверено повторным открытием карточки.','skipped':'Пропущено ответственным.','withdrawn':'Случай отозван: факты изменились или дата закончилась.','uncertain':'Результат сохранения не подтверждён. Нужна ручная проверка; повторного уменьшения не будет.'}
        text=message(case)+'\n\n'+labels[case['state']]
        if case.get('actor'):text+='\nРешение принял Telegram ID '+str(case['actor'])
        if not case['message_id']:
            db.execute('UPDATE cases SET notified=1 WHERE id=?',(case['id'],));db.commit();continue
        try:api(token,'editMessageText',{'chat_id':config['chat_id'],'message_id':case['message_id'],'text':text,'reply_markup':{'inline_keyboard':[]}})
        except RuntimeError:
            # Do not send duplicate outcome notifications on uncertain network I/O.
            pass
        db.execute('UPDATE cases SET notified=1 WHERE id=?',(case['id'],));db.commit()

def start_job(db):
    # Approved cases take priority so the reviewed current value remains fresh.
    row=db.execute("SELECT id,state FROM cases WHERE state IN ('approved','need_limit') ORDER BY CASE state WHEN 'approved' THEN 0 ELSE 1 END,rowid LIMIT 1").fetchone()
    if not row:return None
    mode='apply' if row['state']=='approved' else 'read'
    if mode=='read':db.execute("UPDATE cases SET state='reading' WHERE id=?",(row['id'],));db.commit()
    log=(ROOT/'worker.log').open('a')
    try:
        process=subprocess.Popen(['flock','-n','/opt/courier-analytics/onec-roster.lock',
            '/opt/courier-analytics/onec-venv/bin/python',str(Path(__file__).with_name('probe_powerbi_vpn.py')),
            '--address','10.210.254.19','--onec-attendance-case',row['id'],'--onec-attendance-mode',mode],stdout=log,stderr=subprocess.STDOUT,start_new_session=False)
    except Exception:
        if mode=='read':db.execute("UPDATE cases SET state='need_limit' WHERE id=?",(row['id'],));db.commit()
        raise
    finally:log.close()
    return process,row['id'],mode,time.monotonic()

def finish_job(db,job,timeout=False):
    process,identity,mode,_=job
    state=get(db,identity)['state']
    if state=='applying':
        db.execute("UPDATE cases SET state='uncertain',result='Worker interrupted; verify manually',notified=0 WHERE id=?",(identity,))
    elif state in ('approved','reading'):
        # A failed pre-write verification needs another human review, not an
        # automatic retry of an approved financial/work allocation change.
        target='held' if mode=='apply' else 'need_limit'
        db.execute('UPDATE cases SET state=?,target_limit=NULL,actor=NULL,result=?,notified=0 WHERE id=?',(target,'Worker did not complete; no verified write',identity))
    db.commit()

def main():
    os.umask(0o077);ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    lock=(ROOT/'bot.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    config=json.loads(CONFIG.read_text());token=load_token()
    if not config.get('human_review_required') or config.get('automatic_limit_changes') is not False:raise ValueError('Human review required')
    chat=api(token,'getChat',{'chat_id':config['chat_id']})
    if chat.get('id')!=config['chat_id'] or chat.get('title','').casefold()!='опоздавшие':raise ValueError('Bound group changed')
    if api(token,'getMe')['id']!=config['bot_id']:raise ValueError('Bot identity changed')
    if api(token,'getWebhookInfo').get('url'):raise ValueError('Existing webhook must be integrated; not replaced')
    db=connect()
    # Ambiguous states after a process crash are never retried as writes/sends.
    db.execute("UPDATE cases SET state='uncertain',notified=0 WHERE state='applying'")
    db.execute("UPDATE cases SET state='delivery_uncertain' WHERE state='sending'")
    db.execute("UPDATE cases SET state='need_limit' WHERE state='reading'");db.commit()
    def stop(*args):raise SystemExit(0)
    signal.signal(signal.SIGTERM,stop)
    job=None;next_collect=0;next_job=0
    print('Attendance review bot started. Group verified; individual approval required.',flush=True)
    try:
        while True:
            config=json.loads(CONFIG.read_text())
            if job and (job[0].poll() is not None or time.monotonic()-job[3]>300):
                if job[0].poll() is None:job[0].terminate();job[0].wait(timeout=10)
                finish_job(db,job);job=None;next_job=time.monotonic()+30
            if time.monotonic()>=next_collect:
                try:collect(db,config)
                except (OSError,ValueError,RuntimeError,KeyError,TypeError) as error:
                    print('Evidence refresh failed:',type(error).__name__,flush=True)
                next_collect=time.monotonic()+120
            notify(db,config,token)
            if not job and time.monotonic()>=next_job:job=start_job(db)
            offset=db.execute("SELECT value FROM meta WHERE key='telegram_offset'").fetchone()
            updates=api(token,'getUpdates',{'offset':int(offset[0]) if offset else 0,'timeout':10,'limit':100})
            for update in updates:
                # Persist unrelated updates rather than silently discarding them.
                if not update.get('callback_query',{}).get('data','').startswith('att:'):
                    directory=ROOT/'other-updates';directory.mkdir(mode=0o700,exist_ok=True)
                    (directory/(str(update['update_id'])+'.json')).write_text(json.dumps(update,ensure_ascii=False))
                else:handle_callback(db,update,config,token)
                db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('telegram_offset',?)",(str(update['update_id']+1),));db.commit()
    finally:
        if job and job[0].poll() is None:job[0].terminate()
        db.close()

if __name__=='__main__':
    try:main()
    except Exception as error:
        print('Attendance bot stopped: '+type(error).__name__+'. No automatic write retries; inspect private state.',flush=True)
        raise SystemExit(78 if isinstance(error,ValueError) or 'Telegram HTTP 409' in str(error) else 1)
