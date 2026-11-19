// Independent admin application. Never use the player's browser session cookie.
const $=q=>document.querySelector(q), root=$('#root'), modal=$('#modal');
const pages={dashboard:['◈','运营概览'],ai:['✦','AI 模型设置'],reports:['⚑','举报工单'],manage:['▤','帖子管理'],users:['◎','用户管理'],library:['▦','资源管理'],words:['◇','敏感词库'],audit:['≡','操作日志'],settings:['⚙','账号设置']};
const states={page:'dashboard',q:'',pn:1,status:'all',user:null}; let paint=0;
const esc=s=>String(s??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const short=(s,n=65)=>s?.length>n?s.slice(0,n)+'…':s||'（无文字）';
const dt=s=>s?new Date(s).toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'}):'—';
const token=()=>sessionStorage.getItem('atlas-admin')||'';
const badge=(s,warn=false)=>`<span class="badge ${warn?'amber':''}">${esc(s)}</span>`;
function toast(t){$('#message').textContent=t;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#message').textContent='',3500)}
async function api(path,method='GET',body){
 const r=await fetch('/api'+path,{method,credentials:'omit',headers:{Authorization:'Bearer '+token(),...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});
 const x=await r.json();if(!r.ok){if(r.status===401&&states.user){clearSession();login()}throw Error(typeof x.detail==='string'?x.detail:'请检查输入后重试')}return x;
}
function clearSession(){sessionStorage.removeItem('atlas-admin');states.user=null;if(modal.open)modal.close()}
const brand='<div class="brand"><span class="mark">▦</span><div><b>方块工坊</b><small>社区管理</small></div></div>';
function login(){root.innerHTML=`<div class="login"><aside>${brand}<div><h1>社区管理台</h1><p>核实原帖，处理反馈，维护资源库。</p></div></aside><form id="login"><h2>管理员登录</h2><label for="un">管理账号</label><input id="un" name="username" autocomplete="username" required><label for="pw">密码</label><input id="pw" type="password" name="password" autocomplete="current-password" required><p class="error" id="login-error"></p><button type="submit" class="primary">进入管理台 →</button><div class="line"><button type="button" data-demo="admin">填入演示账号</button><a href="/">返回玩家端</a></div></form></div>`;
 $('[data-demo]').onclick=()=>{$('#un').value='admin';$('#pw').value='Admin123!'};
 $('#login').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('button[type=submit]');b.disabled=true;try{const x=await api('/auth/login','POST',Object.fromEntries(new FormData(e.target)));sessionStorage.setItem('atlas-admin',x.token);if(x.user.role!=='admin'){await api('/auth/logout','POST');clearSession();throw Error('请使用管理员账号登录')}states.user=x.user;go(location.hash.slice(1)||'dashboard')}catch(err){$('#login-error').textContent=err.message}finally{b.disabled=false}}}
function dlg(title,body){modal.innerHTML=`<div class="dialog-head"><h2 id="dialog-title">${esc(title)}</h2><button id="close-modal" aria-label="关闭">×</button></div>${body}<p id="dialog-error" class="error" role="alert"></p>`;if(!modal.open)modal.showModal();$('#close-modal').onclick=()=>modal.close()}
function confirm(title,body,run){dlg(title,`<p class="note">${esc(body)}</p><button class="primary" id="confirm">确认${esc(title)}</button>`);$('#confirm').onclick=async e=>{e.target.disabled=true;try{await run();modal.close();toast('操作已保存');await load()}catch(err){$('#dialog-error').textContent=err.message;e.target.disabled=false}}}
const names={hide_post:'下架帖子',restore_post:'恢复帖子',delete_post:'删除帖子',disable_user:'停用用户',enable_user:'启用用户',delete_user:'删除用户',add_word:'添加敏感词',delete_word:'移除敏感词',review_summary:'生成证据摘要',review_decision:'举报处理决定',resource_description:'更新资源说明'};
function go(page){states.page=pages[page]?page:'dashboard';states.q='';states.pn=1;states.status='all';history.replaceState(null,'','#'+states.page);shell();load()}
const sections=[['社区',['dashboard','reports','manage','users','library']],['系统',['ai','words','audit','settings']]];
function shell(){
 const {page,user}=states;
 const groups=sections.map(([section,keys])=>`<section class="nav-set"><small>${section}</small>${keys.map(id=>`<button data-view="${id}" ${page===id?'aria-current="page"':''}><span class="ico" aria-hidden="true">${pages[id][0]}</span>${pages[id][1]}</button>`).join('')}</section>`).join('');
 root.innerHTML=`<div class="layout"><aside class="rail">${brand}<button id="menu-toggle" aria-controls="ops-nav" aria-expanded="false">管理菜单</button><nav id="ops-nav" class="group" aria-label="管理导航">${groups}</nav><div class="user"><strong>${esc(user.nickname)}</strong></div></aside><section class="body-pane"><header class="top"><span>管理工作区</span><div><a href="/" target="_blank" rel="noopener">玩家端 ↗</a>　<button id="out">退出</button></div></header><main class="main" id="content" aria-live="polite"></main></section></div>`;
 const toggle=$('#menu-toggle');
 const setMenu=(on)=>{toggle.setAttribute('aria-expanded',String(on));$('.rail').classList.toggle('menu-open',on);toggle.textContent=on?'收起菜单':'管理菜单'};
 toggle.onclick=()=>setMenu(toggle.getAttribute('aria-expanded')!=='true');
 $('.rail').onkeydown=e=>{if(e.key==='Escape'&&toggle.getAttribute('aria-expanded')==='true'){setMenu(false);toggle.focus()}};
 root.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{go(b.dataset.view);if(window.matchMedia('(max-width:720px)').matches)$('#menu-toggle').focus()});
 $('#out').onclick=async()=>{try{await api('/auth/logout','POST')}finally{clearSession();login()}}
}
const head=(_code,title,desc,extra='')=>`<div class="head"><div><h1>${title}</h1>${desc?`<p>${desc}</p>`:''}</div>${extra}</div>`;
function table(cols,rows){if(!rows.length)return '<div class="empty">没有符合条件的记录。</div>';return `<div class="table-box"><table><thead><tr>${cols.map(c=>'<th>'+c+'</th>').join('')}</tr></thead><tbody>${rows.map(x=>'<tr>'+x.map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('')}</tbody></table></div>`}
const pager=(total,size)=>`<div class="pager"><button data-page="-1" ${states.pn===1?'disabled':''}>上一页</button><small>第 ${states.pn} 页 / 共 ${Math.max(1,Math.ceil(total/size))} 页　·　${total} 条</small><button data-page="1" ${states.pn*size>=total?'disabled':''}>下一页</button></div>`;
function filter(placeholder){return `<form class="tools" id="filter"><input name="q" aria-label="搜索" value="${esc(states.q)}" placeholder="${placeholder}"><button>搜索</button><button type="button" id="reset">重置</button></form>`}
function chart(trend){const max=Math.max(1,...trend.flatMap(x=>[x.posts,x.users]));return `<svg class="chart" viewBox="0 0 520 158" role="img" aria-label="近七日发帖和注册数量">${[0,1,2,3].map(i=>`<line x1="10" x2="512" y1="${15+i*36}" y2="${15+i*36}" stroke="#dce4d7"/>`).join('')}${trend.map((x,i)=>{const pos=25+i*73;return [x.posts,x.users].map((n,j)=>`<rect x="${pos+j*17}" y="${123-103*n/max}" width="14" height="${103*n/max}" fill="${j?'#dbad63':'#557a55'}"><title>${x.date} ${j?'注册':'发帖'}：${n}</title></rect>`).join('')+`<text x="${pos}" y="147" font-size="12" fill="#62735e">${x.date.slice(5)}</text>`}).join('')}</svg>`}
function row(a,b){return `<div class="queue-row"><span>${a}</span><strong>${b}</strong></div>`}
async function dashboard(){
 const [s,w,logs]=await Promise.all([api('/admin/stats'),api('/admin/workspace'),api('/admin/audit')]);
 const c=s.counts,metrics=[['周活跃玩家',c.active_7d],['社区帖子',c.posts],['待处理举报',w.pending],['已收录 Mod',w.resources]];
 const items=metrics.map(([name,value])=>`<div class="stat"><span>${name}</span><b>${value}</b></div>`).join('');
 const records=logs.slice(0,4).map(x=>row(esc(names[x.action]||x.action),esc(dt(x.created_at)))).join('')||'<p class="muted">暂无管理记录。</p>';
 return head('','社区运营概览','近七日活跃与当前社区数据。')+
 `<section class="stats" aria-label="社区数据">${items}</section>
 <div class="panes"><section class="panel"><div class="line"><h2>社区增长</h2><span class="legend"><i></i>发帖<i></i>注册</span></div>${chart(s.trend)}</section>
 <section class="panel dispatch"><h2>内容审核</h2><p>${w.pending?'有 '+w.pending+' 条举报等待核实。':'目前没有待处理的举报。'}</p><button class="primary" data-to="reports">${w.pending?'处理举报':'查看举报记录'}</button></section></div>
 <details class="extras"><summary>管理记录与互动数据</summary><div class="panes"><section class="panel"><div class="line"><h2>最近操作</h2><button class="link" data-to="audit">全部记录 →</button></div>${records}</section><section class="panel"><h2>社区互动</h2>${row('评分 / 评论',c.ratings+' / '+c.comments)}${row('实测记录',w.plays)}${row('已下架帖子',c.hidden)}${row('热门标签',s.tags.slice(0,3).map(x=>'#'+esc(x.name)).join('　')||'暂无')}</section></div></details>`;
}
async function manage(){const p=await api('/posts?'+new URLSearchParams({q:states.q,page:states.pn,page_size:15}));return head('MODERATION / POSTS','帖子管理','核对文字、媒体、作者和可见范围。下架后可恢复。')+filter('关键词搜索帖子')+table(['编号 / 作者','内容摘要','状态','操作'],p.items.map(x=>['#'+x.id+'<br>'+esc(x.nickname),esc(short(x.content)),badge(x.hidden?'已下架':({friends:'好友可见',private:'私密',public:'公开'}[x.visibility]),x.hidden),`<div class="actions"><button data-detail="${x.id}">查看</button><button data-togglepost="${x.id}" data-enable="${x.hidden?1:0}">${x.hidden?'恢复':'下架'}</button><button class="warn" data-delpost="${x.id}">删除</button></div>`]))+pager(p.total,15)}
async function users(){const p=await api('/admin/users?'+new URLSearchParams({q:states.q,page:states.pn}));return head('DIRECTORY / USERS','用户管理','查找玩家、核对账号状态并管理访问权限。')+filter('用户名或昵称')+table(['用户','角色','最后活跃','状态','操作'],p.items.map(x=>[esc(x.nickname)+'<br><small>@'+esc(x.username)+'</small>',x.role==='admin'?'管理员':'玩家',esc(dt(x.last_active)),badge(x.disabled?'已停用':'正常',x.disabled),x.role==='admin'?'受保护':`<div class="actions"><button data-toggleuser="${x.id}" data-enable="${x.disabled?1:0}">${x.disabled?'启用':'停用'}</button><button class="warn" data-deluser="${x.id}">删除</button></div>`]))+pager(p.total,20)}
let catalog=[],work;
async function library(){catalog=await api('/library');const rows=catalog.filter(x=>(x.slug+' '+x.title+' '+x.description).toLowerCase().includes(states.q.toLowerCase()));return head('CATALOG / RESOURCES','资源管理','维护玩家可见的资源说明，导入可核验的真实项目。','<button class="primary" id="import">＋ 导入项目</button>')+filter('资源名称、标识或说明')+table(['资源','固定版本','必需依赖','操作'],rows.map(x=>[esc(x.title)+'<br><small>'+esc(x.slug)+'</small>',esc(x.version),esc(x.required.join(' / ')||'未声明'),`<button data-editres="${esc(x.slug)}">维护说明</button>`]))}
let reports=[];
async function cases(){[reports,work]=await Promise.all([api('/admin/reports'),api('/admin/workspace')]);const list=reports.filter(r=>states.status==='all'||(states.status==='closed'?r.done:!r.done));return head('MODERATION / INBOX','举报工单','结合举报理由与原帖证据，记录人工处理结果。')+`<div class="tools"><label>状态 <select id="status">${[['all','全部'],['open','待处理'],['closed','已处理']].map(([k,v])=>`<option value="${k}" ${states.status===k?'selected':''}>${v}</option>`).join('')}</select></label></div>`+table(['工单','举报说明','举报人','状态','操作'],list.map(r=>['#'+r.id+'<br><small>帖子 #'+r.pid+'</small>',esc(short(r.reason)),esc(r.nickname),badge(r.done?'已处理':'待处理',!r.done),`<button data-case="${r.id}">核查工单</button>`]))}
async function words(){const items=await api('/admin/words');return head('POLICY / DICTIONARY','敏感词库','新增词条用于后续内容过滤。')+'<form id="word-form" class="tools"><input name="word" maxlength="30" required placeholder="输入新词条"><button class="primary">添加词条</button></form><section class="panel"><p class="muted">点击词条可移除</p><div class="words">'+items.map(w=>`<button data-word="${esc(w)}">${esc(w)}　×</button>`).join('')+'</div></section>'}
async function audit(){const items=await api('/admin/audit');return head('SYSTEM / AUDIT','操作日志','最近 100 次管理操作，按时间倒序排列。')+table(['时间','操作者','动作','对象 / 说明'],items.map(x=>[esc(dt(x.created_at)),esc(x.actor),esc(names[x.action]||x.action),esc(x.target)]))}
async function settings(){return head('STAFF / ACCOUNT','账号设置','更换当前管理员的登录密码。')+`<form id="pwd" class="panel" style="max-width:450px"><label>原密码</label><input required type="password" name="old_password" autocomplete="current-password"><label>新密码 · 8–72 位</label><input required type="password" name="new_password" minlength="8" maxlength="72" autocomplete="new-password"><p class="muted">更新后将退出所有该账号的登录会话。</p><button class="primary">保存新密码</button></form>`}
const aiPresets = {
  text: [
    ['DeepSeek', 'https://api.deepseek.com/chat/completions'],
    ['阿里云百炼（北京）', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'],
    ['OpenAI', 'https://api.openai.com/v1/chat/completions'],
  ],
  vision: [
    ['阿里云百炼（北京）', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'],
    ['OpenAI', 'https://api.openai.com/v1/chat/completions'],
  ],
};
const aiFeatures = {
  text: ['文本模型', '调配配方', '玩家对话改包、举报证据摘要'],
  vision: ['视觉模型', '图像识别', '玩家圈选截图后推荐相似 Mod'],
};
function modelCard(kind, cfg) {
  const [title, , usage] = aiFeatures[kind], presets = aiPresets[kind];
  const configured = cfg.enabled && cfg.has_key && cfg.url && cfg.model;
  const status = configured ? '已启用 · 可测试' : cfg.source === 'none' ? '尚未配置' : !cfg.enabled ? '已停用' : '配置不完整';
  const url = cfg.url || presets[0][1];
  const keyHelp = cfg.has_key ? '已有密钥 · 留空保留' : '填写服务商签发的 API Key';
  return `<form class="panel ai-channel" data-ai-form="${kind}" autocomplete="off">
    <div class="line"><div><h2>${title}</h2></div>${badge(status,!configured)}</div>
    <p class="ai-usage">${esc(usage)}</p><details class="ai-edit"><summary>编辑连接参数</summary><p class="ai-source">当前来源：${esc(({local:'本机设置',env:'环境变量',none:'未设置'})[cfg.source]||'未设置')}</p>
    <fieldset><legend>连接参数</legend>
    <label for="ai-${kind}-provider">服务商预设</label>
    <select id="ai-${kind}-provider" data-ai-provider>${presets.map(([n,v])=>`<option value="${esc(v)}" ${v===url?'selected':''}>${esc(n)}</option>`).join('')}<option value="" ${presets.some(p=>p[1]===url)?'':'selected'}>自定义兼容端点</option></select>
    <label for="ai-${kind}-url">请求地址</label><input id="ai-${kind}-url" type="url" name="url" required maxlength="512" value="${esc(url)}" spellcheck="false" placeholder="https://…/chat/completions">
    <label for="ai-${kind}-model">模型 ID</label><input id="ai-${kind}-model" name="model" required maxlength="160" value="${esc(cfg.model||'')}" placeholder="${kind==='vision'?'填写支持图片输入的模型 ID':'填写已开通的文本模型 ID'}" spellcheck="false">
    <label for="ai-${kind}-key">API 密钥</label><input id="ai-${kind}-key" type="password" name="key" autocomplete="new-password" placeholder="${keyHelp}" spellcheck="false">
    <label class="ai-switch"><input type="checkbox" name="enabled" ${cfg.enabled||cfg.source==='none'?'checked':''}>启用此通道</label>
    </fieldset>
    <p class="hint">模型 ID 应与服务商控制台一致。更改请求地址时须重新填写密钥。</p>
    <div class="actions"><button type="submit" class="primary">保存设置</button><button type="button" data-ai-test ${configured?'':'disabled'}>测试连接</button></div>
    <p class="ai-result" role="status" aria-live="polite"></p>
    ${cfg.source==='local'?'<button type="button" data-ai-reset class="link">移除本机设置</button>':''}
  </details></form>`;
}
async function aiPage() {
  const cfg = await api('/admin/ai');
  return head('SYSTEM / MODEL CONNECTIONS','AI 模型设置','此页设置社区默认模型及后台审核模型。玩家可在自己的 AI 工坊覆盖文本和视觉设置。')+
    
    '<div class="ai-channels">'+modelCard('text',cfg.text)+modelCard('vision',cfg.vision)+'</div>'+
    '<p class="hint">测试会向服务商发出一次请求，可能产生少量费用；不开启通道时对应功能仍可使用本地模式。</p>';
}
function bindAI(form) {
  const kind=form.dataset.aiForm, provider=form.querySelector('[data-ai-provider]');
  const fields=form.elements, test=form.querySelector('[data-ai-test]'), result=form.querySelector('.ai-result');
  const tell=(msg,bad=false)=>{result.classList.toggle('error',bad);result.textContent=msg};
  const originalUrl=fields.url.value.trim();
  const dirty=()=>{if(fields.url.value.trim()!==originalUrl)fields.key.required=true;else fields.key.required=false;test.disabled=true;tell('有未保存的修改。保存后可测试连接。')};
  const busy=(on)=>{form.querySelectorAll('fieldset,button').forEach(el=>el.disabled=on);form.setAttribute('aria-busy',String(on))};
  const replace=async()=>{
    const cfg=await api('/admin/ai');if(!form.isConnected)return;
    const t=document.createElement('template');t.innerHTML=modelCard(kind,cfg[kind]);const f=t.content.firstElementChild;
    f.querySelector('.ai-edit').open=true;form.replaceWith(f);bindAI(f);return f;
  };
  provider.onchange=()=>{if(provider.value)fields.url.value=provider.value;else fields.url.focus();dirty()};
  fields.url.addEventListener('input',()=>{provider.value=[...provider.options].some(o=>o.value===fields.url.value.trim())?fields.url.value.trim():''});
  form.oninput=dirty;
  form.onsubmit=async e=>{
    e.preventDefault();
    const data={url:fields.url.value.trim(),model:fields.model.value.trim(),key:fields.key.value.trim(),enabled:fields.enabled.checked};
    busy(true);tell('正在保存…');
    try{await api('/admin/ai/'+kind,'POST',data);fields.key.value='';const f=await replace();if(f){f.querySelector('.ai-result').textContent=data.enabled?'已保存。点击「测试连接」可验证模型和凭据。':'已保存，此通道已停用。';}}
    catch(err){busy(false);test.disabled=true;tell(err.message,true)}
  };
  test.onclick=async()=>{
    busy(true);tell('正在等待服务商响应…');
    try{const r=await api('/admin/ai/'+kind+'/test','POST');tell(r.message||'测试通过')}
    catch(err){tell(err.message,true)}
    finally{busy(false)}
  };
  const reset=form.querySelector('[data-ai-reset]');
  if(reset)reset.onclick=()=>confirm('移除本机设置','将清除该通道的本机覆盖及其密钥。如果服务器配置了环境变量，将恢复环境变量；否则回到本地模式。',async()=>{await api('/admin/ai/'+kind,'DELETE')});
}

const screens={ai:aiPage,dashboard,reports:cases,manage,users,library,words,audit,settings};
async function load(){const stamp=++paint,el=$('#content');if(!el)return;el.setAttribute('aria-busy','true');try{const content=await screens[states.page]();if(stamp!==paint||!el.isConnected)return;el.innerHTML=content;bind()}catch(e){if(stamp===paint&&el.isConnected){el.innerHTML='<p class="error">'+esc(e.message)+'</p><button id="retry">重新加载</button>';$('#retry').onclick=load}}finally{el.removeAttribute('aria-busy')}}
async function showPost(id){const x=await api('/posts/'+id);dlg('帖子 #'+id,`<article class="post"><b>${esc(x.nickname)}</b> · ${esc(dt(x.created_at))}<p class="note">${esc(x.content)}</p>${x.media.map(m=>{const url='/api/media/'+encodeURIComponent(m.id)+'?token='+encodeURIComponent(token());return m.kind==='video'?`<video controls preload="metadata" src="${url}"></video>`:`<img alt="原帖图片" src="${url}">`}).join('')}<p>${x.tags.map(t=>badge('# '+t)).join(' ')} · ${x.comment_count} 条评论</p></article>`)}
function safe(fn){return async e=>{try{await fn(e)}catch(err){if(modal.open&&$('#dialog-error'))$('#dialog-error').textContent=err.message;else toast(err.message)}}}
async function showCase(r){const p=await api('/posts/'+r.pid);const observed=r.stamp+'|'+p.updated_at;dlg('工单 #'+r.id,`<div class="muted">举报人 ${esc(r.nickname)}　·　${dt(r.stamp)}</div><h3 class="report-desc">举报理由</h3><div class="evidence">${esc(r.reason)}</div><h3 class="report-desc">原帖 #${r.pid}</h3><div class="evidence">${esc(p.content)}</div><button id="origin">查看完整帖子（${p.media.length} 个媒体）</button><hr><button id="summary">${work.model?'使用在线模型整理证据':'整理证据（本地）'}</button><p class="hint">${work.model?'会将举报理由和原帖文字提交给配置的模型。':'当前未配置模型。仅整理原帖和举报原文，不判断违规。'}</p><div id="recap"></div>${r.done?badge('已处理'):'<form id="decision"><label>人工处理决定</label><select name="action"><option value="keep">结案，不改变帖子可见性</option><option value="hide">下架原帖并结案</option></select><label>处理原因</label><textarea required name="note" maxlength="300" placeholder="说明判断依据，写入审计日志"></textarea><button class="primary">确认并记录</button></form>'}`);
 $('#origin').onclick=safe(async()=>{await showPost(r.pid);modal.insertAdjacentHTML('beforeend','<button id="backcase">返回工单</button>');$('#backcase').onclick=safe(()=>showCase(r))});
 $('#summary').onclick=safe(async e=>{const b=e.currentTarget;b.disabled=true;const box=$('#recap');try{const a=await api('/admin/reports/'+r.id+'/summary','POST');if(box.isConnected)box.innerHTML=badge(a.mode)+'<p>'+esc(a.summary)+'</p><p><b>待核查：</b>'+esc(a.check)+'</p><small>证据来源：举报 #'+r.id+' / 帖子 #'+r.pid+'</small>'}finally{b.disabled=false}});
 if($('#decision'))$('#decision').onsubmit=safe(async e=>{e.preventDefault();await api('/admin/reports/'+r.id+'/decision','POST',{...Object.fromEntries(new FormData(e.target)),observed});modal.close();toast('处理结果已记录');await load()})}
function bind(){document.querySelectorAll('[data-ai-form]').forEach(bindAI);const bindAll=(q,fn)=>document.querySelectorAll(q).forEach(b=>b.onclick=safe(()=>fn(b)));
 bindAll('[data-to]',b=>go(b.dataset.to));bindAll('[data-page]',b=>{states.pn+=Number(b.dataset.page);load()});if($('#filter')){$('#filter').onsubmit=e=>{e.preventDefault();states.q=e.target.q.value;states.pn=1;load()};$('#reset').onclick=()=>{states.q='';states.pn=1;load()}}
 bindAll('[data-detail]',b=>showPost(b.dataset.detail));bindAll('[data-case]',b=>showCase(reports.find(r=>r.id===Number(b.dataset.case))));if($('#status'))$('#status').onchange=e=>{states.status=e.target.value;load()};
 for(const [name,kind,end] of [['togglepost','帖子','/admin/posts/'],['toggleuser','账号','/admin/users/']])bindAll('[data-'+name+']',b=>{const id=b.dataset[name],on=b.dataset.enable==='1';confirm(b.textContent+kind,'对象：'+kind+' #'+id,()=>api(end+id+'/status','PUT',{enabled:on}))});
 for(const [name,kind,end] of [['delpost','帖子','/posts/'],['deluser','用户','/admin/users/']])bindAll('[data-'+name+']',b=>confirm('删除'+kind,kind+' #'+b.dataset[name]+' 将永久删除，关联记录也会移除。',()=>api(end+b.dataset[name],'DELETE')));
 bindAll('[data-word]',b=>confirm('移除词条',b.dataset.word,()=>api('/admin/words?word='+encodeURIComponent(b.dataset.word),'DELETE')));
 if($('#word-form'))$('#word-form').onsubmit=safe(async e=>{e.preventDefault();await api('/admin/words','POST',{word:e.target.word.value});await load()});
 if($('#pwd'))$('#pwd').onsubmit=safe(async e=>{e.preventDefault();await api('/auth/password','PUT',Object.fromEntries(new FormData(e.target)));clearSession();login();toast('密码已更新，请重新登录')});
 bindAll('[data-editres]',b=>{const v=catalog.find(x=>x.slug===b.dataset.editres);dlg(v.title,`<p>固定版本：${esc(v.version)}　<a rel="noopener" href="${esc(v.source)}" target="_blank">上游发布页 ↗</a></p><form id="desc"><label>玩家可见的资源说明</label><textarea name="text" maxlength="800" rows="4" required>${esc(v.description)}</textarea><button class="primary">保存到资源库</button></form>`);$('#desc').onsubmit=safe(async e=>{e.preventDefault();await api('/admin/resources/'+encodeURIComponent(v.slug)+'/description','PUT',{text:e.target.text.value});modal.close();toast('已同步到玩家资源库');await load()})});
 if($('#import'))$('#import').onclick=()=>{dlg('导入 Modrinth 资源','<form id="lookup"><label>Mod 项目链接或标识</label><input name="link" required placeholder="https://modrinth.com/mod/lithium"><button>预览</button></form><div id="preview"></div>');$('#lookup').onsubmit=safe(async e=>{e.preventDefault();const src=e.target.link.value.trim(),box=$('#preview');box.textContent='正在查询真实发布文件…';const v=await api('/library/preview','POST',{link:src});box.innerHTML='<h3>'+esc(v.title)+'</h3><p>'+esc(v.version)+' · Fabric 1.20.1</p><p>'+esc(v.description)+'</p><button class="primary" id="commit">确认导入</button>';$('#commit').onclick=safe(async()=>{await api('/library/import','POST',{link:src});modal.close();toast('已写入资源库');await load()})})}}
try{if(!token())throw Error();states.user=await api('/auth/me');if(states.user.role!=='admin')throw Error();go(location.hash.slice(1)||'dashboard')}catch{clearSession();login()}

