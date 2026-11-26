import {itemSvg} from './items.js';
export const mark=itemSvg('brand',40);
const mainItems=[['feed','玩家广场','广场'],['library','发现 Mod','Mod'],['ai','AI 工坊','AI'],['bench','整合包工作台','整合包'],['friends','好友','好友']];
function navItem([key,title,short],active){
  return `<button type="button" data-view="${key}" aria-label="${title}" title="${title}" ${key===active?'aria-current="page" class="active"':''}><span class="item-slot">${itemSvg(key,28)}</span><span class="nav-label">${title}</span><span class="nav-mini" aria-hidden="true">${short}</span></button>`;
}
export function sidebar(active){
  const section=({friendsFeed:"friends",vision:"ai"})[active]||active;
  return `<div class="navgroup primary-pages">${mainItems.map(item=>navItem(item,section)).join('')}</div>`;
}
const compact=window.matchMedia('(max-width: 900px)');
export function closeRail(restore=false){
  const open=document.body.classList.contains('rail-open'),rail=document.querySelector('.sidebar'),toggle=document.querySelector('#rail-toggle');
  document.body.classList.remove('rail-open');
  if(rail){rail.removeAttribute('role');rail.removeAttribute('aria-modal')}
  if(toggle){toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-label','展开导航')}
  const main=document.querySelector('#app > main');if(main)main.inert=false;
  if(restore&&open)toggle?.focus();
}
export function bindRail(){
  const toggle=document.querySelector('#rail-toggle'),rail=document.querySelector('.sidebar');
  toggle.onclick=()=>{
    if(document.body.classList.contains('rail-open'))return closeRail(true);
    if(!compact.matches)return;
    document.body.classList.add('rail-open');document.querySelector('#app > main').inert=true;
    rail.setAttribute('role','dialog');rail.setAttribute('aria-modal','true');
    toggle.setAttribute('aria-label','收起导航');toggle.setAttribute('aria-expanded','true');
    rail.querySelector('[aria-current=page]')?.focus();
  };
  document.querySelector('#rail-scrim').onclick=()=>closeRail(true);
}
compact.addEventListener('change',()=>closeRail());
document.addEventListener('keydown',e=>{
  if(!document.body.classList.contains('rail-open'))return;
  if(document.querySelector('#player-pouch:not([hidden])'))return;
  if(e.key==='Escape'){e.preventDefault();closeRail(true);return}
  if(e.key!=='Tab')return;
  const buttons=[...document.querySelectorAll('.sidebar button,.sidebar summary')].filter(b=>b.getClientRects().length);if(!buttons.length)return;
  if(e.shiftKey&&document.activeElement===buttons[0]){e.preventDefault();buttons.at(-1).focus()}
  if(!e.shiftKey&&document.activeElement===buttons.at(-1)){e.preventDefault();buttons[0].focus()}
});
