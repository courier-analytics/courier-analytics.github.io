"""Restore only the user-confirmed 1C list-filter values through native UI controls."""
import re

PREFIX='form0_КомпоновщикНастроекПользовательскиеНастройкиЭлемент'
TYPES={6:'6 - Мобильный Авто Курьер',9:'9 - Мобильный Вело Курьер'}


def _control(page,identity):
    return page.locator('[id="'+identity+'"]')


def _option(page,labels,timeout=5000):
    pattern=re.compile(r'^(?:'+ '|'.join(re.escape(label) for label in labels)+r')$')
    options=page.get_by_text(pattern).and_(page.locator(':visible'))
    options.first.wait_for(state='visible',timeout=timeout)
    leaves=[]
    for i in range(options.count()):
        option=options.nth(i)
        if option.evaluate('(e)=> !Array.from(e.children).some(c=>c.innerText?.trim()===e.innerText.trim())'):
            leaves.append(option)
    if len(leaves)!=1:raise ValueError('1C filter option ambiguous')
    return leaves[0]


def _choose(page,labels,timeout=5000):
    _option(page,labels,timeout).click(timeout=5000)


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


def restore_type_comparison_in_settings(page,progress=None):
    """Use the user's confirmed Configure list / Filter route for a scalar quick filter."""
    def mark(stage):
        if progress:progress(stage)
    mark('settings_open')
    _control(page,'form0_allActionsФормаКоманднаяПанель').click(timeout=5000)
    _choose(page,('Настроить список','Настроить список...','Настроить список…',
                  'Configure list','Configure list...','Configure list…'))
    # Derive the actual new form ID from the UI, never assume form1 or a data-row ID.
    page.wait_for_function(r'''()=>Array.from(document.querySelectorAll('[id]')).some(e=>
        /^form[1-9][0-9]*_container$/.test(e.id) && e.getClientRects().length && getComputedStyle(e).visibility!=='hidden')''',timeout=10000)
    ids=page.evaluate(r'''()=>Array.from(document.querySelectorAll('[id]')).filter(e=>
        /^form[1-9][0-9]*_container$/.test(e.id) && e.getClientRects().length && getComputedStyle(e).visibility!=='hidden').map(e=>e.id)''')
    if len(ids)!=1:raise ValueError('1C list settings form ambiguous')
    modal=_control(page,ids[0])
    # Official 1C list settings may show a compact Presentation tree rather
    # than separate Field/Comparison headers. Require the field AND comparator
    # in the same native grid row; the available-field tree alone is not a filter.
    comparison_labels=('Равно','Не равно','В списке','Не в списке',
                       'Equal to','Not equal to','Equal','Not equal','In list','Not in list')
    rows=modal.locator('.gridBody > .gridLine:visible').filter(
        has=page.get_by_text(re.compile(r'^Тип\s*Курьера:?$',re.I))).filter(
        has=page.get_by_text(re.compile('^(?:'+'|'.join(re.escape(v) for v in comparison_labels)+')$')))
    mark('settings_filter_tab')
    if not rows.count():
        tabs=modal.get_by_role('tab',name=re.compile(r'^(Отбор|Filter)$'))
        if tabs.count()==1:tabs.click(timeout=5000)
        else:_choose(modal,('Отбор','Filter'))
    rows.first.wait_for(state='visible',timeout=10000)
    if rows.count()!=1:raise ValueError('1C courier type filter row not uniquely identified')
    row=rows.first
    mark('settings_type_comparison')
    current=_option(row,comparison_labels)
    if current.inner_text().strip() not in ('Не в списке','Not in list'):
        current.dblclick(timeout=5000)
        choices=page.get_by_text(re.compile(r'^(Не в списке|Not in list)$')).and_(page.locator(':visible'))
        if not choices.count():
            focused=modal.locator('input:focus')
            if focused.count()!=1:raise ValueError('1C comparison editor not identified')
            identity=focused.get_attribute('id') or ''
            button=_control(page,identity[:-3]+'_DLB') if identity.endswith('_i0') else None
            if button is not None and button.is_visible():button.click(timeout=5000)
            else:focused.press('F4')
        _choose(page,('Не в списке','Not in list'))
        page.keyboard.press('Tab')
        _option(row,('Не в списке','Not in list')).wait_for(state='visible',timeout=5000)
    mark('settings_apply')
    _choose(modal,('Завершить редактирование','Закончить редактирование','Finish editing','ОК','OK'))
    modal.wait_for(state='hidden',timeout=10000)
    use=_control(page,PREFIX+'5Использование')
    use.wait_for(state='visible',timeout=10000)
    if not use.evaluate('(e)=>e.classList.contains("select")'):
        use.click(timeout=5000)
        page.wait_for_function('(id)=>document.getElementById(id)?.classList.contains("select")',
                               arg=PREFIX+'5Использование',timeout=10000)
    _control(page,PREFIX+'5ВидСравненияЭлементаОтбора_i0').wait_for(state='visible',timeout=10000)


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
    comparison=_control(page,PREFIX+'5ВидСравненияЭлементаОтбора_i0')
    if not comparison.is_visible():restore_type_comparison_in_settings(page,progress)
    _choice(page,PREFIX+'5ВидСравненияЭлементаОтбора',('Не в списке','Not in list'))
    if type_selection_valid(page):return
    base=PREFIX+'5Значение'
    if _type_shape(page)['count']:
        mark('types_clear')
        label=_control(page,base)
        if label.is_visible():label.hover(timeout=5000)
        _control(page,base+'_CLR').click(timeout=5000)
        page.wait_for_function("""(base)=>!Array.from(document.querySelectorAll('[id]')).some(e=>
            e.id.startsWith(base+'_multipleValues_') && e.classList.contains('chipsItem') && Number.isInteger(parseInt(e.title,10)))
            && !Number(document.getElementById(base+'_multipleValues_more')?.textContent?.trim().replace('+','')||0)""",arg=base,timeout=5000)
        if _type_shape(page)['count']:raise ValueError('1C courier type list was not cleared')
    for number,(code,label) in enumerate(TYPES.items(),start=1):
        mark('type_'+str(code)+'_select')
        field=_control(page,base+'_i0')
        field.click(timeout=5000)
        if field.input_value():
            field.press('Control+A');field.press('Backspace')
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
