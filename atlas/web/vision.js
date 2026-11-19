const safe=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export async function visionView({api,navigate,toast}){
 const root=document.querySelector('#content'),status=await api('/vision/status');if(!root.isConnected)return;
 root.innerHTML=`<div class="page-head"><div><h1>截图找玩法</h1><p>上传截图，在画面上拖动，圈出想复现的效果。</p></div></div>
 <div class="lens-grid">
   <section class="panel lens-edit"><header><b id="lens-title">参考截图</b><label class="upload">选择图片<input type="file" id="lens-file" aria-label="选择图片" accept="image/png,image/jpeg,image/webp"></label></header>
     <div class="canvaswrap"><canvas id="lens-canvas" aria-label="拖动框选截图区域"></canvas></div>
     <div class="lens-controls"><span id="lens-size"></span><button class="small ghost" id="full">使用全图</button></div>
     <details class="lens-samples"><summary>换张样图</summary><div class="sample-row"><button data-sample="jei">配方界面</button><button data-sample="sodium">水下渲染</button></div></details>
   </section>
   <section class="panel lens-side"><h2>想找什么？</h2><label for="lens-q">补充描述（选填）</label><textarea id="lens-q" rows="3" maxlength="240" placeholder="比如：想在右侧看到合成配方"></textarea>
     <details class="lens-method"><summary id="lens-method-label">检索方式 · 本地图库</summary>
       <label class="mode"><input type="checkbox" id="lens-online" ${status.online?'':'disabled'}> 使用在线视觉模型</label>
       <p class="hint">${status.online?'开启并点击查找后，仅选区和描述会发送给已配置的模型。':'未启用视觉模型，当前只比对本地图库和描述。'} <a href="#ai" class="ai-inline">模型设置</a></p></details>
     <button id="lens-go">查找候选 Mod</button><div id="matches" aria-live="polite"></div>
   </section></div>`;
 const $=s=>root.querySelector(s),cv=$('#lens-canvas'),ctx=cv.getContext('2d');let file,im,box=[0,0,1,1],start=null,epoch=0,display=0;
 function paint(){ctx.drawImage(im,0,0,cv.width,cv.height);let [x,y,r,b]=box;const w=cv.width,h=cv.height;ctx.fillStyle='#0d181c80';ctx.beginPath();ctx.rect(0,0,w,h);ctx.rect(x*w,y*h,(r-x)*w,(b-y)*h);ctx.fill('evenodd');ctx.strokeStyle='#d8ff83';ctx.lineWidth=3;ctx.strokeRect(x*w,y*h,(r-x)*w,(b-y)*h);$('#lens-size').textContent=Math.round((r-x)*im.naturalWidth)+' × '+Math.round((b-y)*im.naturalHeight)+' px';}
 async function load(blob){const id=++epoch;++display;$('#matches').textContent='';if(!blob||blob.size>8*1024*1024){toast('请使用 8 MB 以内的图片');return}const link=URL.createObjectURL(blob);try{const next=new Image();next.src=link;await next.decode();if(id!==epoch)return;im=next;file=blob;box=[0,0,1,1];cv.width=Math.min(im.naturalWidth,1100);cv.height=Math.max(1,Math.round(cv.width*im.naturalHeight/im.naturalWidth));paint()}catch{toast('无法读取图片，请选择 JPG、PNG 或 WebP')}finally{URL.revokeObjectURL(link)}}
 async function sample(k){try{const r=await fetch('/static/images/'+k+'-scene.jpg');if(!r.ok)throw Error();const blob=await r.blob();await load(blob);if(file===blob)$('#lens-title').textContent='参考截图'}catch{toast('样图读取失败')}}
 function point(e){const a=cv.getBoundingClientRect();return [Math.min(1,Math.max(0,(e.clientX-a.left)/a.width)),Math.min(1,Math.max(0,(e.clientY-a.top)/a.height))]}
 cv.onpointerdown=e=>{if(!im)return;start=point(e);cv.setPointerCapture(e.pointerId)};
 cv.onpointermove=e=>{if(!start)return;const [x,y]=point(e);box=[Math.min(x,start[0]),Math.min(y,start[1]),Math.max(x,start[0]),Math.max(y,start[1])];paint()};
 cv.onpointerup=cv.onpointercancel=()=>{if(!start)return;start=null;if((box[2]-box[0])*im.naturalWidth<6||(box[3]-box[1])*im.naturalHeight<6)box=[0,0,1,1];paint();++display;$('#matches').textContent=''};
 $('#lens-online').onchange=e=>{$('#lens-method-label').textContent='检索方式 · '+(e.target.checked?'在线模型':'本地图库')};
 $('#full').onclick=()=>{if(im){box=[0,0,1,1];paint();++display;$('#matches').textContent=''}};$('#lens-file').onchange=async e=>{const f=e.target.files[0];if(!f)return;await load(f);if(file===f)$('#lens-title').textContent='我的截图'};root.querySelectorAll('[data-sample]').forEach(b=>b.onclick=()=>sample(b.dataset.sample));
 $('#lens-go').onclick=async e=>{if(!file)return;const btn=e.currentTarget,dst=$('#matches'),id=++display;btn.disabled=true;dst.textContent='正在比对所选画面…';try{const form=new FormData();form.append('image',file,'screenshot');form.append('box',JSON.stringify(box));form.append('query',$('#lens-q').value);form.append('online',$('#lens-online').checked);const out=await api('/vision/search',{method:'POST',body:form});if(id!==display||!dst.isConnected)return;dst.innerHTML=`<div class="result-head"><b>${safe(out.mode)}</b><small>裁剪 ${out.crop.join(' × ')}</small></div>${out.mode==='在线视觉模型'?'<p>'+safe(out.observation)+'</p>':''}`+out.matches.map(v=>`<article><b>${safe(v.title)}</b><p>${safe(v.reason)}</p><a target="_blank" rel="noopener" href="${safe(v.source)}">核对版本 ↗</a> <button class="small" data-lens-add="${safe(v.slug)}">加入草稿</button></article>`).join('')+(out.matches.length?'':'<p>资源库没有足够相似的项目。试试缩小选区或补充文字。</p>');dst.querySelectorAll('[data-lens-add]').forEach(b=>b.onclick=async()=>{try{await api('/pack/action',{method:'POST',body:{op:'add',value:b.dataset.lensAdd}});navigate('bench')}catch(err){toast(err.message)}})}catch(err){if(id===display)dst.textContent=err.message}finally{btn.disabled=false}};
 await sample('jei');
}
