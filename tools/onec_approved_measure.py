"""Read a proposed limit or execute one specifically approved Telegram case."""
import json,time
from datetime import datetime
from pathlib import Path
from attendance_cases import connect,get,proposed_target,claim_write,fingerprint
from onec_limit_test import card,save_button
from onec_courier_card import matching_row,matching_id_row,_grid,_save
from attendance_review import TZ,review_rows

def load_task(identity,mode):
    import re
    if not re.fullmatch('[0-9a-f]{24}',identity) or mode not in ('read','apply'):raise ValueError('Invalid case task')
    with connect() as db:case=get(db,identity)
    if case['state'] not in ({'reading'} if mode=='read' else {'approved'}):raise ValueError('Case not available for this operation')
    return case

def fresh_evidence(case):
    from audit_sources import audit
    from proxy_config import configured_proxy
    from attendance_cases import ROOT
    p=case['payload'];day=datetime.now(TZ).date().isoformat()
    if p['date']!=day:raise ValueError('Approval is for a different Moscow day')
    token=json.loads(Path('/root/curator-session.json').read_text())['token']
    folder=ROOT/'recheck'/case['id']
    summary=audit(day,token,configured_proxy(),folder,extra_details=False)
    if not any(s['shop_id']==p['shop_id'] and s.get('scope_verified') for s in summary['shops']):raise ValueError('Fresh source scope not verified')
    rows=review_rows(json.loads((folder/'all-shops-observations.json').read_text()),day)
    matches=[r for r in rows if r['event_id']==p['event_id']]
    if len(matches)!=1 or fingerprint(matches[0])!=fingerprint(p) or matches[0]['unresolved_facts'] or matches[0]['multiple_bookings_for_courier']:
        raise ValueError('Attendance facts changed; review again')

def execute(page,private,identity,mode,study):
    with connect() as db:
        case=load_task(identity,mode);p=case['payload']
        if not study.get('card_opened') or study.get('candidate',{}).get('courier_id')!=p['courier_id'] or study['shop_id']!=p['shop_id']:
            if mode=='read':
                reason=study.get('search_failure','card_identity_not_verified')
                if reason not in ('courier_id_not_found','courier_id_not_unique','courier_name_id_mismatch','courier_search_unstable'):reason='card_identity_not_verified'
                db.execute('UPDATE cases SET last_read_error=? WHERE id=?',(reason,identity));db.commit()
            raise ValueError('Opened card identity not verified')
        if mode=='read':db.execute('UPDATE cases SET last_read_error=NULL WHERE id=?',(identity,));db.commit()
        prefix,current,taking=card(page,p['courier_id'],p['name'])
        if mode=='read':
            try:target=proposed_target(current,p['proposed_measure'])
            except ValueError:
                db.execute("UPDATE cases SET state='held',current_limit=?,target_limit=NULL,result='Manual review required',notified=0 WHERE id=?",(current,identity));db.commit();return {'read':True,'held':True}
            db.execute("UPDATE cases SET state='ready',current_limit=?,target_limit=?,observed=?,notified=0 WHERE id=?",(current,target,time.time(),identity));db.commit()
            return {'read':True,'current_limit':current,'target_limit':target}
        config=json.loads(Path('/etc/superset-telegram/late-group.json').read_text())
        from attendance_routes import case_config
        config=case_config(config,case)
        if case['actor'] not in config['approver_ids'] or not case['observed'] or case['observed']>time.time()+120:raise ValueError('Human approval missing or stale')
        from late_bot_group import load_token,api
        member=api(load_token(),'getChatMember',{'chat_id':config['chat_id'],'user_id':case['actor']})
        if member.get('status') not in ('administrator','creator') or member.get('user',{}).get('is_bot'):raise ValueError('Reviewer authority no longer verified')
        fresh_evidence(case)
        target=proposed_target(current,p['proposed_measure'])
        if current!=case['current_limit'] or target!=case['target_limit']:
            db.execute("UPDATE cases SET state='need_limit',actor=NULL,target_limit=NULL,read_attempts=0,next_attempt=0 WHERE id=?",(identity,));db.commit()
            return {'refresh_required':True,'applied':False}
        button=save_button(page);claim_write(db,identity)
        try:
            field=page.locator('[id="'+prefix+'ОграничениеНаКоличествоЗаказов_i0"]')
            field.click();field.press('Control+A');field.press('Backspace');field.press_sequentially(str(target),delay=90);field.press('Tab');page.wait_for_timeout(300)
            _,edited,unchanged=card(page,p['courier_id'],p['name'])
            if edited!=target or unchanged!=taking:raise ValueError('Edit buffer validation failed')
            button.click(timeout=10000);field.wait_for(state='hidden',timeout=20000)
            grid=page.locator('[id="grid_form0_Список"]');grid.wait_for(state='visible',timeout=10000);page.wait_for_timeout(1000)
            data=_grid(page);row=matching_id_row(data,p['courier_id'],p['name'])
            if row['courier_id']!=p['courier_id']:raise ValueError('Readback courier ID mismatch')
            grid.locator('.gridBody > .gridLine').nth(row['row_index']).locator('.gridBox').nth(data['headings'].index('Name')).dblclick(timeout=5000)
            page.wait_for_timeout(2000)
            _,observed,unchanged=card(page,p['courier_id'],p['name'])
            if observed!=target or unchanged!=taking:raise ValueError('Persisted limit not verified')
            db.execute("UPDATE cases SET state='applied',result=?,notified=0 WHERE id=?",(json.dumps({'before':current,'after':target,'verified':True,'actor':case['actor']}),identity))
            db.execute("UPDATE ledger SET state='applied' WHERE case_id=?",(identity,));db.commit()
            return {'applied':True,'verified':True,'before':current,'after':target}
        except Exception:
            db.execute("UPDATE cases SET state='uncertain',result='Verify persisted limit manually; no retry',notified=0 WHERE id=?",(identity,));db.commit();raise
