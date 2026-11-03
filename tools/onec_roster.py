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
