"""Read-only native Id/Name/Phone exports. No private values in journals."""
import sys,os,json,re,inspect,subprocess
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,'/opt/courier-contacts/connected')
import collect_connected as c
# Reuse the installed verified column-checkbox selector and native all-row export.
source=c.namespace['source']
old="columns=['Id','Name','Т.З.']"
if source.count(old)!=1:raise SystemExit('Phone export selector changed; stopped')
source=source.replace(old,"columns=['Id','Name','Phone']")
exec(compile(source,'verified_phone_columns','exec'),c.roster.__dict__)
DONE=False

def parse(export):
    if not export.get('confirmed') or export.get('columns')!=['Id','Name','Phone'] or export.get('only_selected') is not False:raise ValueError('Phone columns not verified')
    candidates=[]
    for doc in export.get('documents',{}).get('text_fields',[]):
        lines=doc.get('text','').lstrip('\ufeff').splitlines()
        lines=[line for line in lines if line.strip()]
        if not lines or not re.fullmatch(r'Id\s+Name\s+Phone',lines[0].strip()):continue
        rows={}
        for line in lines[1:]:
            match=re.fullmatch(r'\s*([0-9]{6,12})[ \t]+(.+?)[ \t]+([+0-9][0-9 ()+\-]{6,})\s*',line)
            if match:
                ident,name,phone=match.groups();phone=phone.strip()
                if not 10<=len(re.sub(r'\D','',phone))<=15:raise ValueError('Phone format not confirmed')
            else:
                match=re.fullmatch(r'\s*([0-9]{6,12})[ \t]+(.+?)\s*',line)
                if not match:raise ValueError('Native contact row malformed')
                ident,name=match.groups();phone=''
            if ident in rows:raise ValueError('Duplicate native contact ID')
            rows[ident]={'id':ident,'name':name.strip(),'phone':phone}
        candidates.append(rows)
    if len(candidates)!=1 or not candidates[0]:raise ValueError('Native contact document ambiguous or empty')
    return candidates[0]

def capture(page,private,inspect_roster=False,status=None):
    global DONE
    merged={}
    for shop in (8889,9107,7745):
        page=c.fresh_list(page,shop)
        c.flag(page,4,False) # Contacts include every employment/access/type in this shop.
        page.wait_for_timeout(2500)
        if not c.roster.inspect_export_dialog(page).get('opened'):raise ValueError('Phone export dialog absent')
        rows=parse(c.roster.export_id_list(page,True))
        for ident,row in rows.items():
            previous=merged.get(ident)
            if previous and previous['phone'] and row['phone'] and previous['phone']!=row['phone']:raise ValueError('Phone conflict across verified exports')
            if not previous or row['phone']:merged[ident]=row
        print('CONTACT EXPORT VERIFIED:',shop,'records:',len(rows),'with phone:',sum(bool(r['phone']) for r in rows.values()),flush=True)
        page.keyboard.press('Control+F4')
        page.locator('[id="grid_form0_Список"]').wait_for(state='visible',timeout=15000)
    # Save the verified pilot shops independently from the expensive global directory.
    # Global export is opt-in; historical outside-shop contacts retain their timestamps.
    global_complete=False
    if os.environ.get('COURIER_CONTACTS_GLOBAL_EXPORT')=='1':
        # A courier with a future booking can already be assigned to another shop.
        # Read the full contact directory once, without shop/access/type restrictions.
        field=c.filters._control(page,'form0_НомерТочки_i0')
        field.click();field.press('Control+A');field.press('Backspace');field.press('Tab')
        page.wait_for_timeout(6000)
        if field.input_value().strip():raise ValueError('Global contact shop filter not cleared')
        for n in (4,5,6,7,8):c.flag(page,n,False)
        if not c.roster.inspect_export_dialog(page).get('opened'):raise ValueError('Global contact export dialog absent')
        all_rows=parse(c.roster.export_id_list(page,True))
        for ident,row in all_rows.items():
            if row['phone']:merged[ident]=row
        print('GLOBAL CONTACT EXPORT VERIFIED: records:',len(all_rows),'with phone:',sum(bool(r['phone']) for r in all_rows.values()),flush=True)
        global_complete=True
    target=Path('/opt/courier-contacts/phones-current.json')
    observed=datetime.now(timezone.utc).isoformat()
    for row in merged.values():row['observed_at']=observed
    if target.exists():
        previous=json.loads(target.read_text())
        if previous.get('verified') is True:
            for row in previous.get('couriers',[]):
                if row.get('id') not in merged:
                    row=dict(row);row.setdefault('observed_at',previous.get('observed_at'))
                    merged[row['id']]=row
    c.private_write(target,json.dumps({'observed_at':observed,'verified':True,
        'verified_shops':[8889,9107,7745],'global_directory_refreshed':global_complete,
        'couriers':list(merged.values())},ensure_ascii=False))
    DONE=True
    print('FRESH CONTACTS SAVED:',len(merged),'with phone:',sum(bool(r['phone']) for r in merged.values()),flush=True)
    return {'native_roster':{'verified':False,'reason':'separate_verified_phone_export_saved'},'roster_filters':{'filters_verified':True}}

if __name__=='__main__':
    os.umask(0o077);c.browser.capture_interface=capture
    source=inspect.getsource(c.probe)
    if source.count("'240s'")!=1:raise SystemExit('VPN implementation changed; stopped')
    scope={'__name__':'phone_refresh_vpn','__file__':c.probe.__file__}
    exec(compile(source.replace("'240s'","'1200s'"),'phone_refresh_vpn','exec'),scope)
    sys.argv=['probe_powerbi_vpn.py','--address','10.210.254.19','--onec-login','--onec-inspect-roster']
    scope['main']()
    if not DONE:raise SystemExit(1)
