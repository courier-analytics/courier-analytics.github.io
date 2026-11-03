"use strict";
(async function () {
  const response = await fetch('/api/session', {cache: 'no-store'});
  if (!response.ok) return;
  const current = await response.json();
  setInterval(async()=>{
    try {
      const status=await fetch('/api/session',{cache:'no-store'});
      if(status.status===401)location.replace('/login');
    } catch (_) {}
  },60000);
  const area = document.createElement('div');
  area.style.cssText = 'display:flex;gap:12px;justify-content:flex-end;align-items:center;padding:10px 20px;background:#edf2fa;font:14px system-ui;color:#18364b';
  const name = document.createElement('span');name.textContent = current.username;
  const button = document.createElement('button');button.type='button';button.textContent='Выйти';
  button.style.cssText='border:1px solid #cbd5e1;border-radius:8px;background:white;padding:6px 12px;cursor:pointer;font:inherit';
  button.addEventListener('click',async()=>{
    button.disabled=true;
    try {
      const result=await fetch('/logout',{method:'POST',headers:{'X-CSRF-Token':current.csrf}});
      if(!result.ok)throw Error('logout');
      location.replace('/login');
    } catch (_) {button.disabled=false;button.textContent='Повторить выход';}
  });
  area.append(name,button);document.body.prepend(area);
}()).catch(()=>{});
