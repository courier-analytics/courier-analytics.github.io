"use strict";
(function(){
  if(!window.courierPrivate&&!window.courierOpenDetails)return;
  const style=document.createElement('style');style.textContent='.private-detail-tools{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}.private-detail-tools input,.private-detail-tools select{font:inherit;padding:9px;border:1px solid #cbd5e1;border-radius:8px;max-width:100%}.private-detail-table{overflow:auto}.private-detail-table table{width:100%;border-collapse:collapse;font-size:13px}.private-detail-table th,.private-detail-table td{padding:9px;border:1px solid #dbe3ef;vertical-align:top;text-align:left;white-space:pre-line}.private-detail-table th{background:#edf2fa}.private-detail-note{padding:12px;background:#fff5d6;border-radius:9px}.private-detail-section h3{margin:24px 0 8px}';document.head.append(style);
  const node=(tag,text)=>{const e=document.createElement(tag);e.textContent=text;return e;};
  const when=value=>value?new Date(value).toLocaleString('ru-RU',{timeZone:'Europe/Moscow',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—';
  const late=value=>value===null||value===undefined?'Не определено':value===0?'Без опоздания':`${Math.floor(value/3600)} ч ${Math.floor(value%3600/60)} мин ${value%60} с`;
  function table(headers,rows){
    const wrap=node('div','');wrap.className='private-detail-table';const t=node('table','');const head=node('thead','');const hr=node('tr','');
    headers.forEach(h=>hr.append(node('th',h)));head.append(hr);const body=node('tbody','');
    rows.forEach(values=>{const row=node('tr','');values.forEach(value=>row.append(node('td',String(value??'—'))));body.append(row);});
    t.append(head,body);wrap.append(t);return wrap;
  }
  let pending;
  window.addEventListener('metric-detail-open',async event=>{
    if(pending)pending.abort();pending=new AbortController();const signal=pending.signal;
    const {dialog,shop,day,key,metric}=event.detail;const section=node('section','');section.className='private-detail-section';dialog.append(section);
    section.append(node('h3','Курьеры и разбивка'),node('p','Загружаем персональные данные…'));
    dialog.addEventListener('close',()=>{if(dialog.contains(section)&&pending)pending.abort();},{once:true});
    try{
      const url=window.courierOpenDetails?'data/details-7745.json':`/api/details/${encodeURIComponent(shop)}/${encodeURIComponent(day)}/${encodeURIComponent(key)}`;
      const response=await fetch(url,{cache:'no-store',signal});
      if(!window.courierOpenDetails&&response.status===401){location.replace('/login');return;}
      let payload=await response.json();if(window.courierOpenDetails){const record=payload.shop_id===Number(shop)&&payload.records?.[day];payload={available:!!record?.metrics?.[key],generated_at:record?.generated_at,detail:record?.metrics?.[key]};}if(signal.aborted||!dialog.open||!dialog.contains(section))return;
      section.replaceChildren(node('h3','Курьеры и разбивка'));
      if(!payload.available){section.append(node('p',payload.note||'Детализация пока недоступна.'));return;}
      if(!response.ok)throw Error('details');
      const data=payload.detail;section.append(node('p','Снимок детализации: '+when(payload.generated_at)+' МСК'));
      if(data.note)section.append(node('p',data.note));
      if(!data.reconciled || ['numerator','denominator','value','basis'].some(k=>data.aggregate[k]!==metric[k])){
        const warning=node('p','Разбивка показывает отдельный снимок известных фактов. Совпадение с расчётом процента вверху не подтверждено.');warning.className='private-detail-note';section.append(warning);
      }
      dialog.style.width='min(1120px,calc(100vw - 24px))';
      const tools=node('div','');tools.className='private-detail-tools';const search=node('input','');search.type='search';search.placeholder='Поиск по ФИО или ID';search.setAttribute('aria-label','Поиск по ФИО или ID');
      const select=node('select','');select.setAttribute('aria-label','Группа курьеров');const all=node('option','Все группы');all.value='';select.append(all);
      (data.groups||[]).forEach((group,i)=>{const option=node('option',`${group.title} (${group.count})`);option.value=String(i);select.append(option);});
      tools.append(search);if(data.groups?.length)tools.append(select);section.append(tools);const content=node('div','');section.append(content);
      function render(){
        content.replaceChildren();const query=search.value.trim().toLocaleLowerCase('ru');let found=0;
        if(data.slots){
          const rows=data.slots.filter(s=>!query||s.couriers.some(p=>(p.name+' '+p.courier_id).toLocaleLowerCase('ru').includes(query))||s.slot_id.includes(query)).map(s=>[s.slot_id,s.scope,s.slot_type==='limited'?'Лимитированный':'Ручной',when(s.planned_start)+' — '+when(s.planned_end),s.capacity??'Без лимита',s.occupied,s.free??'—',s.couriers.map(p=>p.name+' · ID '+p.courier_id).join('\n')||'Нет записей']);
          if(rows.length){content.append(table(['Слот','ДС / кластер','Тип','План, МСК','Мест','Записано','Свободно','Курьеры'],rows));found+=rows.length;}
        }
        (data.groups||[]).forEach((group,i)=>{
          if(select.value!==''&&select.value!==String(i))return;
          const people=group.couriers.filter(p=>!query||(p.name+' '+p.courier_id).toLocaleLowerCase('ru').includes(query));
          if(!people.length)return;found+=people.length;
          content.append(node('h3',`${group.title} · ${query?people.length:group.count} курьеров`));
          if(key==='training'){
            content.append(table(['ФИО','ID курьера','Обучение, МСК','Сверка'],people.map(p=>[p.name,p.courier_id,when(p.training_date),p.match_status||'—'])));
            return;
          }
          const rows=people.flatMap(p=>(p.slots.length?p.slots:[{}]).map(s=>[p.name,p.courier_id,s.slot_id||'—',s.slot_type==='limited'?'Лимитированный':s.slot_type==='manual'?'Ручной':'—',when(s.planned_start)+' — '+when(s.planned_end),when(s.actual_start)+' — '+(s.worked_through&&!s.actual_end?'как минимум до '+when(s.worked_through):when(s.actual_end)),s.slot_id&&!(s.removed_at&&!s.actual_start)?late(s.late_seconds):'—',s.status||'Нет записи на выбранный день',when(s.removed_at),s.removed_by||'—',s.note||'']));
          content.append(table(['ФИО','ID курьера','Слот','Тип','План, МСК','Факт, МСК','Опоздание','Статус','Снято, МСК','Кто снял','Примечание'],rows));
        });
        if(!found)content.append(node('p',query?'Совпадений не найдено.':'Нет записей в этой группе.'));
      }
      search.addEventListener('input',render);select.addEventListener('change',render);render();
    }catch(error){if(error.name!=='AbortError'&&dialog.contains(section))section.replaceChildren(node('h3','Курьеры и разбивка'),node('p','Не удалось загрузить детализацию. Закройте окно и попробуйте снова.'));}
  });
}());
