import {modeLabel, openPersonalSettings} from './personal-models.js';

const tools = [
  {kind:'text', view:'bench', name:'对话改整合包', action:'打开工作台', art:'tree.png', hint:'告诉助手想加什么、想留下什么，再一起检查改动。'},
  {kind:'vision', view:'vision', name:'截图找玩法', action:'选择截图', art:'jei-scene.jpg', hint:'圈出截图里喜欢的细节，寻找能实现相似效果的 Mod。'}
];

export async function workshop({api,navigate}) {
  const root=document.querySelector('#content');
  const config=await api('/me/ai');
  if(!root.isConnected||!document.querySelector('[data-view="ai"][aria-current="page"]'))return;
  root.innerHTML=`<div class="page-head ai-heading">
    <div><h1>AI 工坊</h1><p>从一个想法，或一张截图开始。</p></div>
    <button class="ghost" id="my-model-settings">我的模型设置</button>
  </div>
  <div class="ai-tools">${tools.map(t=>`<article class="ai-tool">
    <div class="ai-tool-art" aria-hidden="true"><img src="/static/images/${t.art}" alt=""></div>
    <div class="ai-tool-body"><h2>${t.name}</h2><p>${t.hint}</p>
    <div class="ai-tool-bottom"><button data-use="${t.view}">${t.action} →</button><small class="ai-status" data-source="${t.kind}"></small></div></div>
  </article>`).join('')}</div>`;
  function paint(){
    for(const t of tools){
      const slot=config[t.kind], node=root.querySelector('[data-source="'+t.kind+'"]');
      node.classList.toggle('online',slot.enabled);
      node.textContent=slot.enabled ? slot.model : '本地模式';
      node.title=modeLabel(slot)+' · '+(slot.enabled?'已启用，连接情况可在设置中测试':'未调用在线模型');
    }
  }
  root.querySelectorAll('[data-use]').forEach(b=>b.onclick=()=>navigate(b.dataset.use));
  root.querySelector('#my-model-settings').onclick=e=>openPersonalSettings({
    api,config,initial:'text',returnFocus:e.currentTarget,
    onUpdate:(kind,next)=>{config[kind]=next;if(root.isConnected&&root.querySelector('.ai-tools'))paint()}
  });
  paint();
}
