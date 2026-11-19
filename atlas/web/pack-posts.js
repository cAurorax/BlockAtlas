const esc = (v) => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function packCard(post) {
  return post.pack ? `<div class="pack-release"><div><small>PACK RELEASE / v${post.pack.revision}</small><strong>作者整合包 · ${post.pack.count} 个组件</strong></div><button type="button" class="small ghost" data-pack-details="${post.id}/${post.pack.id}">查看整包与实测 →</button></div>` : '';
}
export function packEditor(post) {
  return `<label class="pack-attach"><input type="checkbox" name="attach_pack"><span><b>${post?.pack?'把当前草稿发布为新版本':'附上我的整合包'}</b><small>${post?.pack?'不勾选将保留之前发布的版本和实测记录。':'保存发布时的组件版本，其他玩家可据此派生自己的包。'}</small></span></label>`;
}
async function api(path, method='GET',body) {
  const r=await fetch('/api'+path,{method,credentials:'same-origin',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
  const j=await r.json();if(!r.ok)throw Error(typeof j.detail==='string'?j.detail:'操作未完成，请检查输入后重试');return j;
}
async function evidenceOptions(){
  const choices=[];let page=1,total=Infinity;
  while((page-1)*50<total){const r=await api('/posts?scope=mine&page_size=50&page='+page++);
    total=r.total;choices.push(...r.items.filter(x=>x.visibility==='public'&&!x.hidden&&x.media?.length));}
  return choices;
}
let dialog, epoch=0;
function alertLine(root,err){const target=root.querySelector('[data-pack-message]');if(target)target.textContent=err.message;}
function close(){epoch++;dialog?.close();}
async function show(pid,vid){
  const sequence=++epoch;
  if(!dialog){dialog=document.createElement('dialog');dialog.className='pack-sheet';document.body.appendChild(dialog);}
  dialog.innerHTML='<div class="modal-head"><h2>整包档案</h2><button aria-label="关闭">×</button></div><p>正在读取固定版本…</p>';dialog.querySelector('button').onclick=close;
  if(!dialog.open)dialog.showModal();
  const path='/posts/'+pid+'/packs/'+vid;
  try {
    const [v,mine]=await Promise.all([api(path),evidenceOptions()]);if(sequence!==epoch||!dialog.open)return;
    const total=Object.values(v.totals).reduce((a,b)=>a+b,0);
    dialog.innerHTML=`<div class="modal-head"><div><small>PACK RELEASE</small><h2>${esc(v.title)}</h2></div><button type="button" data-close aria-label="关闭">×</button></div>
    <div class="pack-meta"><b>Java 1.20.1 / Fabric</b><label>版本 <select data-version>${v.versions.map(x=>`<option value="${x.id}" ${x.id===Number(vid)?'selected':''}>v${x.rev}</option>`).join('')}</select></label></div>
    <h3>组件清单 · ${v.mods.length}</h3><div class="pack-pins">${v.mods.map(m=>`<div><strong>${esc(m.title)}</strong><small>${esc(m.version)}</small></div>`).join('')}</div>
    <button type="button" data-derive>基于这一版修改</button><p class="hint">使用这一版完整清单作为私人草稿，可撤销切换。原帖不会改变。</p>
    <h3>v${v.revision} 实测墙</h3><p>${v.totals['成功']||0} 成功 / ${total} 人实测 · 异常 ${v.totals['异常']||0} · 未启动 ${v.totals['未启动']||0}</p>
    ${v.trials.map(t=>`<article class="pack-trial"><b>${esc(t.nickname)} · ${esc(t.outcome)}</b><p>${esc(t.note)}</p>${(t.evidence?.media||[]).map(m=>m.kind==='video'?`<video controls preload="metadata" src="${esc(m.url)}"></video>`:`<img loading="lazy" src="${esc(m.url)}" alt="实测截图">`).join('')}</article>`).join('')}
    <form data-trial><label>记录我在这版的实测</label><select name="outcome"><option>成功</option><option>异常</option><option>未启动</option></select><textarea required maxlength="500" rows="2" name="note" placeholder="运行环境、测试步骤与现象"></textarea>
    <label>附上自己的公开媒体帖（可选）</label><select name="evidence"><option value="">仅文字</option>${mine.map(p=>`<option value="${p.id}">#${p.id} ${esc(p.content.slice(0,50)||'媒体帖')}</option>`).join('')}</select><button>保存本版实测</button></form><p data-pack-message role="status"></p>`;
    dialog.querySelector('[data-close]').onclick=close;
    dialog.querySelector('[data-version]').onchange=e=>show(pid,Number(e.target.value));
    dialog.querySelector('[data-derive]').onclick=async e=>{
      e.target.disabled=true;try{await api(path+'/derive','POST');close();document.querySelector('[data-view=bench]')?.click();}catch(err){e.target.disabled=false;alertLine(dialog,err);}
    };
    dialog.querySelector('[data-trial]').onsubmit=async e=>{e.preventDefault();const form=e.currentTarget,btn=form.querySelector('button'),data=new FormData(form);btn.disabled=true;try{
      await api(path+'/trials','POST',{outcome:data.get('outcome'),note:data.get('note'),evidence_post_id:Number(data.get('evidence'))||null});await show(pid,vid);
    }catch(err){btn.disabled=false;alertLine(dialog,err);}};
  }catch(err){if(sequence===epoch)dialog.querySelector('p').textContent=err.message;}
}
document.addEventListener('click',e=>{const b=e.target.closest('[data-pack-details]');if(!b)return;const [pid,vid]=b.dataset.packDetails.split('/').map(Number);show(pid,vid);});

