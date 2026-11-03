"""Read only the evidenced 1C courier grid; never publish a viewport as a roster."""
import time


def grid_rows(page):
    data = page.evaluate('''() => {
        const root = document.getElementById('grid_form0_Список');
        if (!root) return null;
        const headings = Array.from(root.querySelectorAll('.gridHead .gridLine > .gridBox'))
            .map(e => e.innerText.trim());
        const cells = Array.from(root.querySelectorAll('.gridBody > .gridLine')).map(row =>
            Array.from(row.children).filter(e => e.classList.contains('gridBox')).map(e => ({
                text: e.innerText.trim(), checked: !!e.querySelector('.checkbox.select')
            })));
        return {headings,cells};
    }''')
    if not data:
        raise ValueError('1C courier grid absent')
    headings = data['headings']
    required = ('Id', 'Name', 'Active', 'Т.З.')
    if any(headings.count(name) != 1 for name in required):
        raise ValueError('1C courier grid columns changed')
    positions = [headings.index(name) for name in required]
    rows = []
    for cells in data['cells']:
        if len(cells) != len(headings):
            raise ValueError('Incomplete 1C grid row')
        identity, name, active, employment = [cells[i] for i in positions]
        if not identity['text'].isdigit() or not name['text'] or not employment['text'].isdigit():
            raise ValueError('Invalid 1C courier grid identity or employment')
        if not active['checked'] or employment['text'] == '1':
            raise ValueError('1C grid contradicts requested access/employment filters')
        rows.append({'courier_id': identity['text'], 'name': name['text'],
                     'access': True, 'employment_type': int(employment['text'])})
    return rows


def scan_grid(page, max_pages=60, max_seconds=90):
    """Bounded keyboard traversal. A stationary viewport alone never proves completeness."""
    grid = page.locator('[id="grid_form0_Список"]')
    first = grid.locator('.gridBody > .gridLine > .gridBox').first
    first.click(timeout=5000)
    page.keyboard.press('Control+Home')
    page.wait_for_timeout(1000)
    seen, pages = {}, []
    deadline = time.monotonic() + max_seconds
    reason = 'page_limit'
    previous = None
    for _ in range(max_pages):
        if time.monotonic() >= deadline:
            reason = 'time_limit'
            break
        rows = grid_rows(page)
        signature = [r['courier_id'] for r in rows]
        pages.append(signature)
        for row in rows:
            old = seen.get(row['courier_id'])
            if old is not None and old != row:
                raise ValueError('1C roster changed during traversal')
            seen[row['courier_id']] = row
        if signature == previous:
            reason = 'stationary_viewport'
            break
        previous = signature
        page.keyboard.press('PageDown')
        page.wait_for_timeout(1200)
    page.keyboard.press('Control+End')
    page.wait_for_timeout(1500)
    tail = grid_rows(page)
    tail_ids = [r['courier_id'] for r in tail]
    unseen_tail = [r['courier_id'] for r in tail if r['courier_id'] not in seen]
    for row in tail:
        old = seen.get(row['courier_id'])
        if old is not None and old != row:
            raise ValueError('1C roster changed at traversal end')
        seen[row['courier_id']] = row
    return {'shop_id': 7745, 'couriers': list(seen.values()), 'count_observed': len(seen),
            'pages': pages, 'tail_ids': tail_ids, 'unseen_tail_ids': unseen_tail,
            'stop_reason': reason, 'complete_roster': False,
            'note': 'Candidate only: native list export or independent total required to verify completeness.'}


def inspect_export_dialog(page):
    """Open only the evidenced 'Output list' command, without confirming export."""
    from playwright.sync_api import TimeoutError as BrowserTimeout
    menu = page.locator('[id="form0_allActionsФормаКоманднаяПанель"]')
    if not menu.is_visible():
        return {'opened': False, 'reason': 'menu_absent'}
    menu.click(timeout=5000)
    command = page.locator('[id="form0_popup_ФормаВывестиСписок"]').and_(page.locator(':visible'))
    try:
        command.first.wait_for(state='visible', timeout=5000)
    except BrowserTimeout:
        page.keyboard.press('Escape')
        return {'opened': False, 'reason': 'output_list_command_not_visible'}
    if command.count() != 1:
        page.keyboard.press('Escape')
        return {'opened': False, 'reason': 'ambiguous_output_list_command'}
    command.click(timeout=5000)
    page.wait_for_timeout(1500)
    return page.evaluate('''() => {
        const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
        return {opened:true,confirmed:false,
            elements:Array.from(document.querySelectorAll('[id]'))
                .filter(e=> /^form[1-9][0-9]*_/.test(e.id) && visible(e))
                .slice(0,200).map(e=>({id:e.id,tag:e.tagName,class:e.className,
                    title:e.getAttribute('title'),type:e.type || null,
                    text:e.tagName === 'INPUT' ? null : (e.innerText || '').trim().slice(0,200)}))};
    }''')


def export_id_list(page, filters_verified):
    """Output all filtered IDs through the native read-only list command."""
    if not filters_verified:
        return {'confirmed': False, 'reason': 'filters_not_verified'}
    from playwright.sync_api import TimeoutError as BrowserTimeout
    page.locator('[id="form1_UnckeckAll"]').click(timeout=5000)
    page.wait_for_timeout(500)
    rows = page.locator('[id="form1_AvailableColumnsElement"] .gridBody > .gridLine')
    identity = rows.filter(has=page.get_by_text('Id', exact=True))
    if identity.count() != 1:
        return {'confirmed': False, 'reason': 'id_column_not_unique'}
    checkbox = identity.locator('.checkbox')
    if checkbox.count() != 1:
        return {'confirmed': False, 'reason': 'id_checkbox_not_unique'}
    if 'select' not in (checkbox.get_attribute('class') or '').split():
        checkbox.click(timeout=5000)
        page.wait_for_timeout(500)
    columns=['Id']
    name_row=rows.filter(has=page.get_by_text('Name',exact=True))
    if name_row.count()==1:
        name_box=name_row.locator('.checkbox')
        if name_box.count()==1:
            if 'select' not in (name_box.get_attribute('class') or '').split():
                name_box.click(timeout=5000);page.wait_for_timeout(500)
            columns.append('Name')
    selected = rows.filter(has=page.locator('.checkbox.select'))
    if sorted(text.strip() for text in selected.all_inner_texts()) != sorted(columns):
        return {'confirmed': False, 'reason': 'id_only_selection_not_confirmed'}
    only_selected = page.locator('[id="form1_OnlySelectedElement"]')
    if 'select' in (only_selected.get_attribute('class') or '').split():
        only_selected.click(timeout=5000)
        page.wait_for_timeout(500)
    if 'select' in (only_selected.get_attribute('class') or '').split():
        return {'confirmed': False, 'reason': 'selected_rows_only_still_enabled'}
    output = page.locator('[id="form1_DocumentTypeElement_i0"]')
    if output.input_value().strip() not in ('Text document', 'Текстовый документ'):
        page.locator('[id="form1_DocumentTypeElement_DLB"]').click(timeout=5000)
        options = page.get_by_text('Text document', exact=True).or_(
            page.get_by_text('Текстовый документ', exact=True)).and_(page.locator(':visible'))
        try:
            options.first.wait_for(state='visible', timeout=5000)
        except BrowserTimeout:
            return {'confirmed': False, 'reason': 'text_output_option_not_visible'}
        if options.count() != 1:
            return {'confirmed': False, 'reason': 'text_output_option_ambiguous'}
        options.click(timeout=5000)
        page.wait_for_timeout(300)
    if output.input_value().strip() not in ('Text document', 'Текстовый документ'):
        return {'confirmed': False, 'reason': 'text_output_not_retained'}
    page.locator('[id="form1_Ok"]').click(timeout=5000)
    output.wait_for(state='hidden', timeout=30000)
    page.wait_for_timeout(4000)
    documents = page.evaluate('''() => {
        const visible=e=>e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
        return {
            text_fields:Array.from(document.querySelectorAll('textarea,pre')).filter(visible)
                .slice(0,10).map(e=>({id:e.id,text:(e.value ?? e.innerText ?? '').slice(0,1000000)})),
            forms:Array.from(document.querySelectorAll('[id]'))
                .filter(e=>/^form[1-9][0-9]*_container$/.test(e.id) && visible(e))
                .slice(0,5).map(e=>({id:e.id,text:(e.innerText || '').slice(0,1000000)})),
            structure:Array.from(document.querySelectorAll('[id]'))
                .filter(e=>/^form[1-9][0-9]*_/.test(e.id) && visible(e))
                .slice(0,150).map(e=>({id:e.id,tag:e.tagName,class:e.className}))
        };
    }''')
    return {'confirmed': True, 'columns': columns, 'only_selected': False,
            'format': 'text', 'documents': documents, 'complete_roster': False}


def parse_id_document(text):
    """Accept only a complete one-column native text output, not arbitrary UI text."""
    import re
    lines = [line.strip().strip('\ufeff') for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != 'Id':
        raise ValueError('Native output must contain the Id header only')
    identities = lines[1:]
    if not identities or any(not re.fullmatch(r'[0-9]{6,12}', item) for item in identities):
        raise ValueError('Native Id output contains unknown rows')
    if len(set(identities)) != len(identities):
        raise ValueError('Duplicate identities in native output')
    return identities


def verify_id_export(export, observed):
    if not export.get('confirmed') or export.get('columns') not in (['Id'],['Id','Name']) or export.get('only_selected') is not False:
        return {'verified': False, 'reason': 'native_export_not_confirmed'}
    parsed = []
    names={}
    for doc in export.get('documents', {}).get('text_fields', []):
        candidate_names={}
        try:
            if export['columns']==['Id','Name']:
                import re
                lines=[line.strip() for line in doc['text'].splitlines() if line.strip()]
                if not re.fullmatch(r'Id\s+Name',lines[0]):raise ValueError('Unexpected name output header')
                people=[]
                for line in lines[1:]:
                    match=re.fullmatch(r'([0-9]{6,12})[ \t]+(\S[^\t\r\n]*)',line)
                    if not match:raise ValueError('Unexpected name output row')
                    people.append(match.groups())
                identities=[i for i,n in people]
                if not people or len(set(identities))!=len(identities):raise ValueError('Duplicate name output IDs')
                candidate_names=dict(people)
            else:identities = parse_id_document(doc['text'])
        except (ValueError, KeyError, TypeError, IndexError):
            continue
        if not set(observed).issubset(identities):
            continue
        names=candidate_names
        parsed.append(identities)
    if not parsed or any(set(ids) != set(parsed[0]) for ids in parsed[1:]):
        return {'verified': False, 'reason': 'complete_plain_text_output_not_verified'}
    return {'verified': True, 'courier_ids': parsed[0], 'names':names,'count': len(parsed[0]),
            'basis': 'native_all_filtered_rows_id_only_text_output'}
