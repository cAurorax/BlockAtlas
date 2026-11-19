import {avatarDock,bindAvatar} from './avatar-dock.js';
import {workshop} from './ai-workshop.js';
import {mark,sidebar,bindRail,closeRail} from './shell.js';
import {visionView} from './vision.js';
import {packCard,packEditor} from './pack-posts.js';
const $ = (selector, root = document) => root.querySelector(selector);
const app = $("#app");
const modal = $("#modal");
const state = {
  user: null,
  view: "feed",
  page: 1,
  filters: {},
  posts: [],
  reply: null,
};
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const date = (value) =>
  new Date(value).toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
const mediaSrc=(url)=>adminPage?url+"?token="+encodeURIComponent(sessionStorage.getItem("atlas-admin")||""):url;
const visibility = { public: "公开", friends: "好友可见", private: "仅自己" };
const query = (values) =>
  new URLSearchParams(
    Object.entries(values).filter(
      ([, v]) => v !== "" && v !== null && v !== undefined,
    ),
  );
let toastTimer;
function toast(message) {
  $("#toast").textContent = message;
  $("#toast").style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($("#toast").style.display = "none"), 3200);
}
async function api(path, options = {}) {
  const config = {
    ...options,
    credentials: adminPage ? "omit" : "same-origin",
    headers: { ...(adminPage ? {Authorization:"Bearer "+(sessionStorage.getItem("atlas-admin")||"")} : {}), ...options.headers },
  };
  if (options.body && !(options.body instanceof FormData)) {
    config.headers["Content-Type"] = "application/json";
    config.body = JSON.stringify(options.body);
  }
  const response = await fetch("/api" + path, config);
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401 && state.user) {
      state.user = null;
      modal.close();
      loginView();
    }
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "输入格式有误，请检查长度、格式和必填项",
    );
  }
  return result;
}
const pages=new Set(['feed','friends','friendsFeed','mine','library','vision','ai','bench','settings']);
function landing(){
  const hash=location.hash.slice(1),match=/^(player|post)\/([1-9]\d*)$/.exec(hash);
  if(match){state.entity=Number(match[2]);return match[1]}
  return pages.has(hash)?hash:'feed';
}
window.addEventListener('hashchange',()=>{if(state.user&&!adminPage)navigate(landing(),false)});
const adminPage = location.pathname === "/admin";
const brand =
  '<div class="brand">'+mark+'<div>方块工坊<small>BLOCK ATLAS</small></div></div>';
function loginView(register = false) {
  closeRail();
  app.innerHTML = `<div class="login"><section class="login-art">${brand}<h1>下一站，<br>你的世界。</h1><p>发现玩法，与朋友分享你的 Minecraft 世界。</p><div class="art-circles"></div></section><section class="login-form"><div><h2>${register ? "注册玩家账号" : "欢迎回来"}</h2><p class="sub">${register ? "创建账号，与朋友分享存档里的故事" : "登录方块工坊，看看今天有什么新鲜事"}</p><form id="login-form"><label for="username">用户名</label><input id="username" name="username" autocomplete="username" placeholder="3–30 位字母、数字或下划线" required minlength="3" maxlength="30" pattern="[A-Za-z0-9_]+">${register ? '<label for="nickname">昵称</label><input id="nickname" name="nickname" required maxlength="24" placeholder="朋友们怎么称呼你">' : ""}<label for="password">密码</label><input id="password" name="password" type="password" autocomplete="${register ? "new-password" : "current-password"}" placeholder="8–72 位密码" required minlength="8" maxlength="72"><div id="login-error"></div><button type="submit">${register ? "注册账号" : "登 录"}　→</button></form><div class="login-switch">${register ? "已有账号？" : "还没有账号？"}<button id="switch-login">${register ? "返回登录" : "立即注册"}</button></div><div class="demo">本地演示账号 <button data-demo="alice">普通用户</button><button data-demo="admin">管理员</button><br>用户 alice / Alice123!　管理员 admin / Admin123!</div></div></section></div>`;
  if (adminPage){$(".login-art h1").textContent="工坊管理台";$(".login-art p").textContent="用户、内容审核与社区运营";$(".login-switch").hidden=true;}
  $(".demo").innerHTML='<details class="demo-options"><summary>使用演示账号</summary><div><button type="button" data-demo="alice">北岸松林</button> <button type="button" data-demo="bob">林地巡游者</button></div></details>';
  $("#switch-login").onclick = () => loginView(!register);
  document.querySelectorAll("[data-demo]").forEach(
    (button) =>
      (button.onclick = () => {
        $("#username").value = button.dataset.demo;
        $("#password").value =
          button.dataset.demo === "admin" ? "Admin123!" : button.dataset.demo==="bob"?"Bob12345!":"Alice123!";
      }),
  );
  $("#login-form").onsubmit = async (event) => {
    event.preventDefault();
    const button = $("button[type=submit]", event.target);
    button.disabled = true;
    try {
      const data = Object.fromEntries(new FormData(event.target));
      if (register) await api("/auth/register", { method: "POST", body: data });
      const result = await api("/auth/login", {
        method: "POST",
        body: { username: data.username, password: data.password },
      });
      if(adminPage)sessionStorage.setItem("atlas-admin",result.token);
      if ((result.user.role==="admin")!==adminPage){await api("/auth/logout",{method:"POST"});throw Error(adminPage?"请使用管理员账号":"管理员请从 /admin 登录");}
      state.user = result.user;
      state.view = result.user.role === "admin" ? "dashboard" : landing();
      state.filters = {};
      state.page = 1;
      shell();
      await renderView();
    } catch (error) {
      $("#login-error").innerHTML =
        `<p class="error">${esc(error.message)}</p>`;
    } finally {
      button.disabled = false;
    }
  };
}
function shell() {
  closeRail();
  const isAdmin = state.user.role === "admin";
  app.innerHTML = `<aside class="sidebar" aria-label="工坊导航"><div class="rail-head">${brand}<button id="rail-toggle" type="button" aria-label="展开导航" aria-controls="rail-nav" aria-expanded="false"><span aria-hidden="true"></span></button></div><nav class="nav" id="rail-nav" aria-label="主导航">${sidebar(state.view)}</nav>${avatarDock(state.user,esc)}</aside><button type="button" id="rail-scrim" tabindex="-1" aria-label="收起导航面板"></button><main tabindex="-1"><div id="content"></div></main>`;
  document
    .querySelectorAll("[data-view]")
    .forEach(
      (button) => (button.onclick = () => navigate(button.dataset.view)),
    );
  bindRail();
  bindAvatar(navigate,async()=>{try{await api("/auth/logout",{method:"POST"});state.user=null;loginView()}catch(e){toast(e.message)}});
}
function friendsNav(view){
  return `<nav aria-label="好友分区" class="friends-sections"><button data-section="friends" ${view==='friends'?'aria-current="page"':''}>好友与申请</button><button data-section="friendsFeed" ${view==='friendsFeed'?'aria-current="page"':''}>好友动态</button></nav>`;
}
document.addEventListener('click',e=>{const b=e.target.closest('#content [data-section]');if(b&&b.dataset.section!==state.view)navigate(b.dataset.section)});
async function navigate(view,update=true) {
  closeRail();
  if(update)history.replaceState(null,"",pages.has(view)&&view!=="feed"?"#"+view:location.pathname);
  state.view = view;
  state.page = 1;
  state.filters = {};
  shell();
  document.querySelector("#app > main")?.focus({preventScroll:true});
  window.scrollTo(0,0);
  await renderView();
}
function head(title, description, action = "") {
  return `<div class="page-head"><div><h1>${title}</h1><p>${description}</p></div>${action}</div>`;
}
async function renderView() {
  const target = $("#content");
  if (!target) return;
  target.innerHTML = '<div class="loading">正在加载工坊数据…</div>';
  const titles = {
    player:"玩家主页",post:"帖子详情",ai:"AI 工坊",vision:"截图找玩法",reports:"举报处理",library:"Mod 资源库",bench:"整合包工作台",feed: "玩家广场",
    mine: "我的帖子",
    friendsFeed: "好友动态",
    friends: "我的好友",
    settings: "账号设置",
    dashboard: "数据概览",
    manage: "内容管理",
    users: "用户管理",
    words: "敏感词管理",
    audit: "操作日志",
  };
  document.title=(titles[state.view]||"玩家端")+" · 方块工坊";
  try {
    await {
      player:playerView,post:singlePost,ai:()=>workshop({api,navigate}),vision:()=>visionView({api,navigate,toast}),reports:reportsView,library:libraryView,bench:benchView, feed: feedView,
      mine: feedView,
      friendsFeed: feedView,
      friends: friendsView,
      settings: settingsView,
      dashboard: dashboardView,
      manage: manageView,
      users: usersView,
      words: wordsView,
      audit: auditView,
    }[state.view]();
    if(target.isConnected){
      if(state.view==='friends'||state.view==='friendsFeed'){target.querySelector('.page-head')?.insertAdjacentHTML('afterend',friendsNav(state.view));}
    }
    if(target.isConnected)target.dataset.arrive="";
  } catch (error) {
    if (state.user && $("#content"))
      $("#content").innerHTML =
        `<div class="empty">${esc(error.message)}<br><button id="retry">重新加载</button></div>`;
    if ($("#retry")) $("#retry").onclick = renderView;
  }
}
function filterBar() {
  return `<form id="filter" class="filter"><input name="q" aria-label="搜索文字" placeholder="⌕  搜索动态文字" value="${esc(state.filters.q || "")}"><input name="tag" aria-label="标签" placeholder="标签" value="${esc(state.filters.tag || "")}"><input type="date" name="start" aria-label="开始日期" value="${esc(state.filters.start || "")}"><input type="date" name="end" aria-label="结束日期" value="${esc(state.filters.end || "")}"><button type="submit">筛选</button><button type="button" id="reset-filter" class="ghost">重置</button></form>`;
}
function bindFilter() {
  $("#filter").onsubmit = (event) => {
    event.preventDefault();
    state.filters = Object.fromEntries(new FormData(event.target));
    state.page = 1;
    renderView();
  };
  $("#reset-filter").onclick = () => {
    state.filters = {};
    state.page = 1;
    renderView();
  };
}
function pager(total, size = 12) {
  const pages = Math.max(1, Math.ceil(total / size));
  return `<div class="pagination"><button class="small ghost" id="previous" ${state.page <= 1 ? "disabled" : ""}>上一页</button><small>${state.page} / ${pages} 页 · 共 ${total} 条</small><button class="small ghost" id="next" ${state.page >= pages ? "disabled" : ""}>下一页</button></div>`;
}
function bindPager() {
  $("#previous").onclick = () => {
    state.page--;
    renderView();
  };
  $("#next").onclick = () => {
    state.page++;
    renderView();
  };
}
function card(post,detail=false) {
  const own=post.user_id===state.user.id;
  const controls=own?`<button data-edit="${post.id}">编辑帖子</button><button data-delete="${post.id}">删除帖子</button>`:`<button data-report="${post.id}">举报帖子</button>`;
  const lines=post.content.split("\n"), title=lines.shift()||"",body=lines.join("\n").trim(), split=title.length<=70;
  const titleText=esc((split?title:post.content)||"查看媒体帖");
  const titleMarkup=detail?titleText:`<a href="#post/${post.id}" class="post-open">${titleText}</a>`;
  const tag=post.tags.map(t=>`<span>#${esc(t)}</span>`).join(" ");
  const media=post.media.map(m=>m.kind==="video"?`<video controls playsinline preload="metadata" ${post.id===1&&post.mod_slug==="fallingtree"?'poster="/static/images/tree.png"':""} src="${mediaSrc(m.url)}"></video>`:`<img src="${mediaSrc(m.url)}" alt="${esc(post.nickname)}的实机截图" loading="lazy" data-photo="${mediaSrc(m.url)}">`).join("");
  const extras=post.mod_slug?`<div class="post-attachment"><button data-jump="${post.effect_second}">${esc(post.mod_slug)}${post.media.some(x=>x.kind==='video')?' · '+post.effect_second+'s':''}</button><button data-copy="${esc(post.mod_slug)}" title="加入整合包草稿">＋ 加入草稿</button></div>`:"";
  const pack=packCard(post);
  return `<article class="post journal-card"><div class="post-head"><a class="avatar author-face" href="#player/${post.user_id}" aria-label="查看${esc(post.nickname)}的主页"><img src="/static/images/player-${post.user_id%3}.png" alt=""></a><div class="author"><a class="author-link" href="#player/${post.user_id}"><strong>${esc(post.nickname)}</strong></a><small>${date(post.created_at)}${post.visibility==='public'?'':' · '+visibility[post.visibility]}</small></div>${post.hidden?'<span class="badge">已下架</span>':''}<details class="post-options"><summary aria-label="更多帖子操作" title="更多帖子操作">···</summary><div>${controls}</div></details></div>
    ${media?`<div class="media-grid ${post.media.length===1?'one':''}">${media}</div>`:''}
    <div class="journal-copy">${split?`<h3 class="post-text">${titleMarkup}</h3>${body?`<p>${esc(body)}</p>`:''}`:`<p class="post-text">${titleMarkup}</p>`}${tag?`<div class="journal-tags">${tag}</div>`:''}</div>
    ${pack||extras?`<details class="post-resources"><summary>关联玩法${post.pack?'与整合包':''}</summary><div>${extras}${pack}</div></details>`:''}
    <div class="post-footer"><span>${post.rating_count?'★ '+post.rating_avg.toFixed(1)+' <small>('+post.rating_count+')</small>':'暂无评分'}</span>${!own&&!post.hidden?`<select aria-label="给动态评分" data-rate="${post.id}"><option value="">评分</option>${[1,2,3,4,5].map(n=>`<option value="${n}" ${post.my_rating===n?'selected':''}>${n} 星</option>`).join('')}</select>`:''}<button data-comments="${post.id}">评论 ${post.comment_count}</button></div></article>`;
}
const relationLabels={none:"＋ 申请好友",outgoing:"已申请 · 等待确认",incoming:"接受好友申请",accepted:"已是好友",self:"这是你自己"};
function socialBack(fallback){const b=$("#social-back");b.onclick=()=>{if(history.state?.atlasFrom)history.back();else navigate(fallback)}}
document.addEventListener('click',e=>{
  const link=e.target.closest('a[href^="#player/"],a[href^="#post/"]');
  if(!link||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||e.defaultPrevented)return;
  e.preventDefault();if(location.hash===link.hash)return;
  history.pushState({atlasFrom:true},'',link.hash);navigate(landing(),false);
});
async function playerView(){
  const target=$("#content"),uid=state.entity;
  const [p,posts]=await Promise.all([api('/players/'+uid),api('/posts?author_id='+uid+'&page='+state.page)]);
  if(!target.isConnected)return;state.posts=posts.items;
  const canAct=p.relationship==='none'||p.relationship==='incoming';
  target.innerHTML=`<button class="identity-back" id="social-back">‹ 返回</button><header class="player-banner"><img src="/static/images/player-${uid%3}.png" alt=""><div><h1>${esc(p.nickname)}</h1><small>@${esc(p.username)}</small></div>${canAct?`<button id="player-request">${relationLabels[p.relationship]}</button>`:`<span class="relationship">${relationLabels[p.relationship]}</span>`}</header>
    <div class="journal-bar"><h2>发布的动态 <small>${posts.total}</small></h2></div><div class="journal-stream">${posts.items.map(x=>card(x)).join('')||'<p class="empty">暂时没有可查看的动态。</p>'}</div>${posts.total>12?pager(posts.total):''}`;
  socialBack('feed');bindPosts();if(posts.total>12)bindPager();
  if(canAct)$("#player-request").onclick=async e=>{const btn=e.currentTarget;btn.disabled=true;
    try{const incoming=p.relationship==='incoming';await api(incoming?'/friends/'+p.friend_id:'/friends',{method:incoming?'PUT':'POST',body:incoming?{action:'accept'}:{user_id:uid}});toast(incoming?'已成为好友':'好友申请已发送')}
    catch(err){toast(err.message)}finally{if(target.isConnected)await renderView()}};
}
async function singlePost(){
  const target=$("#content"),id=state.entity;
  const [p,comments]=await Promise.all([api('/posts/'+id),api('/posts/'+id+'/comments')]);if(!target.isConnected)return;state.posts=[p];
  target.innerHTML=`<div class="story-detail"><button class="identity-back" id="social-back">‹ 返回</button><h1>帖子详情</h1>${card(p,true)}
    <section class="panel"><h2>评论 · ${comments.length}</h2>${comments.map(x=>`<div class="story-comment"><a href="#player/${x.user_id}">${esc(x.nickname)}</a>${x.parent_id?' · 回复 '+esc(comments.find(y=>y.id===x.parent_id)?.nickname||'评论'):''}<p>${esc(x.content)}</p></div>`).join('')||'<p>暂时还没有评论。</p>'}<button data-comments="${p.id}">写评论 / 回复</button></section></div>`;
  socialBack('feed');bindPosts();
}
async function feedView() {
  const scope =
    state.view === "mine"
      ? "mine"
      : state.view === "friendsFeed"
        ? "friends"
        : "all";
  const feedTarget=$("#content"),entry=state.view;
  const result = await api(
    "/posts?" + query({ ...state.filters, page: state.page, scope }),
  );
  if(!feedTarget.isConnected||state.view!==entry)return;
  state.posts=result.items;
  const publicFeed=state.view==="feed",title=publicFeed?"玩家广场":state.view==="mine"?"我的发布":"好友";
  const anyFilters=Object.values(state.filters).some(Boolean);
  const heading=publicFeed?`<section class="landscape-title"><div><h1>玩家广场</h1><p>来自玩家的世界与玩法。</p></div><button id="create-post">＋ 发布动态</button><a aria-label="查看封面图来源：Iris" href="https://modrinth.com/mod/iris/gallery" title="封面：Iris / Wide Mountain" target="_blank" rel="noopener">Iris ↗</a></section>`:head(title,"",'<button id="create-post">＋ 发布动态</button>');
  $("#content").innerHTML=`<section class="journal">${heading}<div class="journal-bar"><h2>${anyFilters?'筛选结果':'最新动态'} <small>${result.total}</small></h2><button class="filter-trigger" id="filter-toggle" aria-expanded="${anyFilters}" aria-controls="filter-panel">搜索与筛选${anyFilters?' · 已应用':''}</button></div><div id="filter-panel" ${anyFilters?'':'hidden'}>${filterBar()}</div><div class="journal-stream">${result.items.map(p=>card(p)).join('')||'<div class="empty">这里还没有动态。</div>'}</div>${result.total>12?pager(result.total):''}</section>`;
  $("#filter-toggle").onclick=e=>{const panel=$("#filter-panel");panel.hidden=!panel.hidden;e.currentTarget.setAttribute('aria-expanded',String(!panel.hidden));if(!panel.hidden)panel.querySelector('input').focus()};
  bindFilter();
  if(result.total>12)bindPager();
  bindPosts();$("#create-post").onclick=()=>editor();
}
// A contextual post menu closes after a command, on outside click, or with Escape.
document.addEventListener("click",e=>{
  document.querySelectorAll(".post-options[open]").forEach(menu=>{
    if(!menu.contains(e.target)||e.target.closest("button"))menu.open=false;
  });
});
document.addEventListener("keydown",e=>{
  if(e.key!=="Escape" || document.querySelector("dialog[open]"))return;
  const menu=document.querySelector(".post-options[open]");
  if(menu){menu.open=false;menu.querySelector("summary").focus();}
});
function bindPosts() {
  document.querySelectorAll('.journal-card').forEach(el=>{el.onclick=e=>{if(e.target.closest('a,button,details,select,input,img,video')||window.getSelection()?.toString())return;el.querySelector('.post-open')?.click()}});

 document.querySelectorAll("[data-report]").forEach(b=>b.onclick=()=>{openModal("举报帖子",'<form id="flag"><input name="reason" required maxlength="250" placeholder="说明问题"><button>提交举报</button></form>');$("#flag").onsubmit=async e=>{e.preventDefault();try{await api("/posts/"+b.dataset.report+"/report",{method:"POST",body:{reason:e.target.reason.value}});modal.close();toast("举报已提交")}catch(e){toast(e.message)}}});
  document.querySelectorAll("[data-copy]").forEach(b=>b.onclick=async()=>{try{await api("/pack/action",{method:"POST",body:{op:"add",value:b.dataset.copy}});await navigate("bench")}catch(e){toast(e.message)}});
  document.querySelectorAll("[data-jump]").forEach(b=>b.onclick=()=>{const v=b.closest("article").querySelector("video");if(v){v.currentTime=Number(b.dataset.jump);v.play().catch(()=>{})}else navigate("library")});
  document
    .querySelectorAll("[data-edit]")
    .forEach(
      (b) =>
        (b.onclick = () =>
          editor(state.posts.find((p) => p.id === Number(b.dataset.edit)))),
    );
  document.querySelectorAll("[data-delete]").forEach(
    (b) =>
      (b.onclick = () =>
        confirmAction(
          "删除动态",
          "删除后，图片、评论和评分将一并删除，无法恢复。",
          async () => {
            await api("/posts/" + b.dataset.delete, { method: "DELETE" });
            if(state.view==="post")await navigate("feed");else await renderView();
            toast("动态已删除");
          },
        )),
  );
  document.querySelectorAll("[data-rate]").forEach(
    (s) =>
      (s.onchange = async () => {
        if (!s.value) return;
        try {
          await api("/posts/" + s.dataset.rate + "/rating", {
            method: "PUT",
            body: { score: Number(s.value) },
          });
          await renderView();
          toast("评分已保存");
        } catch (e) {
          toast(e.message);
        }
      }),
  );
  document
    .querySelectorAll("[data-comments]")
    .forEach(
      (b) => (b.onclick = () => showComments(Number(b.dataset.comments))),
    );
  document
    .querySelectorAll("[data-photo]")
    .forEach(
      (img) =>
        (img.onclick = () =>
          openModal(
            "照片预览",
            `<img class="photo-full" alt="照片预览" src="${img.dataset.photo}">`,
          )),
    );
}
function openModal(title, body) {
  modal.innerHTML = `<div class="modal-head"><h2>${esc(title)}</h2><button id="close-modal" aria-label="关闭">×</button></div>${body}`;
  if (!modal.open) modal.showModal();
  $("#close-modal").onclick = () => modal.close();
}
function confirmAction(title, description, action) {
  openModal(
    title,
    `<p class="side-copy">${description}</p><div class="modal-actions"><button class="ghost" id="cancel">取消</button><button class="danger" id="confirm">确认${title}</button></div>`,
  );
  $("#cancel").onclick = () => modal.close();
  $("#confirm").onclick = async () => {
    const b = $("#confirm");
    b.disabled = true;
    try {
      await action();
      modal.close();
    } catch (e) {
      toast(e.message);
      b.disabled = false;
    }
  };
}
async function editor(post = null) {
  let mods;try{mods=await api("/library")}catch(e){toast(e.message);return}
  let media = post ? [...post.media] : [];
  openModal(
    post ? "编辑这条玩法" : "记录新的玩法",
    `<form id="post-form"><label for="post-content">这一刻，想说些什么</label><textarea id="post-content" name="content" rows="5" maxlength="3000" placeholder="分享你的所见、所感、所爱…">${esc(post?.content || "")}</textarea><label for="post-tags">标签</label><input id="post-tags" name="tags" placeholder="使用逗号分隔，最多 5 个，例如：生存,建筑" value="${esc(post?.tags.join(",") || "")}"><label for="post-visibility">谁可以看</label><select id="post-visibility" name="visibility">${Object.entries(
      visibility,
    )
      .map(
        ([k, v]) =>
          `<option value="${k}" ${post?.visibility === k ? "selected" : ""}>${v}</option>`,
      )
      .join(
        "",
      )}</select><label>关联玩法（可选）</label><select name="mod_slug"><option value="">不关联 Mod</option>${mods.map(m=>`<option value="${esc(m.slug)}" ${post?.mod_slug===m.slug?"selected":""}>${esc(m.title)}</option>`).join("")}</select><label>效果时间点（秒，视频选填）</label><input name="second" type="number" min="0" max="86400" value="${post?.effect_second||0}">${packEditor(post)}<label for="post-files">图片或视频</label><input id="post-files" type="file" accept="image/jpeg,image/png,image/webp,image/gif,video/mp4" multiple><p class="hint">最多 9 个媒体 · 每个文件不超过 50 MB · 支持 JPG / PNG / WebP / GIF / MP4</p><div id="previews" class="preview-list"></div><p class="hint" id="upload-status"></p><div class="modal-actions"><button type="submit" id="save-post">${post ? "保存修改" : "发布动态"}</button></div></form>`,
  );
  const previews = () => {
    $("#previews").innerHTML = media
      .map(
        (m, i) =>
          `<div class="preview">${m.kind === "video" ? `<video src="${mediaSrc(m.url)}" controls></video>` : `<img src="${mediaSrc(m.url)}" alt="待发布图片">`}<button type="button" data-remove="${i}" aria-label="移除媒体">×</button></div>`,
      )
      .join("");
    document.querySelectorAll("[data-remove]").forEach(
      (b) =>
        (b.onclick = () => {
          media.splice(Number(b.dataset.remove), 1);
          previews();
        }),
    );
  };
  previews();
  $("#post-files").onchange = async (event) => {
    const files = [...event.target.files];
    if (files.length + media.length > 9) {
      toast("最多添加 9 个媒体");
      event.target.value = "";
      return;
    }
    $("#save-post").disabled = true;
    try {
      for (const [index, file] of files.entries()) {
        if (file.size > 50 * 1024 * 1024)
          throw new Error("单个文件不能超过 50 MB");
        $("#upload-status").textContent =
          `正在上传 ${index + 1}/${files.length}…`;
        const body = new FormData();
        body.append("file", file);
        media.push(await api("/media", { method: "POST", body }));
        previews();
      }
      $("#upload-status").textContent = "上传完成";
    } catch (e) {
      toast(e.message);
      $("#upload-status").textContent = "部分文件未上传，请重试";
    } finally {
      $("#save-post").disabled = false;
      event.target.value = "";
    }
  };
  $("#post-form").onsubmit = async (event) => {
    event.preventDefault();
    const b = $("#save-post");
    b.disabled = true;
    try {
      const values = Object.fromEntries(new FormData(event.target));
      await api("/posts" + (post ? "/" + post.id : ""), {
        method: post ? "PUT" : "POST",
        body: {
          content: values.content, attach_pack:values.attach_pack==='on', mod_slug:values.mod_slug,effect_second:Number(values.second),
          tags: values.tags
            .split(/[,，]/)
            .map((x) => x.trim())
            .filter(Boolean),
          visibility: values.visibility,
          media_ids: media.map((m) => m.id),
        },
      });
      modal.close();
      state.page = 1;
      await renderView();
      toast(post ? "修改已保存" : "新的玩法已发布");
    } catch (e) {
      toast(e.message);
    } finally {
      b.disabled = false;
    }
  };
}
async function showComments(id) {
  try {
    const [post, comments] = await Promise.all([
      api("/posts/" + id),
      api("/posts/" + id + "/comments"),
    ]);
    state.reply = null;
    openModal(
      "评论与交流",
      `<div id="comments-list">${comments.length ? comments.map((c) => `<div class="comment"><strong>${esc(c.nickname)}</strong> <small>${date(c.created_at)}</small>${c.parent_id ? `<small> · 回复 ${esc(comments.find((x) => x.id === c.parent_id)?.nickname || "评论")}</small>` : ""}<p>${esc(c.content)}</p><button data-reply="${c.id}" data-name="${esc(c.nickname)}">回复</button>${state.user.id === c.user_id || state.user.id === post.user_id || state.user.role === "admin" ? `<button data-delete-comment="${c.id}">删除</button>` : ""}</div>`).join("") : '<p class="muted">还没有评论，来聊聊吧。</p>'}</div><form id="comment-form"><label id="reply-label" for="comment-content">写下你的评论</label><textarea id="comment-content" maxlength="500" rows="3" required placeholder="友善交流，让分享更有温度"></textarea><div class="modal-actions"><button type="button" class="ghost" id="cancel-reply">取消回复</button><button type="submit">发送评论</button></div></form>`,
    );
    document.querySelectorAll("[data-reply]").forEach(
      (b) =>
        (b.onclick = () => {
          state.reply = Number(b.dataset.reply);
          $("#reply-label").textContent = "回复 " + b.dataset.name;
          $("#comment-content").focus();
        }),
    );
    $("#cancel-reply").onclick = () => {
      state.reply = null;
      $("#reply-label").textContent = "写下你的评论";
    };
    document.querySelectorAll("[data-delete-comment]").forEach(
      (b) =>
        (b.onclick = () =>
          confirmAction("删除评论", "该评论及其回复将被删除。", async () => {
            await api("/comments/" + b.dataset.deleteComment, {
              method: "DELETE",
            });
            await renderView();
          })),
    );
    $("#comment-form").onsubmit = async (event) => {
      event.preventDefault();
      const button = $("button[type=submit]", event.target);
      button.disabled = true;
      try {
        await api("/posts/" + id + "/comments", {
          method: "POST",
          body: {
            content: $("#comment-content").value,
            parent_id: state.reply,
          },
        });
        await renderView();
        await showComments(id);
      } catch (e) {
        toast(e.message);
      } finally {
        button.disabled = false;
      }
    };
  } catch (e) {
    toast(e.message);
  }
}
async function friendsView() {
  const list = await api("/friends");
  $("#content").innerHTML =
    head("好友", "") +
    `<div class="split"><div class="panel"><h3>好友与申请</h3>${list.length ? list.map((f) => `<div class="friend"><div class="avatar">${esc(f.nickname[0])}</div><div class="info"><strong>${esc(f.nickname)}</strong><small>@${esc(f.username)} · ${f.status === "accepted" ? "已成为好友" : f.requester === state.user.id ? "等待对方确认" : "请求添加你为好友"}</small></div>${f.status === "pending" && f.receiver === state.user.id ? `<button class="small" data-accept="${f.id}">接受</button>` : ""}<button class="small ghost" data-remove-friend="${f.id}">${f.status === "accepted" ? "移除" : f.receiver === state.user.id ? "拒绝" : "取消"}</button></div>`).join("") : '<p class="muted">还没有好友，试试搜索用户名。</p>'}</div><div class="panel"><h3>发现朋友</h3><form id="find-friend" class="filter"><input name="q" placeholder="搜索昵称或用户名" aria-label="搜索好友"><button>搜索</button></form><div id="friend-results"><p class="hint">演示账号：alice、bob、carol。</p></div></div></div>`;
  document.querySelectorAll("[data-accept]").forEach(
    (b) =>
      (b.onclick = async () => {
        try {
          await api("/friends/" + b.dataset.accept, {
            method: "PUT",
            body: { action: "accept" },
          });
          await renderView();
          toast("已成为好友");
        } catch (e) {
          toast(e.message);
        }
      }),
  );
  document.querySelectorAll("[data-remove-friend]").forEach(
    (b) =>
      (b.onclick = () =>
        confirmAction(
          "移除关系",
          "取消申请或移除好友后，可以重新发起申请。",
          async () => {
            await api("/friends/" + b.dataset.removeFriend, {
              method: "DELETE",
            });
            await renderView();
          },
        )),
  );
  $("#find-friend").onsubmit = async (event) => {
    event.preventDefault();
    try {
      const result = await api(
        "/users/search?" + new URLSearchParams(new FormData(event.target)),
      );
      $("#friend-results").innerHTML = result.length
        ? result
            .map(
              (u) =>
                `<div class="friend"><div class="avatar">${esc(u.nickname[0])}</div><div class="info">${esc(u.nickname)}<small>@${esc(u.username)}</small></div><button class="small" data-add-friend="${u.id}">添加好友</button></div>`,
            )
            .join("")
        : '<p class="muted">没有找到匹配的用户</p>';
      document.querySelectorAll("[data-add-friend]").forEach(
        (b) =>
          (b.onclick = async () => {
            try {
              await api("/friends", {
                method: "POST",
                body: { user_id: Number(b.dataset.addFriend) },
              });
              toast("申请已发送");
              await renderView();
            } catch (e) {
              toast(e.message);
            }
          }),
      );
    } catch (e) {
      toast(e.message);
    }
  };
}
function settingsView() {
  $("#content").innerHTML =
    head("账号设置", "管理自己的登录密码和模型连接。") +
    `<section class="panel settings"><h3>个人 AI 模型</h3><p>为这个账号使用自己的文本或视觉模型，也可以跟随社区默认。</p><a href="#ai">前往 AI 工坊设置 →</a></section>` +
    `<section class="panel settings"><h3>登录密码</h3><p class="hint">修改密码后，所有设备上的登录状态都会失效。</p><form id="password-form"><label for="old-password">原密码</label><input id="old-password" name="old_password" type="password" required autocomplete="current-password"><label for="new-password">新密码</label><input id="new-password" name="new_password" type="password" required minlength="8" maxlength="72" autocomplete="new-password"><label for="confirm-password">确认新密码</label><input id="confirm-password" type="password" required autocomplete="new-password"><button>保存新密码</button></form></section>`;
  $("#password-form").onsubmit = async (event) => {
    event.preventDefault();
    if ($("#new-password").value !== $("#confirm-password").value) {
      toast("两次输入的新密码不一致");
      return;
    }
    try {
      await api("/auth/password", {
        method: "PUT",
        body: Object.fromEntries(new FormData(event.target)),
      });
      if(adminPage)sessionStorage.removeItem("atlas-admin");
      state.user = null;
      loginView();
      toast("密码已更新，请重新登录");
    } catch (e) {
      toast(e.message);
    }
  };
}
async function dashboardView() {
  const s = await api("/admin/stats");
  const max = Math.max(1, ...s.trend.flatMap((x) => [x.posts, x.users]));
  const bars = s.trend
    .map((x, i) => {
      const left = 40 + i * 70;
      return `<rect x="${left}" y="${170 - (x.posts / max) * 130}" width="16" height="${(x.posts / max) * 130}" rx="3" fill="#6e9c7c"><title>${x.date} 新增动态 ${x.posts}</title></rect><rect x="${left + 20}" y="${170 - (x.users / max) * 130}" width="16" height="${(x.users / max) * 130}" rx="3" fill="#d6be8c"><title>${x.date} 新增用户 ${x.users}</title></rect><text x="${left + 17}" y="195" text-anchor="middle">${x.date.slice(5)}</text><text x="${left + 8}" y="${162 - (x.posts / max) * 130}" text-anchor="middle">${x.posts}</text>`;
    })
    .join("");
  const labels = { text: "文字动态", image: "图片动态", video: "视频动态" };
  $("#content").innerHTML =
    head(
      "社区运营概览",
      "了解社区的使用情况，让管理更有依据。",
      '<button class="outline" id="refresh-stats">↻　刷新数据</button>',
    ) +
    `<div class="stats">${[
      ["用户总数", s.counts.users, "包含管理员账号"],
      ["动态总数", s.counts.posts, `已下架 ${s.counts.hidden} 条`],
      ["近 7 日活跃用户", s.counts.active_7d, "近 7 日访问 API 的普通用户"],
      [
        "互动总数",
        s.counts.comments + s.counts.ratings,
        `${s.counts.comments} 条评论 / ${s.counts.ratings} 个评分`,
      ],
    ]
      .map(
        ([a, b, c]) =>
          `<div class="stat"><small>${a}</small><strong>${b}</strong><span>${c}</span></div>`,
      )
      .join(
        "",
      )}</div><div class="charts"><section class="panel"><div class="side-title"><h3>社区增长趋势</h3><small>最近 7 天 · 北京时间</small></div><div class="legend"><span><b style="background:#6e9c7c"></b>新增动态</span><span><b style="background:#d6be8c"></b>新增用户</span></div><svg class="chart" role="img" aria-label="最近七天新增动态与用户柱状图" viewBox="0 0 550 210"><path d="M25 170H535 M25 105H535 M25 40H535" stroke="#edf1e8"/>${bars}</svg></section><section class="panel"><div class="side-title"><h3>内容构成</h3><small>按动态计数</small></div>${[
      "image",
      "text",
      "video",
    ]
      .map((kind, i) => {
        const count = s.kinds.find((x) => x.kind === kind)?.count || 0;
        return `<div class="bar-row"><span>${labels[kind]}</span><div class="bar"><i style="width:${(count / Math.max(1, s.counts.posts)) * 100}%;background:${["#6f997a", "#cfb784", "#97b7ba"][i]}"></i></div><strong>${count}</strong></div>`;
      })
      .join(
        "",
      )}<p class="hint">包含视频的混合动态计为视频；其余有图片的计为图片。</p></section></div><section class="panel"><div class="side-title"><h3>大家正在分享</h3><small>热门标签 TOP 8</small></div>${s.tags.length ? s.tags.map((t) => `<div class="bar-row"><span># ${esc(t.name)}</span><div class="bar"><i style="width:${(t.count / Math.max(...s.tags.map((t) => t.count))) * 100}%"></i></div><small>${t.count} 条动态</small></div>`).join("") : '<p class="muted">暂无标签数据</p>'}</section>`;
  $("#refresh-stats").onclick = renderView;
}
async function manageView() {
  const result = await api(
    "/posts?" + query({ ...state.filters, page: state.page }),
  );
  state.posts = result.items;
  $("#content").innerHTML =
    head("内容管理", "查询、查看和管理社区中的所有动态。") +
    filterBar() +
    `<div class="table-wrap"><table><thead><tr><th>动态 / 发布者</th><th>类型</th><th>发布时间</th><th>状态</th><th>操作</th></tr></thead><tbody>${result.items.map((p) => `<tr><td><div class="clip">${esc(p.content || "媒体动态")}</div><small>${esc(p.nickname)} · #${p.id}</small></td><td>${p.media.some((m) => m.kind === "video") ? "视频" : p.media.length ? "图片" : "文字"}</td><td>${date(p.created_at)}</td><td><span class="badge">${p.hidden ? "已下架" : visibility[p.visibility]}</span></td><td><div class="actions"><button class="small ghost" data-detail="${p.id}">查看</button><button class="small ghost" data-toggle-post="${p.id}" data-hidden="${p.hidden}">${p.hidden ? "恢复" : "下架"}</button><button class="small danger" data-delete="${p.id}">删除</button></div></td></tr>`).join("") || '<tr><td colspan="5">暂无符合条件的动态</td></tr>'}</tbody></table></div>${pager(result.total)}`;
  bindFilter();
  bindPager();
  bindPosts();
  document.querySelectorAll("[data-detail]").forEach(
    (b) =>
      (b.onclick = () => {
        openModal(
          "动态详情",
          card(state.posts.find((p) => p.id === Number(b.dataset.detail))),
        );
        bindPosts();
      }),
  );
  document.querySelectorAll("[data-toggle-post]").forEach(
    (b) =>
      (b.onclick = async () => {
        try {
          await api("/admin/posts/" + b.dataset.togglePost + "/status", {
            method: "PUT",
            body: { enabled: b.dataset.hidden === "1" },
          });
          await renderView();
          toast("内容状态已更新");
        } catch (e) {
          toast(e.message);
        }
      }),
  );
}
async function usersView() {
  const result = await api(
    "/admin/users?" +
      new URLSearchParams({ q: state.filters.q || "", page: state.page }),
  );
  $("#content").innerHTML =
    head("用户管理", "查看用户状态，维护有序的社区环境。") +
    `<form id="user-filter" class="filter"><input name="q" placeholder="搜索用户名或昵称" aria-label="搜索用户" value="${esc(state.filters.q || "")}"><button>搜索</button></form><div class="table-wrap"><table><thead><tr><th>用户</th><th>角色</th><th>注册时间</th><th>最近活跃</th><th>状态</th><th>操作</th></tr></thead><tbody>${result.items.map((u) => `<tr><td>${esc(u.nickname)}<br><small>@${esc(u.username)}</small></td><td>${u.role === "admin" ? "管理员" : "普通用户"}</td><td>${date(u.created_at)}</td><td>${date(u.last_active)}</td><td><span class="badge">${u.disabled ? "已停用" : "正常"}</span></td><td>${u.role === "admin" ? "<small>受保护账号</small>" : `<div class="actions"><button class="small ghost" data-toggle-user="${u.id}" data-disabled="${u.disabled}">${u.disabled ? "启用" : "停用"}</button><button class="small danger" data-delete-user="${u.id}">删除</button></div>`}</td></tr>`).join("") || '<tr><td colspan="6">未找到用户</td></tr>'}</tbody></table></div>${pager(result.total, 20)}`;
  bindPager();
  $("#user-filter").onsubmit = (e) => {
    e.preventDefault();
    state.filters = Object.fromEntries(new FormData(e.target));
    state.page = 1;
    renderView();
  };
  document.querySelectorAll("[data-toggle-user]").forEach(
    (b) =>
      (b.onclick = async () => {
        try {
          await api("/admin/users/" + b.dataset.toggleUser + "/status", {
            method: "PUT",
            body: { enabled: b.dataset.disabled === "1" },
          });
          await renderView();
          toast("用户状态已更新");
        } catch (e) {
          toast(e.message);
        }
      }),
  );
  document.querySelectorAll("[data-delete-user]").forEach(
    (b) =>
      (b.onclick = () =>
        confirmAction(
          "删除用户",
          "该用户的动态、媒体、评论、评分和好友关系将一并删除，无法恢复。",
          async () => {
            await api("/admin/users/" + b.dataset.deleteUser, {
              method: "DELETE",
            });
            await renderView();
            toast("用户已删除");
          },
        )),
  );
}
async function wordsView() {
  const words = await api("/admin/words");
  $("#content").innerHTML =
    head(
      "让交流，多一份善意",
      "发布与编辑动态、标签、评论和注册昵称时自动替换敏感词。",
    ) +
    `<div class="panel"><form id="word-form" class="filter"><input name="word" maxlength="30" required placeholder="输入要过滤的词语" aria-label="新增敏感词"><button>添加词语</button></form><div class="tag-cloud">${words.map((w) => `<button class="tag" data-word="${esc(w)}">${esc(w)}　×</button>`).join("")}</div><p class="hint">点击词语可删除。词库更新对后续提交生效，历史内容需管理员另行下架或删除。此功能采用精确词匹配，不包含图像、语音或语义审核。</p></div>`;
  $("#word-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api("/admin/words", {
        method: "POST",
        body: Object.fromEntries(new FormData(e.target)),
      });
      await renderView();
      toast("词语已添加");
    } catch (e) {
      toast(e.message);
    }
  };
  document.querySelectorAll("[data-word]").forEach(
    (b) =>
      (b.onclick = () =>
        confirmAction(
          "删除词语",
          "删除后，后续提交不再过滤此词。",
          async () => {
            await api(
              "/admin/words?word=" + encodeURIComponent(b.dataset.word),
              { method: "DELETE" },
            );
            await renderView();
          },
        )),
  );
}
async function auditView() {
  const logs = await api("/admin/audit");
  const labels = {
    delete_post: "删除动态",
    hide_post: "下架动态",
    restore_post: "恢复动态",
    delete_user: "删除用户",
    disable_user: "停用用户",
    enable_user: "启用用户",
    add_word: "新增敏感词",
    delete_word: "删除敏感词",
  };
  $("#content").innerHTML =
    head("操作日志", "记录最近 100 次管理操作，方便追溯。") +
    `<div class="table-wrap"><table><thead><tr><th>时间</th><th>操作者</th><th>操作</th><th>目标</th></tr></thead><tbody>${logs.map((l) => `<tr><td>${date(l.created_at)}</td><td>${esc(l.actor)}</td><td>${labels[l.action] || esc(l.action)}</td><td>${esc(l.target)}</td></tr>`).join("") || '<tr><td colspan="4">暂无操作记录</td></tr>'}</tbody></table></div>`;
}
// Renderers share the community shell, authenticated API client and modal.
async function resourceNotes(v){
 let n=await api('/library/'+v.slug+'/notes');openModal(v.title+' · 实测记录',`<p>Java 1.20.1 / Fabric · ${esc(v.version)}</p><button id="star" class="ghost">${n.saved?'取消收藏':'收藏资源'}</button>${n.changed?'<p>收藏的版本已经更新</p>':''}<div>${n.notes.map(x=>`<p><b>${esc(x.nickname)} · ${esc(x.result)}</b> <small>${esc(x.version)}</small><br>${esc(x.note)}</p>`).join('')||'<p class="hint">还没有玩家提交实测。运行成功与否由玩家记录，星级评分单独统计。</p>'}</div><form id="field"><select name="result"><option>成功</option><option>异常</option><option>未启动</option></select><input name="note" required maxlength="400" placeholder="写下运行环境和实际表现"><button>保存我的实测</button></form>`);
 $('#star').onclick=async()=>{try{await api('/library/'+v.slug+'/bookmark',{method:'PUT'});await resourceNotes(v)}catch(e){toast(e.message)}};$('#field').onsubmit=async e=>{e.preventDefault();try{await api('/library/'+v.slug+'/notes',{method:'POST',body:{version:v.version,...Object.fromEntries(new FormData(e.target))}});await resourceNotes(v)}catch(e){toast(e.message)}}}
async function reportsView(){const rows=await api('/admin/reports');$('#content').innerHTML=head('举报处理','核对被举报的原帖与理由，再决定是否下架。')+rows.map(r=>`<section class="panel"><b>${esc(r.nickname)} · ${r.done?'已处理':'待处理'}</b><p>举报：${esc(r.reason)}</p><p>原帖 #${r.pid}：${esc(r.content)}</p>${r.done?'':`<button data-dismiss="${r.id}">处理完毕</button> <button class="ghost" data-hide="${r.pid}">下架原帖</button>`}</section>`).join('');if(!rows.length)$('#content').insertAdjacentHTML('beforeend','<div class="empty">暂无举报</div>');document.querySelectorAll('[data-dismiss]').forEach(b=>b.onclick=async()=>{try{await api('/admin/reports/'+b.dataset.dismiss+'/close',{method:'POST'});await reportsView()}catch(e){toast(e.message)}});document.querySelectorAll('[data-hide]').forEach(b=>b.onclick=()=>confirmAction('下架原帖','其他玩家将不能再看到这条内容。',async()=>{await api('/admin/posts/'+b.dataset.hide+'/status',{method:'PUT',body:{enabled:false}});await reportsView()}))}


const alias={sodium:'性能优化',jei:'配方查询',appleskin:'食物信息','fabric-api':'基础依赖',fallingtree:'连锁伐木'};
function asset(path){return path?.startsWith('/static/images/')||path?.startsWith('https://cdn.modrinth.com/')?esc(path):'';}
async function libraryView(){
 const list=await api('/library');let only=false,saved=[];const paint=(term='')=>{
 const rows=list.filter(x=>!only||saved.includes(x.slug)).filter(x=>[x.title,x.slug,alias[x.slug]].join(' ').toLowerCase().includes(term.toLowerCase()));
 $('#resource-grid').innerHTML=rows.map(x=>`<article class="resource"><img src="${asset(x.icon)}" alt=""><small>FABRIC · 1.20.1</small><h3>${esc(x.title)}</h3><p>${esc(alias[x.slug]||x.description)}</p><small>${esc(x.version)}</small><div><a href="${esc(x.source)}" target="_blank" rel="noopener">来源 ↗</a><button class="small ghost" data-notes="${esc(x.slug)}">实测 / 收藏</button> <button class="small" data-install="${esc(x.slug)}">＋ 加入草稿</button></div></article>`).join('')||'<p>没有匹配资源</p>';
 document.querySelectorAll('[data-notes]').forEach(b=>b.onclick=()=>resourceNotes(list.find(x=>x.slug===b.dataset.notes)).catch(e=>toast(e.message)));document.querySelectorAll('[data-install]').forEach(b=>b.onclick=async()=>{try{const s=await api('/pack/action',{method:'POST',body:{op:'add',value:b.dataset.install}});toast(s.last)}catch(e){toast(e.message)}})};
 $('#content').innerHTML=head('Mod 资源库','固定游戏版本：Java 1.20.1 / Fabric。导入的是资源索引，最终导出时才生成整合包。','<button id="import-mod">＋ 导入资源</button>')+'<button class="small ghost" id="onlysaved">只看收藏</button> <input id="findmod" placeholder="搜索模组名称或用途"><div id="resource-grid"></div>';
 $('#onlysaved').onclick=async()=>{try{saved=await api('/bookmarks');only=!only;$('#onlysaved').textContent=only?'显示全部':'只看收藏';paint($('#findmod').value)}catch(e){toast(e.message)}};$('#findmod').oninput=e=>paint(e.target.value);paint();$('#import-mod').onclick=()=>{openModal('从 Modrinth 导入','<form id="lookup"><label>项目链接或 slug</label><input name="link" required placeholder="https://modrinth.com/mod/lithium"><p class="hint">只收录适配当前版本的客户端 Mod。已有项目不会重复导入。</p><button>读取项目资料</button></form><div id="found"></div>');$('#lookup').onsubmit=async e=>{e.preventDefault();const link=e.target.link.value.trim(),dst=$('#found');dst.textContent='正在查询版本与必需依赖…';const input=e.target.link;input.disabled=true;try{const v=await api('/library/preview',{method:'POST',body:{link}});dst.innerHTML=`<h3>${esc(v.title)}</h3><p>${esc(v.description)}</p><p>版本 ${esc(v.version)} · 必需依赖：${esc(v.required.join(', ')||'索引未列出')}</p><button id="confirm-import">确认入库</button>`;$('#confirm-import').onclick=async ev=>{ev.target.disabled=true;try{await api('/library/import',{method:'POST',body:{link}});modal.close();await libraryView();toast('资源已入库')}catch(e){dst.textContent=e.message}}}catch(e){dst.textContent=e.message}finally{input.disabled=false}}}
}
async function benchView(){
 const [s,rows]=await Promise.all([api('/pack'),api('/library')]);const dict=Object.fromEntries(rows.map(x=>[x.slug,x]));
 $('#content').innerHTML=head('我的整合包','私人草稿 · Java 1.20.1 / Fabric 0.19.4','<button id="pack-export">生成最终包 ↓</button>')+`<div class="pack-origin"><b>草稿来源 · ${esc(s.origin?.label||"初始轻量生存包")}</b><small>新增：${esc(s.diff?.added.join("、")||"无")}　移除：${esc(s.diff?.removed.join("、")||"无")}</small></div><div class="benches"><section class="panel"><h3>组件清单 · ${s.mods.length}</h3>${s.mods.map(k=>`<div class="packrow"><img src="${asset(dict[k].icon)}" alt=""><strong>${esc(dict[k].title)}<small>${esc(dict[k].version)}</small></strong><button class="small ghost" data-op="${s.locks.includes(k)?'unlock':'lock'}" data-k="${esc(k)}">${s.locks.includes(k)?'已锁定':'锁定'}</button><button class="small ghost" data-op="remove" data-k="${esc(k)}">移除</button></div>`).join('')||'还没有组件'}<p>改动：${esc(s.last)}</p><button class="small ghost" data-op="undo" ${s.history.length?'':'disabled'}>撤销上一轮</button> <button id="go-library" class="small ghost">浏览资源</button></section><section class="panel"><h3>AI 对话改包 <small>${s.online?'在线模型':'离线指令'}</small></h3>${s.messages.map(([q,a])=>`<p><b>你：</b>${esc(q)}<br>工坊：${esc(a)}</p>`).join('')}<form id="adjust"><label>还想怎么改？</label><input name="q" required maxlength="400" placeholder="加上配方查询，锁定性能优化"><button>应用修改</button></form><p class="hint">支持添加、移除、锁定与撤销。移除仍被使用的依赖会被阻止。<br><a href="#ai" class="ai-inline">查看 AI 模型与配置入口 →</a></p></section></div>`;
 $('#go-library').onclick=()=>navigate('library');async function act(op,value=''){try{await api('/pack/action',{method:'POST',body:{op,value}});await benchView()}catch(e){toast(e.message)}}document.querySelectorAll('[data-op]').forEach(b=>b.onclick=()=>act(b.dataset.op,b.dataset.k));$('#adjust').onsubmit=e=>{e.preventDefault();act('chat',e.target.q.value)};$('#pack-export').onclick=async()=>{try{const x=await api('/pack/export',{method:'POST'});openModal('已生成整合包',`<p>取包码（24 小时有效）</p><h2>${esc(x.code)}</h2><p>电脑上打开 <a href="/pickup">取包页</a>，或直接下载。</p><a class="download" download href="${esc(x.url)}">下载最终 .mrpack ↓</a><p class="hint">启动器首次安装需要联网获取对应版本。取包码仅分享给需要的人。</p>`)}catch(e){toast(e.message)}}}


try {
  state.user = await api("/auth/me");
  if ((state.user.role==="admin")!==adminPage) throw Error("角色入口不匹配");
  state.view = state.user.role === "admin" ? "dashboard" : landing();
  shell();
  await renderView();
} catch {
  loginView();
}
