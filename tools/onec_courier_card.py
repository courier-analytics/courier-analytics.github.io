"""Read-only named courier card inspection. Never fills a card or saves it."""
import json,os,re,tempfile,zipfile
from pathlib import Path
from datetime import datetime
from prepare_openvpn import private_write


def normalized(value):return ' '.join(str(value).split()).casefold()

def matching_row(data,name):
    heads=data.get('headings',[])
    if heads.count('Id')!=1 or heads.count('Name')!=1:raise ValueError('Courier list columns changed')
    a,b=heads.index('Id'),heads.index('Name');matches=[]
    for index,values in enumerate(data.get('rows',[])):
        if len(values)!=len(heads):raise ValueError('Incomplete courier row')
        if normalized(values[b])!=normalized(name):continue
        identity=values[a].strip()
        if not identity.isdigit():raise ValueError('Courier ID missing')
        matches.append({'courier_id':identity,'name':values[b].strip(),'row_index':index})
    if len(matches)!=1:raise ValueError('Expected one exact visible name match')
    return matches[0]


def matching_id_row(data,identity,name):
    heads=data.get('headings',[])
    if heads.count('Id')!=1 or heads.count('Name')!=1:raise ValueError('Courier list columns changed')
    a,b=heads.index('Id'),heads.index('Name')
    rows=[(i,r) for i,r in enumerate(data.get('rows',[])) if len(r)==len(heads) and r[a].strip()==identity]
    if not rows:raise ValueError('courier_id_not_found')
    if len(rows)!=1:raise ValueError('courier_id_not_unique')
    index,row=rows[0]
    if normalized(row[b])!=normalized(name):raise ValueError('courier_name_id_mismatch')
    return {'courier_id':identity,'name':row[b].strip(),'row_index':index}


SEARCH_IDS=('form0_ПолеПоиска_i0','form0_ФормаКоманднаяПанельСписокСтрокаПоиска_i0')


def search_field_id(fields):
    found=[f['id'] for f in fields if f.get('id') in SEARCH_IDS and not f.get('disabled') and not f.get('readOnly')]
    if len(found)!=1:raise ValueError('Courier list search missing or ambiguous')
    return found[0]


def _search_field(page):
    # Both IDs are evidenced in supplied 1C interface archives. Never use
    # the global caption bar search or arbitrary text controls as a fallback.
    page.wait_for_function('(ids)=>ids.some(id=>{const e=document.getElementById(id);return e&&!e.disabled&&!e.readOnly&&e.getBoundingClientRect().width>0&&e.getBoundingClientRect().height>0})',arg=list(SEARCH_IDS),timeout=10000)
    fields=page.evaluate('''ids=>ids.flatMap(id=>{const e=document.getElementById(id);return e&&e.getBoundingClientRect().width>0&&e.getBoundingClientRect().height>0?[{id,disabled:e.disabled,readOnly:e.readOnly}]:[]})''',list(SEARCH_IDS))
    identity=search_field_id(fields)
    return page.locator('[id="'+identity+'"]'),identity


def _grid(page):
    return page.evaluate('''() => {
        const root=document.getElementById('grid_form0_Список');
        if(!root) return {};
        return {headings:Array.from(root.querySelectorAll('.gridHead .gridLine > .gridBox')).map(e=>e.innerText.trim()),
            rows:Array.from(root.querySelectorAll('.gridBody > .gridLine')).map(r=>Array.from(r.children).filter(e=>e.classList.contains('gridBox')).map(e=>e.innerText.trim()))};
    }''')


def wait_for_courier_result(page,name,identity=None,attempts=40):
    previous=None;last_error='courier_search_unstable'
    for attempt in range(attempts):
        data=_grid(page)
        try:
            candidate=matching_id_row(data,identity,name) if identity else matching_row(data,name)
        except ValueError as error:
            last_error=str(error);previous=None
        else:
            if data==previous:return data,candidate
            previous=data
        page.wait_for_timeout(500)
    raise ValueError(last_error)


def _save(page,folder,status):
    # Private UI evidence only: no network bodies, cookies or storage dump.
    data=page.evaluate('''() => {
        const visible=e=>!!(e.getBoundingClientRect().width&&e.getBoundingClientRect().height);
        const root=document.getElementById('mainSurface');if(!root)return {};
        return {fields:Array.from(root.querySelectorAll('input,textarea,select')).filter(e=>visible(e)&&e.type!=='password').map(e=>({id:e.id,type:e.type,label:e.getAttribute('aria-label'),title:e.title,value:e.value,disabled:e.disabled,readOnly:e.readOnly})),
            labels:Array.from(root.querySelectorAll('*')).filter(e=>visible(e)&&!e.children.length&&!['INPUT','TEXTAREA','SCRIPT','STYLE'].includes(e.tagName)&&(e.innerText||'').trim()).slice(0,1000).map(e=>({id:e.id,text:e.innerText.trim().slice(0,300)}))};
    }''')
    folder=Path(folder);folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    private_write(folder/'onec-courier-study-status.json',json.dumps(status,ensure_ascii=False,indent=2))
    with tempfile.TemporaryDirectory(prefix='.courier-card-',dir=folder) as tmp:
        tmp=Path(tmp);picture=tmp/'interface.png';image=False
        try:page.screenshot(path=str(picture),timeout=5000);image=True
        except Exception:pass
        fd,name=tempfile.mkstemp(prefix='.courier-card-',dir=folder)
        try:
            with os.fdopen(fd,'wb') as stream:
                with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
                    z.writestr('status.json',json.dumps(status,ensure_ascii=False))
                    z.writestr('ui-structure.json',json.dumps(data,ensure_ascii=False))
                    if image:z.write(picture,'interface.png')
            os.replace(name,folder/'onec-courier-study.zip')
        finally:
            if os.path.exists(name):os.unlink(name)


def wait_for_card_identity(page,name,identity=None):
    page.wait_for_function(r"""args=>Array.from(document.querySelectorAll('#mainSurface input')).some(e=>{
            if(!/^form[1-9][0-9]*_Наименование_i0$/.test(e.id)||!e.getClientRects().length)return false;
            const norm=s=>s.trim().replace(/\s+/g,' ').toLowerCase();
            if(norm(e.value)!==norm(args.name))return false;
            if(!args.identity)return true;
            const id=document.getElementById(e.id.split('_')[0]+'_Идентификатор_i0');
            return id&&id.value.trim()===args.identity;
        })""",arg={'name':name,'identity':identity},timeout=20000)


def inspect(page,private,shop,name,expected_id=None):
    if shop not in (8889,7745,9107) or not isinstance(name,str) or len(name)>150 or len(name.split())<2 or any(ord(c)<32 for c in name):
        raise ValueError('Invalid read-only courier study target')
    from onec_browser import open_roster_navigation
    from onec_filters import _choice
    status={'shop_id':shop,'requested_name':name,'read_only':True,'record_edited':False,
            'card_opened':False,'limit_verified':False,'stage':'navigation'}
    try:
        stopped=open_roster_navigation(page)
        if stopped:raise ValueError('Courier navigation not available')
        grid=page.locator('[id="grid_form0_Список"]')
        grid.wait_for(state='visible',timeout=20000)
        status['stage']='list_filters'
        # Disable only known list filters; this never changes a courier setting.
        prefix='form0_КомпоновщикНастроекПользовательскиеНастройкиЭлемент'
        for number in (4,5,6,7,8):
            control=page.locator('[id="'+prefix+str(number)+'Использование"]')
            if control.count()==1 and control.is_visible() and control.evaluate('(e)=>e.classList.contains("select")'):
                control.click(timeout=5000)
                page.wait_for_timeout(300)
        _choice(page,'form0_Служба',('','Без отбора','No filter','Without filter'))
        point=page.locator('[id="form0_НомерТочки_i0"]')
        point.wait_for(state='visible',timeout=10000)
        point.click();point.press('Control+A');point.press('Backspace');point.press_sequentially(str(shop),delay=80)
        point.press('Enter');point.press('Tab');page.wait_for_timeout(3000)
        if point.input_value().strip()!=str(shop):raise ValueError('Courier shop filter not retained')
        status['stage']='exact_name_search'
        search,identity=_search_field(page)
        status['search_control']=identity
        status['stage']='enter_exact_name'
        search.click();search.press('Control+A');search.press('Backspace');search.press_sequentially(name,delay=40);search.press('Enter')
        page.wait_for_timeout(2500)
        if search.input_value().strip()!=name or point.input_value().strip()!=str(shop):raise ValueError('Search scope not retained')
        status['stage']='verify_search_results'
        try:
            second,candidate=wait_for_courier_result(page,name,expected_id)
        except ValueError:
            if not expected_id:raise
            status['stage']='verify_id_search'
            search.click();search.press('Control+A');search.press('Backspace');search.press_sequentially(expected_id,delay=80);search.press('Enter')
            if search.input_value().strip()!=expected_id or point.input_value().strip()!=str(shop):raise ValueError('Courier ID search scope changed')
            try:second,candidate=wait_for_courier_result(page,name,expected_id)
            except ValueError as error:
                status['search_failure']=str(error)
                raise
        status['candidate']=candidate
        status['visible_results']=len(second['rows'])
        status['list_completeness_verified']=False
        # Read-only opening of a candidate is allowed; it is not authorization
        # to change this record. Exact card ID remains a separate verification.
        status['stage']='open_candidate'
        second,candidate=wait_for_courier_result(page,name,expected_id)
        rows=grid.locator('.gridBody > .gridLine')
        rows.nth(candidate['row_index']).locator('.gridBox').nth(second['headings'].index('Name')).dblclick(timeout=5000)
        wait_for_card_identity(page,name,expected_id)
        # Do not infer success from the banner: require a new form with a real
        # name field containing the candidate, rather than the global user name.
        name_fields=page.locator('#mainSurface input:not([type="password"])').evaluate_all('''es=>es.filter(e=>e.id.startsWith('form')&&!e.id.startsWith('form0_')&&e.value).map(e=>({id:e.id,value:e.value}))''')
        status['card_name_fields']=[x['id'] for x in name_fields if normalized(x['value'])==normalized(name)]
        status['card_opened']=bool(status['card_name_fields'])
        status['stage']='card_snapshot' if status['card_opened'] else 'candidate_opening_unconfirmed'
        # A control named like a list filter is never accepted as a card limit.
        status['limit_verified']=False
    except Exception as error:
        status['error_category']=type(error).__name__
        status['stage_failed']=status['stage']
    finally:
        _save(page,private,status)
    print('1C courier study: '+json.dumps({k:status[k] for k in ('shop_id','stage','card_opened','limit_verified','record_edited')},ensure_ascii=False),flush=True)
    print('Private evidence saved: onec-courier-study.zip',flush=True)
    return status
