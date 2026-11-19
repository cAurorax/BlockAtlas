import {itemSvg} from './items.js';

export function avatarDock(user, escape){
  const portrait = Math.abs(Number(user.id)||0)%3;
  return `<div class="player-dock">
    <button type="button" id="account-home" class="player-trigger" aria-controls="player-pouch" aria-expanded="false" aria-label="打开账号菜单" title="账号菜单">
      <span class="portrait-slot"><img src="/static/images/player-${portrait}.png" alt="" width="36" height="36"></span>
      <span class="player-name"><b>${escape(user.nickname)}</b><small>@${escape(user.username)}</small></span>
    </button>
    <div id="player-pouch" hidden role="group" aria-label="账号操作">
      <div class="pouch-heading"><img src="/static/images/pouch.png" alt="" width="22" height="22"><span>玩家行囊</span></div>
      <button data-section="mine"><span>${itemSvg('mine',24)}</span>我的发布</button>
      <button data-section="settings"><span>${itemSvg('settings',24)}</span>账号设置</button>
      <button id="logout"><span><svg width="20" height="20" viewBox="0 0 16 16" shape-rendering="crispEdges" aria-hidden="true"><path fill="#967449" d="M2 2h8v2H4v8h6v2H2z"/><path fill="#a46543" d="M10 4h2v2h2v1h2v2h-2v1h-2v2h-2V9H6V7h4z"/></svg></span>退出登录</button>
    </div></div>`;
}
// Use the avatar as the layout anchor, including in embedded browser windows.
function setOpen(visible, restore=false){
  const button=document.getElementById('account-home'), panel=document.getElementById('player-pouch');
  if(!button||!panel)return;
  panel.hidden=!visible;
  button.setAttribute('aria-expanded',String(visible));
  if(restore)button.focus();
}
document.addEventListener('pointerdown',e=>{
  if(!e.target.closest('.player-dock'))setOpen(false);
});
document.addEventListener('focusin',e=>{
  if(!e.target.closest('.player-dock'))setOpen(false);
});
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'&&document.querySelector('#player-pouch:not([hidden])')){
    e.preventDefault();setOpen(false,true);
  }
});
export function bindAvatar(navigate,logout){
  const menu=document.querySelector('#player-pouch'),trigger=document.querySelector('#account-home');
  trigger.onclick=()=>setOpen(menu.hidden);
  trigger.onkeydown=e=>{if(e.key==='ArrowDown'){e.preventDefault();setOpen(true);menu.querySelector('button').focus()}};
  menu.querySelectorAll('[data-section]').forEach(b=>b.onclick=()=>{setOpen(false);navigate(b.dataset.section)});
  menu.querySelector('#logout').onclick=()=>{setOpen(false,true);logout()};
  menu.onkeydown=e=>{
    const items=[...menu.querySelectorAll('button')],i=items.indexOf(document.activeElement);
    if(['ArrowUp','ArrowDown','Home','End'].includes(e.key)){
      e.preventDefault();items[e.key==='Home'?0:e.key==='End'?items.length-1:(i+(e.key==='ArrowUp'?-1:1)+items.length)%items.length].focus();
    }
  };
}
