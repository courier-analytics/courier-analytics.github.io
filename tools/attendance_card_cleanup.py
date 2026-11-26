"""Retire only durably withdrawn bot cards; preserve decisions and uncertain writes."""
import time
from attendance_cases import get
from attendance_routes import case_config


def cleanup_withdrawn(db,config,token,api,only_id=None,now=None):
    now=time.time() if now is None else now
    rows=db.execute("SELECT id FROM cases WHERE state='withdrawn' AND message_id IS NOT NULL AND coalesce(cleanup_state,'') NOT IN ('deleted','closed') AND cleanup_attempts<5 AND cleanup_after<=? ORDER BY rowid LIMIT 3",(now,)).fetchall()
    for row in rows:
        if only_id is not None and row['id']!=only_id:continue
        case=get(db,row['id'])
        if case['state']!='withdrawn':continue
        route=case_config(config,case)
        payload={'chat_id':route['chat_id'],'message_id':case['message_id']}
        state=None
        try:
            if api(token,'deleteMessage',payload) is True:state='deleted'
        except RuntimeError:
            pass
        if state is None:
            # Telegram may forbid deletion of old messages. Disable the card instead.
            try:
                api(token,'editMessageText',{**payload,'text':'Карточка больше не актуальна: случай отозван после обновления данных или завершения даты. Действия недоступны.', 'reply_markup':{'inline_keyboard':[]}})
                state='closed'
            except RuntimeError:
                try:api(token,'editMessageReplyMarkup',{**payload,'reply_markup':{'inline_keyboard':[]}})
                except RuntimeError:pass
        db.execute("UPDATE cases SET cleanup_state=?,cleanup_attempts=cleanup_attempts+1,cleanup_after=?,notified=CASE WHEN ? IS NOT NULL THEN 1 ELSE notified END WHERE id=? AND state='withdrawn'",(state,now+600,state,case['id']))
        db.commit()
        print('Withdrawn card cleanup:',state or 'deferred',flush=True)
