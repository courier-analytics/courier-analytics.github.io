"""Attendance review bot: two authorized humans, one explicit decision per case."""
import fcntl,json,os,re,secrets,signal,subprocess,sys,time
from datetime import datetime
from pathlib import Path
from attendance_cases import connect,get,ingest,DB,ROOT,TERMINAL
from attendance_review import review_rows,TZ,START
from late_bot_group import load_token,api
from audit_sources import audit
from proxy_config import configured_proxy
from attendance_routes import case_config,reviewer_allowed
from attendance_shop_policy import enabled
CONFIG=Path('/etc/superset-telegram/late-group.json')

def message(case):
    p=case['payload'];minutes=p.get('late_seconds')
    late='\nОпоздание: '+str(round(minutes/60,2))+' мин.' if minutes is not None else ''
    text=f"ДС {p['shop_id']} · {p['date']}\n{p['name']} · ID {p['courier_id']}\nНачало слота: {p['planned_start']}\nСтатус источника: {p['source_status']}"+late
    if case['current_limit'] is not None:text+='\nТекущий лимит: '+str(case['current_limit'])
    if case['target_limit'] is not None:text+='\nПредлагаемый лимит: '+str(case['target_limit'])+'\nПроверьте обстоятельства перед подтверждением.'
    else:
        text+='\nФакты или допустимый лимит требуют ручной проверки. Применение недоступно.'
        if case.get('result')=='limit_read_failed':text+='\nНе удалось прочитать лимит в 1С после трёх попыток; уменьшение не выполнялось.'
        detail={'courier_id_not_found':'Указанный ID не найден в выбранном ДС после ожидания результатов.', 'courier_id_not_unique':'Карточка с указанным ID не найдена однозначно в выбранном ДС.', 'courier_name_id_mismatch':'ID найден, но ФИО в 1С отличается от источника.', 'courier_search_unstable':'Список 1С не завершил обновление.', 'card_identity_not_verified':'Не удалось подтвердить открытую карточку курьера.'}.get(case.get('last_read_error'))
        if detail:text+='\nПричина: '+detail
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
    shops={shop for shop in (8889,7745,9107) if enabled(config,shop)}
    if not shops<={s['shop_id'] for s in summary['shops'] if s.get('scope_verified')}:raise ValueError('Enabled source scopes must be verified')
    observations=json.loads((folder/'all-shops-observations.json').read_text())
    observations['shops']=[s for s in observations['shops'] if s['shop_id'] in shops]
    rows=review_rows(observations,day.isoformat())
    live=ingest(db,rows,config.get('ignored_cases',[]))
    for row in db.execute('SELECT id,state,payload FROM cases').fetchall():
        p=json.loads(row['payload'])
        if row['state'] not in TERMINAL|{'applying','delivery_uncertain','sending'} and (p['date']!=day.isoformat() or row['id'] not in live):
            db.execute("UPDATE cases SET state='withdrawn',notified=0 WHERE id=? AND state NOT IN ('applied','skipped','withdrawn','uncertain','applying','delivery_uncertain','sending')",(row['id'],))
    db.commit()

def reviewer_label(user):
    username=user.get('username','')
    if isinstance(username,str) and re.fullmatch(r'[A-Za-z0-9_]{1,32}',username):return '@'+username
    name=' '.join(str(user.get(k) or '') for k in ('first_name','last_name'))
    name=' '.join(''.join(c for c in name if c.isprintable()).split())
    return name[:150] or 'Участник группы'

def handle_callback(db,update,config,token):
    from attendance_cases import callback_decision
    q=update.get('callback_query');
    if not isinstance(q,dict):return
    data=q.get('data','')
    if not data.startswith('att:'):return
    try:
        match=re.fullmatch(r'att:([as]):([0-9a-f]{24}):([0-9a-f]{8})',data)
        if not match:raise ValueError('Invalid callback')
        action,identity,nonce=match.groups()
        case=get(db,identity)
        if not enabled(config,case['payload']['shop_id']):raise ValueError('Attendance disabled for this shop')
        config=case_config(config,case)
        actor=q['from']['id'];msg=q['message']
        if q['from'].get('is_bot'):raise ValueError('Not a human reviewer')
        member=api(token,'getChatMember',{'chat_id':config['chat_id'],'user_id':actor})
        if not reviewer_allowed(config,member,actor):raise ValueError('Group reviewer rights required')
        config={**config,'verified_member_id':actor,'actor_label':reviewer_label(q['from'])}
        outcome=callback_decision(db,identity,nonce,actor,msg['chat']['id'],msg['message_id'],'apply' if action=='a' else 'skip',config)
        answer='Подтверждение принято; проверяем данные и сохраняем в 1С.' if outcome=='approved' else 'Пропущено.' if outcome=='skipped' else 'Лимит устарел. Перечитаем и запросим подтверждение заново.'
        # Strip buttons immediately; durable database state is the authority.
        try:api(token,'editMessageReplyMarkup',{'chat_id':config['chat_id'],'message_id':msg['message_id'],'reply_markup':{'inline_keyboard':[]}})
        except RuntimeError:pass
    except (ValueError,KeyError,TypeError):answer='Кнопка устарела, уже обработана или у вас нет права подтверждения.'
    api(token,'answerCallbackQuery',{'callback_query_id':q['id'],'text':answer})

def notify(db,config,token,only_id=None):
    root_config=config
    for row in db.execute("SELECT id FROM cases WHERE state='ready' AND current_limit IS NOT NULL AND target_limit IS NOT NULL AND notified=0").fetchall():
        if only_id is not None and row['id']!=only_id:continue
        case=get(db,row['id'])
        if not enabled(root_config,case['payload']['shop_id']):continue
        config=case_config(root_config,{**case,'message_id':None,'message_chat_id':None})
        if case['state']=='ready' and (not case['observed'] or case['observed']>time.time()+120):
            db.execute("UPDATE cases SET state='need_limit' WHERE id=?",(case['id'],));db.commit();continue
        if case.get('message_id'):
            previous=case_config(root_config,case)
            try:api(token,'editMessageReplyMarkup',{'chat_id':previous['chat_id'],'message_id':case['message_id'],'reply_markup':{'inline_keyboard':[]}})
            except RuntimeError:pass  # Old nonce is already invalid; missing old messages must not block routing.
        db.execute("UPDATE cases SET state='sending',message_chat_id=? WHERE id=?",(config['chat_id'],case['id']));db.commit()
        try:
            sent=api(token,'sendMessage',{'chat_id':config['chat_id'],'text':message(case),'reply_markup':buttons(case)})
            if type(sent.get('message_id')) is not int:raise RuntimeError('Message unconfirmed')
            db.execute("UPDATE cases SET state='pending_review',message_id=?,notified=1 WHERE id=?",(sent['message_id'],case['id']));db.commit()
        except RuntimeError:
            db.execute("UPDATE cases SET state='delivery_uncertain',notified=1 WHERE id=?",(case['id'],));db.commit();raise
    for row in db.execute("SELECT id FROM cases WHERE state IN ('applied','skipped','uncertain','held') AND message_id IS NOT NULL AND notified=0").fetchall():
        if only_id is not None and row['id']!=only_id:continue
        case=get(db,row['id'])
        if not enabled(root_config,case['payload']['shop_id']):continue
        config=case_config(root_config,case);p=case['payload']
        labels={'held':'Проверка не завершена; изменение не подтверждено. Требуется разбор, повторного списания не будет.','applied':'Сохранено в 1С и проверено повторным открытием карточки.','skipped':'Пропущено ответственным.','withdrawn':'Случай отозван: факты изменились или дата закончилась.','uncertain':'Результат сохранения не подтверждён. Нужна ручная проверка; повторного уменьшения не будет.'}
        text=message(case)+'\n\n'+labels[case['state']]
        if case.get('actor'):
            label=case.get('actor_label')
            if not label:
                try:
                    member=api(token,'getChatMember',{'chat_id':config['chat_id'],'user_id':case['actor']})
                    if member.get('user',{}).get('id')==case['actor']:label=reviewer_label(member['user'])
                except RuntimeError:pass
            text+='\nРешение принял: '+(label or 'Участник группы')
        if not case['message_id']:
            db.execute('UPDATE cases SET notified=1 WHERE id=?',(case['id'],));db.commit();continue
        try:api(token,'editMessageText',{'chat_id':config['chat_id'],'message_id':case['message_id'],'text':text,'reply_markup':{'inline_keyboard':[]}})
        except RuntimeError:
            # Do not send duplicate outcome notifications on uncertain network I/O.
            pass
        db.execute('UPDATE cases SET notified=1 WHERE id=?',(case['id'],));db.commit()

def start_job(db,config=None):
    # Approved cases take priority so the reviewed current value remains fresh.
    config=json.loads(CONFIG.read_text()) if config is None else config
    rows=db.execute("SELECT id,state,payload FROM cases WHERE state IN ('approved','need_limit') AND next_attempt<=? ORDER BY CASE state WHEN 'approved' THEN 0 ELSE 1 END,next_attempt,rowid",(time.time(),)).fetchall()
    row=next((row for row in rows if enabled(config,json.loads(row['payload'])['shop_id'])),None)
    if not row:return None
    mode='apply' if row['state']=='approved' else 'read'
    if mode=='read':db.execute("UPDATE cases SET state='reading',read_attempts=read_attempts+1 WHERE id=?",(row['id'],));db.commit()
    log=(ROOT/'worker.log').open('a')
    try:
        process=subprocess.Popen(['flock','-n','-E','75','/opt/courier-analytics/onec-roster.lock',
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
    if mode=='read' and state=='reading' and process is not None and process.returncode==75:
        db.execute("UPDATE cases SET state='need_limit',read_attempts=max(0,read_attempts-1),next_attempt=? WHERE id=?",(time.time()+60,identity));db.commit()
        print('1C read deferred: shared connection busy; attempt not counted',flush=True)
        return
    if state=='applying':
        db.execute("UPDATE cases SET state='uncertain',result='Worker interrupted; verify manually',notified=0 WHERE id=?",(identity,))
    elif state in ('approved','reading'):
        # A failed pre-write verification needs another human review, not an
        # automatic retry of an approved financial/work allocation change.
        attempts=get(db,identity)['read_attempts']
        exhausted=mode=='read' and attempts>=3
        target='held' if mode=='apply' or exhausted else 'need_limit'
        delay=(120 if attempts<=1 else 600) if mode=='read' and not exhausted else 0
        reason='limit_read_failed' if exhausted else 'Worker did not complete; no verified write'
        db.execute('UPDATE cases SET state=?,target_limit=NULL,actor=NULL,result=?,next_attempt=?,notified=0 WHERE id=?',(target,reason,time.time()+delay,identity))
        print('1C worker did not complete:',mode,'read attempt:',attempts,'next state:',target,flush=True)
    db.commit()

def start_source_refresh():
    with (ROOT/'source-refresh.log').open('a') as log:
        process=subprocess.Popen([sys.executable,'-u',str(Path(__file__).with_name('attendance_source_refresh.py'))],
                                 stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    print('Evidence refresh started in background; Telegram receiver remains available.',flush=True)
    return process,time.monotonic()

def stop_source_refresh(source_job):
    if source_job and source_job[0].poll() is None:
        try:os.killpg(source_job[0].pid,signal.SIGTERM)
        except ProcessLookupError:pass
        source_job[0].wait(timeout=10)

STARTUP_MESSAGES={'Human review required','Bound group identity changed','Bot identity changed',
                  'Existing webhook must be integrated; not replaced','Matryoshka configuration not private','Unexpected Matryoshka group'}

def verify_startup(config,token):
    if not config.get('human_review_required') or config.get('automatic_limit_changes') is not False:
        raise ValueError('Human review required')
    chat=api(token,'getChat',{'chat_id':config['chat_id']})
    # Group titles are editable display labels; authorization is bound to ID.
    if chat.get('id')!=config['chat_id']:raise ValueError('Bound group identity changed')
    me=api(token,'getMe')
    if me.get('id')!=config['bot_id']:raise ValueError('Bot identity changed')
    if api(token,'getWebhookInfo').get('url'):
        raise ValueError('Existing webhook must be integrated; not replaced')
    return me

def main():
    os.umask(0o077);ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    lock=(ROOT/'bot.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    config=json.loads(CONFIG.read_text());token=load_token()
    me=verify_startup(config,token)
    from matryoshka_command_handler import Handler
    matryoshka=Handler(token,me['username'])
    db=connect()
    # Ambiguous states after a process crash are never retried as writes/sends.
    db.execute("UPDATE cases SET state='uncertain',notified=0 WHERE state='applying'")
    db.execute("UPDATE cases SET state='delivery_uncertain' WHERE state='sending'")
    db.execute("UPDATE cases SET state='need_limit' WHERE state='reading'");db.commit()
    def stop(*args):raise SystemExit(0)
    signal.signal(signal.SIGTERM,stop)
    job=None;source_job=None;next_collect=0;next_job=0
    print('Attendance review bot started. Group verified; individual approval required.',flush=True)
    try:
        while True:
            config=json.loads(CONFIG.read_text())
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('last_loop',?)",(datetime.now(TZ).isoformat(),));db.commit()
            if job and (job[0].poll() is not None or time.monotonic()-job[3]>300):
                if job[0].poll() is None:job[0].terminate();job[0].wait(timeout=10)
                finish_job(db,job);job=None;next_job=time.monotonic()+30
            if source_job:
                status=source_job[0].poll()
                if status is not None:
                    print('Background evidence refresh finished; exit:',status,flush=True)
                    source_job=None;next_collect=time.monotonic()+(60 if status==75 else 120)
                elif time.monotonic()-source_job[1]>600:
                    stop_source_refresh(source_job);source_job=None;next_collect=time.monotonic()+120
                    db.execute("INSERT OR REPLACE INTO meta VALUES('last_source_error','source_refresh_timeout')");db.commit()
                    print('Background evidence refresh timed out; Telegram receiver continues.',flush=True)
            if source_job is None and time.monotonic()>=next_collect:
                try:source_job=start_source_refresh()
                except OSError:
                    next_collect=time.monotonic()+120
                    print('Could not start evidence refresh; Telegram receiver continues.',flush=True)
            notify(db,config,token)
            if not job and time.monotonic()>=next_job:job=start_job(db,config)
            offset=db.execute("SELECT value FROM meta WHERE key='telegram_offset'").fetchone()
            updates=api(token,'getUpdates',{'offset':int(offset[0]) if offset else 0,'timeout':10,'limit':100})
            for update in updates:
                # Persist unrelated updates rather than silently discarding them.
                if update.get('callback_query',{}).get('data','').startswith('att:'):
                    handle_callback(db,update,config,token)
                elif not matryoshka.handle(update):
                    directory=ROOT/'other-updates';directory.mkdir(mode=0o700,exist_ok=True)
                    (directory/(str(update['update_id'])+'.json')).write_text(json.dumps(update,ensure_ascii=False))
                db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('telegram_offset',?)",(str(update['update_id']+1),));db.commit()
    finally:
        stop_source_refresh(source_job)
        if job and job[0].poll() is None:job[0].terminate()
        db.close()

if __name__=='__main__':
    try:main()
    except Exception as error:
        safe=str(error) if str(error) in STARTUP_MESSAGES or re.fullmatch(r'Telegram HTTP \d{3}|Unsupported setup method',str(error)) else type(error).__name__
        print('Attendance bot stopped: '+safe+'. No automatic write retries; inspect private state.',flush=True)
        raise SystemExit(78 if isinstance(error,ValueError) or 'Telegram HTTP 409' in str(error) else 1)
