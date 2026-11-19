const escape = value => String(value ?? '').replace(/[&<>"']/g, c =>
  ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'})[c]);
const deepseek = ['DeepSeek', 'https://api.deepseek.com/chat/completions'];
const bailian = ['阿里云百炼（北京）', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'];
const openai = ['OpenAI', 'https://api.openai.com/v1/chat/completions'];
const channels = {
  text: {name:'文本模型', info:'用于你的对话改包。模型需支持 JSON 输出。', presets:[deepseek,bailian,openai]},
  vision: {name:'视觉模型', info:'用于你的截图圈选检索。请选择支持图片输入的模型。', presets:[bailian,openai]}
};
const own = c => c.has_personal || c.source === 'personal';

export function modeLabel(channel){
  return own(channel) ? '我的配置' : '社区默认';
}
function fragment(html) {
  const template = document.createElement('template');
  template.innerHTML = html.trim();
  return template.content.firstElementChild;
}
function tell(form, text, error=false){
  const msg = form.querySelector('[data-model-message]');
  msg.classList.toggle('error', error);
  msg.textContent = text;
}
function savedSummary(cfg) {
  const prefix = modeLabel(cfg);
  return cfg.enabled ? prefix + ' · ' + cfg.model : prefix + ' · 本地模式';
}

function formMarkup(kind, cfg) {
  const {presets, info} = channels[kind];
  const personal = own(cfg), hasKey = personal && cfg.has_key;
  const url = personal && cfg.url ? cfg.url : presets[0][1];
  const id = 'personal-'+kind+'-';
  return `<form data-personal-form="${kind}" autocomplete="off" class="model-form">
    <div class="model-mode"><span>${escape(savedSummary(cfg))}</span></div>
    <p class="muted">${escape(info)}</p>
    <fieldset aria-label="模型连接">
      <label for="${id}provider">服务商</label>
      <select id="${id}provider" data-model-provider>
        ${presets.map(([name,endpoint])=>`<option value="${escape(endpoint)}" ${url===endpoint?'selected':''}>${escape(name)}</option>`).join('')}
        <option value="" ${presets.some(x=>x[1]===url)?'':'selected'}>手动填写受支持的地址</option>
      </select>

      <label for="${id}model">模型 ID</label>
      <input id="${id}model" name="model" value="${escape(personal?cfg.model:'')}" maxlength="160" spellcheck="false" placeholder="填写你的服务商账户中已开通的模型 ID">
      <label for="${id}key">我的 API Key</label>
      <input type="password" id="${id}key" name="key" autocomplete="new-password" maxlength="4096" spellcheck="false" placeholder="${hasKey?'已保存个人密钥，留空保留':'填写你自己的 API Key'}">
      <small>密钥由服务端保存，不会回显。</small>
      <details class="model-endpoint" ${presets.some(x=>x[1]===url)?'':'open'}><summary>自定义请求地址</summary><label for="${id}url">HTTPS 接口</label><input type="url" required id="${id}url" name="url" value="${escape(url)}" maxlength="500" spellcheck="false" placeholder="https://…/chat/completions"></details>
      <label class="model-switch"><input type="checkbox" name="enabled" ${!personal||cfg.enabled?'checked':''}>启用这个个人模型</label>
      <small>关闭后使用本地模式。</small>
    </fieldset>
    <div class="model-actions"><button type="submit">保存我的设置</button>
      <button class="ghost" type="button" data-model-test ${personal&&cfg.enabled&&hasKey?'':'disabled'}>测试我的连接</button></div>
    <small>测试将调用一次服务商接口，可能产生费用。</small>
    <p role="status" aria-live="polite" data-model-message></p>
    ${personal?`<button class="ghost small" type="button" data-model-reset>恢复社区默认</button>
      <div class="model-reset-confirm" data-reset-prompt hidden>
        <p>删除该通道的个人连接和密钥，改为使用社区默认？</p>
        <button type="button" data-confirm-reset>确认恢复</button>
        <button type="button" class="ghost" data-cancel-reset>保留我的设置</button>
      </div>`:''}
  </form>`;
}

export function openPersonalSettings({api, config, onUpdate, initial='text', returnFocus}){
  // A preference form is transient. Nothing in it is sent until the user chooses Save/Test.
  const dialog = fragment(`<dialog id="personal-model-dialog" class="personal-models" aria-labelledby="my-model-title">
    <header class="modal-head"><h2 id="my-model-title">我的模型设置</h2><button type="button" data-close aria-label="关闭">×</button></header>
    <p class="model-intro">仅影响你的账号。未设置的通道沿用社区默认。</p>
    <nav class="model-tabs" aria-label="选择模型通道">
      ${Object.entries(channels).map(([k,c])=>`<button type="button" data-model-tab="${k}">${c.name}</button>`).join('')}
    </nav>
    <div class="model-form-host"></div>
  </dialog>`);
  document.body.appendChild(dialog);
  const host=dialog.querySelector('.model-form-host');
  const forms={};
  let current=initial;
  function select(k) {
    current=k;
    for(const [key,form] of Object.entries(forms))form.hidden=key!==k;
    dialog.querySelectorAll('[data-model-tab]').forEach(b=>b.setAttribute('aria-pressed', String(b.dataset.modelTab===k)));
  }
  function initForm(kind, cfg) {
    const form=fragment(formMarkup(kind,cfg));
    if(forms[kind]) forms[kind].replaceWith(form); else host.appendChild(form);
    forms[kind]=form;
    const f=form.elements, selectProvider=form.querySelector('[data-model-provider]'), test=form.querySelector('[data-model-test]');
    const hasKey=Boolean(own(cfg)&&cfg.has_key), original=f.url.value;
    const sync=()=>{
      f.model.required=f.enabled.checked;
      f.key.required=f.enabled.checked && (!hasKey || f.url.value.trim()!==original);
    };
    f.url.addEventListener('invalid',()=>{form.querySelector('details').open=true});
    sync();
    selectProvider.onchange=()=>{
      if(selectProvider.value) f.url.value=selectProvider.value; else {form.querySelector("details").open=true;f.url.focus()}
      form.dispatchEvent(new Event('input'));
    };
    f.url.oninput=()=>{selectProvider.value=channels[kind].presets.find(x=>x[1]===f.url.value.trim())?.[1]||''};
    form.oninput=()=>{form.dataset.dirty='1';sync();test.disabled=true;tell(form,'有未保存的修改。测试使用已保存的设置。')};
    function lock(yes) {
      form.setAttribute('aria-busy',String(yes));
      form.querySelector('fieldset').disabled=yes;
      form.querySelectorAll('button').forEach(b=>b.disabled=yes);
      if(!yes)test.disabled=Boolean(form.dataset.dirty)||!own(cfg)||!cfg.enabled||!hasKey;
    }
    async function changed(reply,message) {
      let next;
      if(reply && typeof reply.enabled==='boolean' && ('has_personal' in reply||'source' in reply))next=reply;
      else next=(await api('/me/ai'))[kind];
      onUpdate(kind,next);
      if(!dialog.isConnected)return;
      const fresh=initForm(kind,next);
      select(current);
      tell(fresh,message);
    }
    const path='/me/ai/'+kind;
    form.onsubmit=async e=>{
      e.preventDefault();
      const payload={url:f.url.value.trim(),model:f.model.value.trim(),key:f.key.value.trim(),enabled:f.enabled.checked};
      lock(true);tell(form,'正在保存个人连接…');
      try {
        const reply=await api(path,{method:'POST',body:payload});
        f.key.value='';
        await changed(reply,payload.enabled?'已保存。现在可测试自己的连接。':'已保存，当前账号的这个通道已切到本地模式。');
      } catch(err){lock(false);tell(form,err.message,true)}
    };
    test.onclick=async()=>{
      lock(true);tell(form,'正在测试已保存的个人连接…');
      try{const reply=await api(path+'/test',{method:'POST'});tell(form,reply.message||'测试通过。')}
      catch(err){tell(form,err.message,true)}
      finally{lock(false)}
    };
    const reset=form.querySelector('[data-model-reset]');
    if(reset){
      const prompt=form.querySelector('[data-reset-prompt]');
      reset.onclick=()=>{prompt.hidden=false;form.querySelector('[data-confirm-reset]').focus()};
      form.querySelector('[data-cancel-reset]').onclick=()=>{prompt.hidden=true;reset.focus()};
      form.querySelector('[data-confirm-reset]').onclick=async()=>{
        lock(true);tell(form,'正在恢复社区默认…');
        try{const reply=await api(path,{method:'DELETE'});await changed(reply,'此通道已恢复社区默认。')}
        catch(err){lock(false);tell(form,err.message,true)}
      };
    }
    return form;
  }
  for(const k of Object.keys(channels))initForm(k,config[k]);
  dialog.querySelectorAll('[data-model-tab]').forEach(b=>b.onclick=()=>select(b.dataset.modelTab));
  dialog.querySelector('[data-close]').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>{
    dialog.querySelectorAll('input[type=password]').forEach(el=>el.value='');
    dialog.remove();
    if(returnFocus?.isConnected)returnFocus.focus();
  },{once:true});
  select(initial);
  dialog.showModal();
}
