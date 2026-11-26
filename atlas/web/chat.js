import { api, esc, openModal, toast } from './app.js';

let drawer = null;
let poller = null;
let active = null;

const portrait = (uid) => `/static/images/player-${Math.abs(Number(uid) || 0) % 3}.png`;

function fmt(stamp) {
  if (!stamp) return '';
  return new Date(stamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function modIcon(mod) {
  const icon = mod.icon || '';
  if (/^(\/static\/images\/|https:\/\/cdn\.modrinth\.com\/)/.test(icon)) {
    return `<img src="${esc(icon)}" alt="">`;
  }
  return `<span class="ph">${esc((mod.title || mod.slug || '?').slice(0, 1))}</span>`;
}

function packCard(message) {
  const payload = message.payload || {};
  const mods = payload.mods || [];
  const rows = mods
    .map((m) => `<li>${modIcon(m)}<span class="mod-title">${esc(m.title || m.slug)}</span><small>${esc(m.version || '')}</small></li>`)
    .join('');
  return `<div class="msg-card">
    <div class="msg-card-head"><b>${esc(payload.label || '整合包分享')}</b><span class="tag">${mods.length} 个组件</span></div>
    <div class="msg-card-body">
      <ul>${rows || '<li><span class="ph">·</span><span class="mod-title">空包</span></li>'}</ul>
      ${message.mine
        ? '<small class="muted-note">已发出</small>'
        : `<div class="msg-card-actions">
             <button class="small" data-import="${message.id}">加入我的草稿</button>
             <button class="small ghost" data-compare="${message.id}">对比差异</button>
           </div>`}
    </div>
  </div>`;
}

function inviteCard(message) {
  const payload = message.payload || {};
  const status = message.status || '';
  const label = status === 'accepted' ? '已接受' : status === 'declined' ? '已拒绝' : active?.kind === 'room' ? '群内公告' : '等待回应';
  const actions = active?.kind === 'dm' && !message.mine && status === 'pending'
    ? `<span class="issue-actions">
         <button class="small" data-answer="accept" data-mid="${message.id}">接受</button>
         <button class="small ghost" data-answer="decline" data-mid="${message.id}">拒绝</button>
       </span>`
    : `<span class="msg-status ${status === 'accepted' ? 'ok' : ''}">${label}</span>`;
  return `<div class="msg-card">
    <div class="msg-card-head"><b>联机邀请</b><span class="tag">${label}</span></div>
    <div class="msg-card-body">
      <div class="invite-row"><code>${esc(payload.address || '')}</code>
        <button class="small ghost" data-copy="${esc(payload.address || '')}">复制地址</button></div>
      ${payload.note ? `<p class="muted-note">${esc(payload.note)}</p>` : ''}
      ${actions}
    </div>
  </div>`;
}

function bubble(message) {
  const side = message.mine ? 'mine' : 'theirs';
  if (message.kind === 'text') {
    const who = active?.kind === 'room' && !message.mine ? `<small class="msg-who">${esc(message.sender_name || '')}</small>` : '';
    return `<div class="msg ${side}">${who}${esc(message.body)}</div>`;
  }
  return `<div class="msg ${side} card">${message.kind === 'pack' ? packCard(message) : inviteCard(message)}</div>`;
}

function ensureDrawer() {
  if (drawer) return drawer;
  drawer = document.createElement('aside');
  drawer.className = 'chat-drawer';
  drawer.setAttribute('aria-label', '聊天');
  drawer.innerHTML = `
    <header>
      <span class="chat-avatar" id="chat-avatar"></span>
      <span class="chat-who"><strong id="chat-name">好友</strong><small id="chat-sub">好友 · 消息仅彼此可见</small></span>
      <button class="chat-close" type="button" title="关闭">×</button>
    </header>
    <div class="chat-log" id="chat-log"></div>
    <div class="chat-tools">
      <button class="small ghost" type="button" data-share>分享整合包</button>
      <button class="small ghost" type="button" data-invite>邀请联机</button>
    </div>
    <form class="chat-invite-form" id="chat-invite-form" hidden>
      <input name="address" placeholder="服务器地址，例如 127.0.0.1:25565" maxlength="120" required>
      <input name="note" placeholder="备注（可选）" maxlength="200">
      <button class="small">发送邀请</button>
    </form>
    <form class="chat-compose" id="chat-compose">
      <input name="body" placeholder="说点什么…" maxlength="1000" autocomplete="off" required>
      <button>发送</button>
    </form>`;
  document.body.appendChild(drawer);
  drawer.querySelector('.chat-close').onclick = closeChat;
  drawer.querySelector('[data-share]').onclick = shareCurrent;
  drawer.querySelector('[data-invite]').onclick = () => {
    const form = drawer.querySelector('#chat-invite-form');
    form.hidden = !form.hidden;
    if (!form.hidden) form.querySelector('input').focus();
  };
  drawer.querySelector('#chat-invite-form').onsubmit = sendInvite;
  drawer.querySelector('#chat-compose').onsubmit = sendText;
  return drawer;
}

const base = () => (active.kind === 'room' ? `/rooms/${active.id}` : `/chat/${active.id}`);

async function refresh() {
  if (!active) return;
  const data = await api(base());
  const log = drawer.querySelector('#chat-log');
  const messages = data.messages || [];
  log.innerHTML = messages.length
    ? messages.map(bubble).join('')
    : '<p class="hint">还没有消息。可以发一句话，或者从工作台分享一个整合包。</p>';
  log.scrollTop = log.scrollHeight;
  log.querySelectorAll('[data-import]').forEach((button) => {
    button.onclick = async () => {
      try {
        const result = await api(`${base()}/pack/${button.dataset.import}/import`, { method: 'POST' });
        button.disabled = true;
        button.textContent = '已加入草稿';
        toast(result.last || '已并入草稿');
      } catch (error) {
        toast(error.message);
      }
    };
  });
  log.querySelectorAll('[data-compare]').forEach((button) => {
    button.onclick = () => openCompare(button.dataset.compare).catch((error) => toast(error.message));
  });
  log.querySelectorAll('[data-answer]').forEach((button) => {
    button.onclick = async () => {
      try {
        await api(`${base()}/invite/${button.dataset.mid}/respond`, {
          method: 'POST',
          body: { action: button.dataset.answer },
        });
        await refresh();
      } catch (error) {
        toast(error.message);
      }
    };
  });
  log.querySelectorAll('[data-copy]').forEach((button) => {
    button.onclick = async () => {
      try {
        await navigator.clipboard.writeText(button.dataset.copy);
        toast('地址已复制');
      } catch {
        toast('复制失败，请手动选中');
      }
    };
  });
}

function paintHeader(avatarHtml, title, subtitle) {
  const slot = drawer.querySelector('#chat-avatar');
  slot.innerHTML = avatarHtml;
  drawer.querySelector('#chat-name').textContent = title || '好友';
  drawer.querySelector('#chat-sub').textContent = subtitle || '';
}

function startPolling() {
  clearInterval(poller);
  poller = setInterval(() => refresh().catch(() => {}), 3000);
}

export async function openChat(uid, nickname) {
  if (!uid) return;
  ensureDrawer();
  active = { kind: 'dm', id: Number(uid), title: nickname };
  paintHeader(`<img src="${portrait(uid)}" alt="" width="36" height="36">`, nickname, '好友 · 消息仅彼此可见');
  drawer.classList.add('open');
  try {
    await refresh();
  } catch (error) {
    toast(error.message);
    return;
  }
  startPolling();
}

export async function openRoom(rid, name) {
  if (!rid) return;
  ensureDrawer();
  active = { kind: 'room', id: Number(rid), title: name };
  paintHeader(`<span class="chat-avatar-letter">${esc((name || '群').slice(0, 1))}</span>`, name, '群聊');
  drawer.classList.add('open');
  try {
    await refresh();
  } catch (error) {
    toast(error.message);
    return;
  }
  startPolling();
}

export function closeChat() {
  active = null;
  clearInterval(poller);
  poller = null;
  if (drawer) drawer.classList.remove('open');
}

async function sendText(event) {
  event.preventDefault();
  const input = event.target.body;
  const body = input.value.trim();
  if (!body) return;
  try {
    await api(base(), { method: 'POST', body: { body } });
    input.value = '';
    await refresh();
  } catch (error) {
    toast(error.message);
  }
}

async function sendInvite(event) {
  event.preventDefault();
  try {
    await api(`${base()}/invite`, {
      method: 'POST',
      body: { address: event.target.address.value.trim(), note: event.target.note.value.trim() },
    });
    event.target.reset();
    event.target.hidden = true;
    await refresh();
  } catch (error) {
    toast(error.message);
  }
}

function diffRow(mod, badge, kind = '') {
  return `<li class="${kind}">${modIcon(mod)}<span class="mod-title">${esc(mod.title || mod.slug)}</span>${badge}</li>`;
}

async function openCompare(mid) {
  const data = await api(`${base()}/pack/${mid}/compare`);
  const risky = new Set(data.risks.flatMap((e) => [e.a, e.b]));
  const missing = data.only_theirs.map((m) =>
    diffRow(m, `<small>${esc(m.version || '')}</small>${risky.has(m.slug) ? '<span class="diff-risk">会冲突</span>' : ''}`),
  );
  const extra = data.only_mine.map((m) => diffRow(m, '<span class="diff-tag">仅我有</span>'));
  const versions = data.version_diff.map(
    (m) => diffRow(m, `<small>${esc(m.mine_version)} → ${esc(m.theirs_version)}</small>`, 'diff-version'),
  );
  const safe = data.only_theirs.filter((m) => !risky.has(m.slug));
  const warns = data.risks.map(
    (e) => `<li>${esc(e.a_title)} × ${esc(e.b_title)}</li>`,
  );
  openModal(
    '整合包对比',
    `<div class="diff-compare">
       <p class="hint">「${esc(data.label)}」与当前草稿对比：对方 ${data.theirs_count} 个组件，我的草稿 ${data.mine_count} 个。</p>
       <div class="diff-grid">
         <section class="diff-col"><h4>可补齐 · ${data.only_theirs.length}</h4>
           <ul class="diff-list">${missing.join('') || '<li class="diff-empty">没有缺的组件</li>'}</ul></section>
         <section class="diff-col"><h4>对方没有 · ${data.only_mine.length}</h4>
           <ul class="diff-list">${extra.join('') || '<li class="diff-empty">无</li>'}</ul></section>
       </div>
       ${versions.length ? `<section class="diff-col"><h4>版本不同 · ${versions.length}</h4><ul class="diff-list">${versions.join('')}</ul></section>` : ''}
       ${warns.length ? `<section class="diff-warn"><b>补齐后会有 ${warns.length} 处冲突</b><ul>${warns.join('')}</ul><small>可只勾选安全组件，或到冲突图里处理后再补。</small></section>` : ''}
       <div class="modal-actions">
         <button class="ghost" id="diff-close">取消</button>
         <button id="diff-fill" ${safe.length ? '' : 'disabled'}>补齐 ${safe.length} 个安全组件</button>
       </div>
     </div>`,
  );
  const modalEl = document.querySelector('#modal');
  modalEl.querySelector('#diff-close').onclick = () => modalEl.close();
  modalEl.querySelector('#diff-fill').onclick = async (event) => {
    try {
      const result = await api(`${base()}/pack/${mid}/fill`, {
        method: 'POST',
        body: { slugs: safe.map((m) => m.slug) },
      });
      modalEl.close();
      toast(result.last || '已补齐到草稿');
      await refresh();
    } catch (error) {
      event.currentTarget.disabled = true;
      toast(error.message);
    }
  };
}

async function shareCurrent() {
  try {
    await api(`${base()}/pack`, { method: 'POST' });
    await refresh();
    toast('整合包已分享');
  } catch (error) {
    toast(error.message);
  }
}

export async function openSharePackTo() {
  const friends = (await api('/friends')).filter((f) => f.status === 'accepted');
  const groups = await api('/rooms').catch(() => []);
  const rows = [
    ...friends.map((f) => `<button class="small ghost" data-share-to="${f.other_id}">发给 ${esc(f.nickname)}</button>`),
    ...groups.map((g) => `<button class="small ghost" data-share-room="${g.id}">发到群聊 ${esc(g.name)}</button>`),
  ];
  openModal(
    '分享整合包',
    rows.length
      ? `<p class="hint">把当前草稿的组件清单发出去，对方点一下就能并入自己的草稿。</p>
         <div class="share-list">${rows.join('')}</div>`
      : '<p class="hint">还没有好友或群聊，先去「好友」页添加。</p>',
  );
  document.querySelectorAll('[data-share-to]').forEach((button) => {
    button.onclick = async () => {
      try {
        await api(`/chat/${button.dataset.shareTo}/pack`, { method: 'POST' });
        toast('已发送');
        document.querySelector('#modal').close();
      } catch (error) {
        toast(error.message);
      }
    };
  });
  document.querySelectorAll('[data-share-room]').forEach((button) => {
    button.onclick = async () => {
      try {
        await api(`/rooms/${button.dataset.shareRoom}/pack`, { method: 'POST' });
        toast('已发到群聊');
        document.querySelector('#modal').close();
      } catch (error) {
        toast(error.message);
      }
    };
  });
}

export async function openCreateRoom(onCreated) {
  const friends = (await api('/friends')).filter((f) => f.status === 'accepted');
  openModal(
    '创建群聊',
    `<p class="hint">群聊至少需要一位好友。之后群主还可以继续加人。</p>
     <form id="room-form">
       <label for="room-name">群聊名称</label>
       <input id="room-name" name="name" required maxlength="30" placeholder="比如：周末生存小队">
       <div class="room-members">${
         friends.length
           ? friends
               .map(
                 (f) => `<label class="room-pick"><input type="checkbox" name="member" value="${f.other_id}"> ${esc(f.nickname)}</label>`,
               )
               .join('')
           : '<p class="hint">还没有好友可以邀请。</p>'
       }</div>
       <button>创建</button>
     </form>`,
  );
  document.querySelector('#room-form').onsubmit = async (event) => {
    event.preventDefault();
    const form = event.target;
    const members = form.querySelectorAll('input[name="member"]:checked');
    if (!members.length) {
      toast('至少选一位好友');
      return;
    }
    try {
      const room = await api('/rooms', {
        method: 'POST',
        body: { name: form.name.value.trim(), members: [...members].map((m) => Number(m.value)) },
      });
      document.querySelector('#modal').close();
      toast('群聊已创建');
      await openRoom(room.id, room.name);
      onCreated?.();
    } catch (error) {
      toast(error.message);
    }
  };
}
