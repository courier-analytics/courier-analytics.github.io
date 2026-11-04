"""Restore only the user-confirmed 1C list-filter values through native UI controls."""
import re

PREFIX='form0_КомпоновщикНастроекПользовательскиеНастройкиЭлемент'
TYPES={6:'6 - Мобильный Авто Курьер',9:'9 - Мобильный Вело Курьер'}


def _control(page,identity):
    return page.locator('[id="'+identity+'"]')


def _choose(page,labels,timeout=5000):
    pattern=re.compile(r'^(?:'+ '|'.join(re.escape(label) for label in labels)+r')$')
    options=page.get_by_text(pattern).and_(page.locator(':visible'))
    options.first.wait_for(state='visible',timeout=timeout)
    leaves=[]
    for i in range(options.count()):
        option=options.nth(i)
        if option.evaluate('(e)=> !Array.from(e.children).some(c=>c.innerText?.trim()===e.innerText.trim())'):
            leaves.append(option)
    if len(leaves)!=1:raise ValueError('1C filter option ambiguous')
    leaves[0].click(timeout=5000)


def _choice(page,base,accepted):
    field=_control(page,base+'_i0')
    if field.input_value().strip() in accepted:return
    _control(page,base+'_DLB').click(timeout=5000)
    _choose(page,tuple(value for value in accepted if value))
    field.press('Tab')
    page.wait_for_function('([id,values])=>values.includes(document.getElementById(id)?.value?.trim())',
                           arg=[base+'_i0',list(accepted)],timeout=5000)


def type_codes(page):
    # The type picker renders collapsed overflow chips in a portal. The other
    # confirmed filters are scalar values; inspect only labelled numeric chips.
    titles=page.locator('.chipsItem[title]').evaluate_all('(es)=>es.map(e=>e.title)')
    return {int(match.group(1)) for title in titles if (match:=re.match(r'^\s*([0-9]+)\s*-',title))}


def _type_shape(page):
    return page.evaluate("""(base)=>{
        const chips=Array.from(document.querySelectorAll('[id]')).filter(e=>
            e.id.startsWith(base+'_multipleValues_') && e.classList.contains('chipsItem') && Number.isInteger(parseInt(e.title,10)));
        const extra=Number(document.getElementById(base+'_multipleValues_more')?.textContent?.trim().replace('+','')||0);
        return {codes:chips.map(e=>parseInt(e.title,10)),count:chips.length+extra};
    }""",PREFIX+'5Значение')


def _expand_types(page):
    more=_control(page,PREFIX+'5Значение_multipleValues_more')
    if more.is_visible():
        more.click(timeout=5000)
        page.wait_for_timeout(500)
        page.keyboard.press('Escape')


def type_selection_valid(page):
    shape=_type_shape(page)
    if shape['count']==2 and type_codes(page)!=set(TYPES):
        _expand_types(page)
    return (shape['count']==2 and bool(shape['codes']) and set(shape['codes'])<=set(TYPES)
            and type_codes(page)==set(TYPES))


def restore_values(page,progress=None):
    def mark(value):
        if progress:progress(value)
    mark('list_search')
    search='form0_ФормаКоманднаяПанельСписокСтрокаПоиска'
    field=_control(page,search+'_i0')
    if field.count()==1 and field.input_value().strip():
        _control(page,search+'_CLR').click(timeout=5000)
        page.wait_for_function('(id)=>!(document.getElementById(id)?.value||"").trim()',arg=search+'_i0',timeout=5000)
    mark('service_value')
    _choice(page,'form0_Служба',('','Без отбора','No filter','Without filter'))
    mark('access_value')
    _choice(page,PREFIX+'4Значение',('Да','Yes'))
    mark('employment_comparison')
    _choice(page,PREFIX+'7ВидСравненияЭлементаОтбора',('Не равно','Not equal'))
    mark('employment_value')
    field=_control(page,PREFIX+'7Значение_i0')
    if field.input_value().strip()!='1':
        field.click(timeout=5000);field.press('Control+A');field.press('Backspace')
        field.press_sequentially('1');field.press('Enter');field.press('Tab')
        page.wait_for_function('(id)=>document.getElementById(id)?.value?.trim()==="1"',
                               arg=PREFIX+'7Значение_i0',timeout=5000)
    mark('type_comparison')
    _choice(page,PREFIX+'5ВидСравненияЭлементаОтбора',('Не в списке','Not in list'))
    if type_selection_valid(page):return
    mark('types_clear')
    base=PREFIX+'5Значение'
    _control(page,base+'_CLR').click(timeout=5000)
    page.wait_for_function("""(base)=>!Array.from(document.querySelectorAll('[id]')).some(e=>
        e.id.startsWith(base+'_multipleValues_') && e.classList.contains('chipsItem') && Number.isInteger(parseInt(e.title,10)))
        && !Number(document.getElementById(base+'_multipleValues_more')?.textContent?.trim().replace('+','')||0)""",arg=base,timeout=5000)
    if _type_shape(page)['count']:raise ValueError('1C courier type list was not cleared')
    for number,(code,label) in enumerate(TYPES.items(),start=1):
        mark('type_'+str(code)+'_select')
        field=_control(page,base+'_i0')
        field.click(timeout=5000)
        field.press_sequentially(label,delay=40)
        # A native reference-field autocomplete must supply the selected value;
        # assigning .value or guessing modal row IDs cannot commit a 1C filter.
        from playwright.sync_api import TimeoutError as BrowserTimeout
        try:
            _choose(page,(label,),timeout=3000)
        except BrowserTimeout:
            # Some native reference fields show choices only on the evidenced
            # dropdown button, rather than opening autocomplete while typing.
            _control(page,base+'_DLB').click(timeout=5000)
            _choose(page,(label,))
        field.press('Tab')
        page.wait_for_function("""([base,count])=>{
            const chips=Array.from(document.querySelectorAll('[id]')).filter(e=>e.id.startsWith(base+'_multipleValues_') && e.classList.contains('chipsItem') && Number.isInteger(parseInt(e.title,10)));
            const extra=Number(document.getElementById(base+'_multipleValues_more')?.textContent?.trim().replace('+','')||0);
            return chips.length+extra===count;
        }""",arg=[base,number],timeout=5000)
        if code not in type_codes(page):_expand_types(page)
        page.wait_for_function("""(code)=>Array.from(document.querySelectorAll('.chipsItem[title]'))
            .some(e=>parseInt(e.title,10)===code)""",arg=code,timeout=5000)
    mark('types_verified')
    if not type_selection_valid(page):raise ValueError('1C courier type selection not verified')
