import { api, esc, openModal, toast } from './app.js';

const NS = 'http://www.w3.org/2000/svg';

function layout(nodes) {
  const width = 680, height = 430;
  const cx = width / 2, cy = height / 2 - 6;
  const radius = Math.min(width, height) / 2 - 74;
  const placed = new Map();
  nodes.forEach((node, index) => {
    const angle = -Math.PI / 2 + (index * 2 * Math.PI) / Math.max(nodes.length, 1);
    placed.set(node.slug, {
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
    });
  });
  return { width, height, placed };
}

function nodeState(node, draftConflicts) {
  const pair = draftConflicts.some((e) => e.a === node.slug || e.b === node.slug);
  if (pair) return 'bad';
  if (node.in_draft) return 'draft';
  return 'idle';
}

function render(graph) {
  const { width, height, placed } = layout(graph.nodes);
  const parts = [];
  for (const edge of graph.deps) {
    const a = placed.get(edge.a), b = placed.get(edge.b);
    if (a && b) parts.push(`<line class="edge edge-dep" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/>`);
  }
  for (const edge of graph.edges) {
    const a = placed.get(edge.a), b = placed.get(edge.b);
    if (a && b) {
      const hot = graph.draft_conflicts.some((e) => e.a === edge.a && e.b === edge.b);
      parts.push(`<line class="edge edge-bad${hot ? ' hot' : ''}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/>`);
    }
  }
  for (const node of graph.nodes) {
    const p = placed.get(node.slug);
    if (!p) continue;
    const state = nodeState(node, graph.draft_conflicts);
    const clip = `clip-${node.slug.replace(/[^a-z0-9-]/gi, '')}`;
    const icon = node.icon
      ? `<clipPath id="${clip}"><circle r="23"/></clipPath>
         <image href="${esc(node.icon)}" x="-23" y="-23" width="46" height="46" clip-path="url(#${clip})" preserveAspectRatio="xMidYMid slice"/>`
      : `<circle r="23" class="node-letter-bg"/><text class="node-letter" y="5">${esc(node.title.slice(0, 1))}</text>`;
    parts.push(
      `<g class="node ${state}" data-slug="${esc(node.slug)}" transform="translate(${p.x},${p.y})" tabindex="0" role="button" aria-label="${esc(node.title)}">
         <circle r="30" class="node-halo"/>
         ${icon}
         <text class="node-label" y="44">${esc(node.title.length > 14 ? node.title.slice(0, 13) + '…' : node.title)}</text>
       </g>`,
    );
  }
  return `<svg class="conflict-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="模组冲突与依赖关系图">
    ${parts.join('')}
  </svg>`;
}

function summaryBlock(graph) {
  const { summary } = graph;
  const chips = [
    ['资源', summary.mods, ''],
    ['冲突声明', summary.conflicts, summary.conflicts ? 'warn' : ''],
    ['冲突簇', summary.clusters, summary.clusters ? 'warn' : ''],
    ['草稿内冲突', summary.draft_conflicts, summary.draft_conflicts ? 'bad' : 'ok'],
  ];
  return `<div class="conflict-summary">${chips
    .map(([label, value, tone]) => `<span class="chip ${tone}">${label} <b>${value}</b></span>`)
    .join('')}</div>`;
}

function issuesBlock(graph) {
  const rows = [];
  for (const edge of graph.draft_conflicts) {
    rows.push(`<li class="issue bad">
      <b>${esc(edge.a_title)} × ${esc(edge.b_title)}</b>
      <small>两个都在当前草稿里，游戏启动大概率崩溃。</small>
      <span class="issue-actions">
        <button class="small" data-keep="${esc(edge.a)}" data-drop="${esc(edge.b)}">保留 ${esc(edge.a_title)}</button>
        <button class="small ghost" data-keep="${esc(edge.b)}" data-drop="${esc(edge.a)}">保留 ${esc(edge.b_title)}</button>
      </span></li>`);
  }
  for (const risk of graph.risks) {
    rows.push(`<li class="issue warn">
      <b>${esc(risk.title)}</b>
      <small>再把它加进草稿就会和 ${esc(risk.with_title)} 冲突。</small></li>`);
  }
  if (!rows.length) {
    const pairs = graph.edges.map((e) => `${esc(e.a_title)} × ${esc(e.b_title)}`);
    rows.push(
      pairs.length
        ? `<li class="issue warn"><b>草稿内没有冲突</b>
             <small>资源库里已有 ${pairs.length} 组声明互斥：${pairs.join('、')}。加进草稿之前先二选一；只想看看后果的话，点节点里的「仍然加入」。</small></li>`
        : '<li class="issue ok">当前没有任何声明互斥的模组。</li>',
    );
  }
  return `<ul class="issue-list">${rows.join('')}</ul>`;
}

export async function openConflictGraph() {
  const graph = await api('/conflicts');
  openModal(
    '冲突图',
    `<p class="hint">红色连线＝声明互斥；灰色虚线＝必需依赖。绿点是草稿里的组件，红点是当前已经构成冲突的两个组件。</p>
     ${summaryBlock(graph)}
     <div class="conflict-canvas">${render(graph)}</div>
     <div class="conflict-detail" id="conflict-detail"><p class="hint">点一个节点看它的依赖与冲突。</p></div>
     <h4>待处理</h4>
     ${issuesBlock(graph)}`,
  );
  const modal = document.querySelector('#modal');
  const detail = modal.querySelector('#conflict-detail');
  modal.querySelectorAll('.node').forEach((node) => {
    const show = () => {
      const info = graph.nodes.find((n) => n.slug === node.dataset.slug);
      if (!info) return;
      const req = info.required.length
        ? info.required.map((s) => graph.nodes.find((n) => n.slug === s)?.title || s).join('、')
        : '无';
      const detailRows = info.conflicts_detail || [];
      const con = detailRows.length
        ? detailRows
            .map((c) => `${esc(c.title)}<small>（${c.declared_by_me ? '本方声明' : '对方声明'}）</small>`)
            .join('、')
        : '无';
      const drafting = detailRows.filter(
        (c) => graph.nodes.find((n) => n.slug === c.slug)?.in_draft,
      );
      const force =
        !info.in_draft && drafting.length
          ? `<p class="hint">草稿里已有 ${drafting.map((c) => esc(c.title)).join('、')}。</p>
             <button class="small ghost" data-force="${esc(info.slug)}">仍然加入（会构成冲突）</button>`
          : '';
      detail.innerHTML = `<h4>${esc(info.title)}</h4>
        <p><small>${esc(info.version || '')}</small></p>
        <p>必需依赖：${esc(req)}</p>
        <p>声明冲突：<b class="${detailRows.length ? 'bad-text' : ''}">${con}</b></p>
        <p>当前草稿：${info.in_draft ? '已包含' : '未包含'}</p>
        ${force}
        <p><a href="${esc(info.source || '#')}" target="_blank" rel="noopener">来源 ↗</a></p>`;
      detail.querySelector('[data-force]')?.addEventListener('click', async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        try {
          const result = await api('/conflicts/force', { method: 'POST', body: { slug: info.slug } });
          toast(result.last);
          await openConflictGraph();
        } catch (error) {
          toast(error.message);
          button.disabled = false;
        }
      });
    };
    node.addEventListener('click', show);
    node.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); show(); }
    });
  });
  modal.querySelectorAll('[data-keep]').forEach((button) => {
    button.onclick = async () => {
      try {
        const result = await api('/conflicts/resolve', {
          method: 'POST',
          body: { keep: button.dataset.keep, drop: button.dataset.drop },
        });
        toast(result.last);
        await openConflictGraph();
      } catch (error) {
        toast(error.message);
      }
    };
  });
}
