"""One explicitly authorized test: courier 1799892335, limit 7394 -> 7393.
No scheduler, generic decrement, or automatic retry after a write attempt.
"""
import json,os,re
from pathlib import Path
from datetime import datetime,timezone
from onec_courier_card import normalized,matching_row,_grid,_save
from prepare_openvpn import private_write
ID='1799892335'
NAME='Жуков Максим Сергеевич'
BEFORE=7394
AFTER=7393


def integer(value):
    text=str(value).strip().replace('\u00a0','').replace(' ','')
    if not re.fullmatch(r'\d+',text):raise ValueError('Noninteger order limit')
    return int(text)


def card(page):
    fields=page.locator('#mainSurface input:visible').evaluate_all('es=>es.map(e=>({id:e.id,value:e.value,disabled:e.disabled,readOnly:e.readOnly}))')
    names=[f for f in fields if re.fullmatch(r'form\d+_Наименование_i0',f['id']) and normalized(f['value'])==normalized(NAME)]
    if len(names)!=1:raise ValueError('Target card name not uniquely verified')
    prefix=names[0]['id'].split('_')[0]+'_'
    by_id={f['id']:f for f in fields}
    identity=by_id.get(prefix+'Идентификатор_i0',{}).get('value','').strip()
    if identity!=ID:raise ValueError('Target card ID mismatch')
    limit=by_id.get(prefix+'ОграничениеНаКоличествоЗаказов_i0')
    taking=by_id.get(prefix+'ВремяНаЗаказы_i0')
    if not limit or not taking or limit['disabled'] or limit['readOnly']:raise ValueError('Target limit field unavailable')
    return prefix,integer(limit['value']),taking['value']


def decision(current,journal_exists):
    if current==AFTER:return 'verify_only'
    if current!=BEFORE:raise ValueError('Unexpected current limit; no decrement')
    if journal_exists:raise ValueError('Previous attempt requires review; no automatic retry')
    return 'write_once'


def save_button(page):
    controls=page.get_by_text(re.compile(r'^Записать\s+и\s+закрыть$')).and_(page.locator(':visible'))
    leaves=[]
    for i in range(controls.count()):
        control=controls.nth(i)
        if control.evaluate('(e)=>!Array.from(e.children).some(c=>c.innerText?.trim()===e.innerText.trim())'):leaves.append(control)
    if len(leaves)!=1:raise ValueError('Save and close button ambiguous')
    return leaves[0]


def execute(page,private,study):
    if not study.get('card_opened') or study.get('shop_id')!=9107 or study.get('candidate',{}).get('courier_id')!=ID:
        raise ValueError('Study did not verify authorized courier candidate')
    private=Path(private)
    journal=private/'onec-limit-test-1799892335-7394-to-7393.json'
    prefix,current,taking=card(page)
    action=decision(current,journal.exists())
    result={'courier_id':ID,'before':current,'target':AFTER,'verified':False,'save_clicked':False,'read_only':False}
    if action=='verify_only':
        result.update(verified=True,observed_limit=AFTER,already_at_target=True)
        # Do not overwrite evidence of a prior attempt merely on a no-op check.
        print('1C limit test: '+json.dumps(result),flush=True)
        return result
    button=save_button(page)  # Check availability before claiming or editing.
    result['at']=datetime.now(timezone.utc).isoformat()
    # Durable exclusive claim before the UI edit; a lost connection cannot cause
    # a second subtraction. Fixed expected/target values also gate the write.
    fd=os.open(journal,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(result,stream);stream.flush();os.fsync(stream.fileno())
    try:
        field=page.locator('[id="'+prefix+'ОграничениеНаКоличествоЗаказов_i0"]')
        field.click();field.press('Control+A');field.press('Backspace');field.press_sequentially(str(AFTER),delay=100);field.press('Tab')
        page.wait_for_timeout(400)
        _,edited,taking_after=card(page)
        if edited!=AFTER or taking_after!=taking:raise ValueError('Edit buffer or unrelated taking-time field changed')
        result['save_attempted']=True
        private_write(journal,json.dumps(result,ensure_ascii=False,indent=2))
        button.click(timeout=10000)
        result['save_clicked']=True
        private_write(journal,json.dumps(result,ensure_ascii=False,indent=2))
        field.wait_for(state='hidden',timeout=20000)
        grid=page.locator('[id="grid_form0_Список"]')
        grid.wait_for(state='visible',timeout=10000)
        page.wait_for_timeout(1000)
        data=_grid(page);candidate=matching_row(data,NAME)
        if candidate['courier_id']!=ID:raise ValueError('Readback list identity mismatch')
        grid.locator('.gridBody > .gridLine').nth(candidate['row_index']).locator('.gridBox').nth(data['headings'].index('Name')).dblclick(timeout=5000)
        page.wait_for_timeout(2000)
        _,observed,taking_final=card(page)
        if observed!=AFTER or taking_final!=taking:raise ValueError('Persisted value or unrelated field readback mismatch')
        result.update(verified=True,observed_limit=observed,verification='card_reopened_after_save_and_close')
        private_write(journal,json.dumps(result,ensure_ascii=False,indent=2))
        _save(page,private,{'shop_id':9107,'requested_name':NAME,'limit_test':result,'stage':'limit_readback'})
        print('1C limit test: '+json.dumps(result,ensure_ascii=False),flush=True)
        return result
    except Exception as error:
        result.update(error_category=type(error).__name__,requires_review=True)
        private_write(journal,json.dumps(result,ensure_ascii=False,indent=2))
        _save(page,private,{'shop_id':9107,'requested_name':NAME,'limit_test':result,'stage':'limit_test_requires_review'})
        print('1C limit test: verification incomplete; no automatic retry. Inspect private test journal.',flush=True)
        raise
