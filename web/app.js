/* FishAutoPro Clone - single page admin.
 * No build step, no framework: small helpers + fetch + template strings.
 */
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[c]));
const money = (v) => '¥' + Number(v || 0).toFixed(2);
const fmtTime = (v) => (v ? String(v).replace('T', ' ').slice(0, 19) : '—');
const fmtDate = (v) => (v ? String(v).slice(0, 10) : '—');

const state = { user: null, page: 'dashboard', convId: null, chat: null };

/* ------------------------------------------------------------------ api */
async function api(path, opts = {}) {
  const init = { method: opts.method || 'GET', headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' };
  if (opts.body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch('/api' + path, init);
  let data = null;
  try { data = await res.json(); } catch (e) { data = {}; }
  if (res.status === 401 && !opts.noRedirect) {
    state.user = null;
    renderLogin();
    throw new Error('未登录');
  }
  if (!res.ok || data.ok === false) {
    const err = new Error(data.error || `请求失败 (${res.status})`);
    err.data = data;
    throw err;
  }
  return data;
}

/* ------------------------------------------------------------------ toast / modal */
function toast(message, type = '') {
  const root = $('#toast-root');
  const el = document.createElement('div');
  el.className = 'toast ' + (type === 'error' ? 'err' : type === 'ok' ? 'ok' : '');
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 250); }, 3200);
}

function closeModal() {
  const root = $('#modal-root');
  root.innerHTML = '';
}

function openModal(title, bodyHtml, { submitText = '保存', onSubmit = null, wide = false, footExtra = '' } = {}) {
  const root = $('#modal-root');
  root.innerHTML = `
    <div class="modal-backdrop" data-close="1">
      <div class="modal" style="${wide ? 'width:min(860px,100%)' : ''}" onclick="event.stopPropagation()">
        <div class="modal-head"><h3>${esc(title)}</h3><div class="spacer"></div>
          <button class="icon-btn" data-close="1" aria-label="关闭">✕</button></div>
        <div class="modal-body">${bodyHtml}</div>
        <div class="modal-foot">${footExtra}
          <button class="btn" data-close="1">取消</button>
          ${onSubmit ? `<button class="btn primary" id="modal-submit">${esc(submitText)}</button>` : ''}
        </div>
      </div>
    </div>`;
  $$('#modal-root [data-close]').forEach((el) => el.addEventListener('click', closeModal));
  const submit = $('#modal-submit');
  if (submit && onSubmit) {
    submit.addEventListener('click', async () => {
      submit.disabled = true;
      try {
        const result = await onSubmit();
        if (result !== false) closeModal();
      } catch (err) {
        toast(err.message || '操作失败', 'error');
      } finally {
        submit.disabled = false;
      }
    });
  }
  return root;
}

function modalForm(title, fields, values, onSubmit, opts = {}) {
  const html = fields.map((f) => fieldHTML(f, values[f.name])).join('');
  openModal(title, html || '<div class="muted">没有可编辑的字段</div>', {
    ...opts,
    onSubmit: async () => {
      const data = {};
      for (const f of fields) {
        const el = document.getElementById('f_' + f.name);
        if (!el) continue;
        if (f.type === 'checks') {
          data[f.name] = $$(`input[data-name="${f.name}"]:checked`).map((x) => x.value);
        } else if (f.type === 'checkbox') data[f.name] = el.checked;
        else if (f.type === 'number') data[f.name] = el.value === '' ? null : Number(el.value);
        else if (f.type === 'image') {
          const file = el.files && el.files[0];
          if (file) data[f.name] = await uploadMedia(file);
          else data[f.name] = document.getElementById('v_' + f.name)?.value || '';
        } else data[f.name] = el.value;
      }
      return onSubmit(data);
    },
  });
}

function fieldHTML(f, value) {
  const v = value === undefined || value === null ? (f.value ?? '') : value;
  let control = '';
  if (f.type === 'textarea') {
    control = `<textarea class="input" id="f_${f.name}" rows="${f.rows || 4}" placeholder="${esc(f.placeholder || '')}">${esc(v)}</textarea>`;
  } else if (f.type === 'select') {
    const opts = (f.options || []).map((o) => {
      const val = typeof o === 'object' ? o.value : o;
      const label = typeof o === 'object' ? o.label : o;
      return `<option value="${esc(val)}" ${String(val) === String(v) ? 'selected' : ''}>${esc(label)}</option>`;
    }).join('');
    control = `<select class="input" id="f_${f.name}">${opts}</select>`;
  } else if (f.type === 'checkbox') {
    control = `<label class="row" style="gap:8px"><input type="checkbox" id="f_${f.name}" ${v ? 'checked' : ''}> <span>${esc(f.checkboxLabel || '启用')}</span></label>`;
  } else if (f.type === 'checks') {
    const selected = new Set((Array.isArray(v) ? v : String(v || '').split(',')).map(String));
    control = `<div class="row wrap" style="gap:12px">${(f.options || []).map((o) => {
      const val = typeof o === 'object' ? o.value : o;
      const label = typeof o === 'object' ? o.label : o;
      return `<label class="row" style="gap:6px"><input type="checkbox" data-name="${f.name}" value="${esc(val)}" ${selected.has(String(val)) ? 'checked' : ''}> ${esc(label)}</label>`;
    }).join('')}<span class="hint">不勾选 = 全局渠道</span></div>`;
  } else if (f.type === 'image') {
    control = `<div class="row wrap"><input type="hidden" id="v_${f.name}" value="${esc(v)}">
      <input class="input" id="f_${f.name}" type="file" accept="image/*" style="flex:1;min-width:220px"
        onchange="const p=document.getElementById('prev_${f.name}');if(p&&this.files[0])p.src=URL.createObjectURL(this.files[0])">
      <img id="prev_${f.name}" src="${esc(v)}" style="width:44px;height:44px;object-fit:cover;border-radius:8px;border:1px solid var(--line);${v ? '' : 'display:none'}">
      </div><div class="hint">上传新图会覆盖当前图片；支持 PNG/JPEG/GIF/WEBP，≤5MB</div>`;
  } else {
    control = `<input class="input" id="f_${f.name}" type="${f.type || 'text'}" value="${esc(v)}" placeholder="${esc(f.placeholder || '')}" ${f.step ? `step="${f.step}"` : ''}>`;
  }
  return `<div class="field"><label for="f_${f.name}">${esc(f.label)}</label>${control}${f.help ? `<div class="hint">${esc(f.help)}</div>` : ''}</div>`;
}

async function uploadMedia(file) {
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch('/api/media/upload', { method: 'POST', body: fd, credentials: 'same-origin' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) throw new Error(data.error || '图片上传失败');
  return data.url;
}

function confirmAction(message, danger = true) {
  return new Promise((resolve) => {
    openModal('请确认', `<div style="font-size:14px">${esc(message)}</div>`, {
      submitText: danger ? '删除' : '确定',
      onSubmit: async () => { resolve(true); },
      footExtra: '',
    });
    const cancel = $$('#modal-root [data-close]');
    cancel.forEach((el) => el.addEventListener('click', () => resolve(false)));
  });
}

/* ------------------------------------------------------------------ auth screens */
function renderAuthCard(inner) {
  const app = $('#app');
  app.className = '';
  app.innerHTML = `<div class="auth-screen"><div class="auth-card">
    <div class="auth-brand"><div class="logo">🐟</div><div><h1>FishAutoPro Clone</h1>
      <p>闲鱼自动化交付工作台 · 自托管版</p></div></div>
    ${inner}
    <div class="auth-hint">本系统为独立实现，用于本地演示与二次开发。<br>首次部署请设置强密码，并在设置中配置 AI 服务。</div>
  </div></div>`;
}

function renderLogin() {
  $('#boot').classList.add('hidden');
  renderAuthCard(`
    <h2>登录</h2>
    <form id="login-form">
      <div class="field"><label>用户名</label><input class="input" id="login-user" autocomplete="username" value="admin"></div>
      <div class="field"><label>密码</label><input class="input" id="login-pass" type="password" autocomplete="current-password"></div>
      <button class="btn primary" style="width:100%;justify-content:center" type="submit">进入工作台</button>
    </form>`);
  $('#login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const data = await api('/auth/login', { method: 'POST', body: { username: $('#login-user').value.trim(), password: $('#login-pass').value }, noRedirect: true });
      state.user = data.user;
      renderShell();
      location.hash = '#/dashboard';
      route();
      toast('欢迎回来，' + data.user.username, 'ok');
    } catch (err) {
      toast(err.message, 'error');
    }
  });
}

function renderSetup() {
  $('#boot').classList.add('hidden');
  renderAuthCard(`
    <h2>初始化管理员</h2>
    <form id="setup-form">
      <div class="field"><label>管理员用户名</label><input class="input" id="setup-user" value="admin" autocomplete="username"></div>
      <div class="field"><label>密码（至少 6 位）</label><input class="input" id="setup-pass" type="password" autocomplete="new-password"></div>
      <div class="field"><label>确认密码</label><input class="input" id="setup-pass2" type="password" autocomplete="new-password"></div>
      <div class="field"><label class="row" style="gap:8px"><input type="checkbox" id="setup-seed" checked> <span>同时载入演示数据（账号 / 商品 / 规则）</span></label></div>
      <button class="btn primary" style="width:100%;justify-content:center" type="submit">开始使用</button>
    </form>`);
  $('#setup-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    if ($('#setup-pass').value !== $('#setup-pass2').value) return toast('两次密码不一致', 'error');
    try {
      const data = await api('/setup', {
        method: 'POST', noRedirect: true,
        body: { username: $('#setup-user').value.trim(), password: $('#setup-pass').value, seed_demo: $('#setup-seed').checked },
      });
      state.user = data.user;
      renderShell();
      location.hash = '#/dashboard';
      route();
      toast('初始化完成', 'ok');
    } catch (err) {
      toast(err.message, 'error');
    }
  });
}

/* ------------------------------------------------------------------ shell / router */
const NAV = [
  { group: '运营', items: [
    ['dashboard', '总览', '📊'],
    ['accounts', '账号管理', '👤'],
    ['goods', '商品管理', '📦'],
    ['publish', '商品发布', '🚀'],
    ['orders', '订单管理', '🧾'],
    ['movie', '电影票', '🎬'],
    ['buyers', '买家标签', '🏷️'],
    ['conversations', '会话中心', '💬'],
  ]},
  { group: '自动化', items: [
    ['autoreply', '自动回复', '🤖'],
    ['autosell', '自动发货', '🚚'],
    ['monitor', '商品监控', '🛰️'],
    ['relist', '自动补货', '🔁'],
    ['jobs', '定时任务', '⏱️'],
    ['workflows', '流程编排', '🧩'],
    ['knowledge', '知识库', '📚'],
  ]},
  { group: '系统', items: [
    ['notifications', '通知渠道', '🔔'],
    ['simulator', '联调模拟器', '🧪'],
    ['users', '用户管理', '🧑‍💼'],
    ['sessions', '登录设备', '💻'],
    ['settings', '设置', '⚙️'],
    ['audit', '操作日志', '📜'],
  ]},
];

const PAGE_META = {
  dashboard: ['总览', '账号、订单与自动化运行概览'],
  accounts: ['账号管理', '接入闲鱼账号并管理在线状态'],
  goods: ['商品管理', '在售商品与库存'],
  publish: ['商品发布', '素材库、单个/批量发布与发布日志'],
  orders: ['订单管理', '拉取、发货、重试与交付日志'],
  movie: ['电影票', '电影票订单、出票状态与取票码'],
  buyers: ['买家标签', '买家分层标签与备注'],
  conversations: ['会话中心', '买家消息、人工回复与 AI 接管'],
  autoreply: ['自动回复', '精确 / 关键词 / 正则规则与 AI 兜底'],
  autosell: ['自动发货', '固定内容、库存卡密、API 与流程发货'],
  monitor: ['商品监控', '关键词监控、上新与降价采集'],
  relist: ['自动补货', '下架/售罄商品定时重新上架'],
  jobs: ['定时任务', '订单同步、监控、补货与备份的周期任务'],
  workflows: ['流程编排', '节点式交付流程与运行记录'],
  knowledge: ['知识库', '文档分块、关键词检索与 AI 参考'],
  notifications: ['通知渠道', 'Bark / Telegram / Webhook / 邮件'],
  simulator: ['联调模拟器', '模拟买家消息、下单与监控数据'],
  users: ['用户管理', '账号、角色与数据归属'],
  sessions: ['登录设备', '当前账号的登录会话与吊销'],
  settings: ['设置', 'AI 服务与系统信息'],
  audit: ['操作日志', '系统审计与自动化事件'],
};

function renderShell() {
  $('#boot').classList.add('hidden');
  const app = $('#app');
  app.className = 'app';
  const adminKeys = new Set(['users', 'settings']);
  const nav = NAV.map((g) => `<div class="nav-group">${g.group}</div>` + g.items
    .filter(([key]) => state.user?.role === 'admin' || !adminKeys.has(key))
    .map(([key, label, ico]) => `<a href="#/${key}" data-page="${key}"><span class="ico">${ico}</span>${label}${key === 'conversations' ? '<span id="nav-unread" class="badge red" style="margin-left:auto;display:none"></span>' : ''}</a>`).join('')).join('');
  app.innerHTML = `
    <aside class="sidebar">
      <div class="brand"><div class="mark">🐟</div><div><div class="name">FishAutoPro</div><div class="sub">Clone · self-hosted</div></div></div>
      <nav class="nav">${nav}</nav>
      <div class="sidebar-foot"><div class="user-chip">
        <div class="avatar">${esc((state.user?.username || 'A').slice(0, 1).toUpperCase())}</div>
        <div class="who"><b>${esc(state.user?.username || '')}</b><span>${esc(state.user?.role || '')}</span></div>
        <button class="icon-btn" title="修改密码" onclick="App.passwordModal()">🔑</button>
        <button class="icon-btn" title="退出登录" onclick="App.logout()">⏻</button>
      </div></div>
    </aside>
    <div class="main">
      <header class="topbar"><div><div class="crumb" id="crumb">工作台</div><h1 id="page-title">总览</h1></div>
        <div class="spacer"></div>
        <span class="badge teal"><span class="dot"></span> 本地模式</span>
        <span class="badge blue">v1.0</span>
      </header>
      <main class="content" id="view"><div class="empty"><span class="big">⏳</span>加载中…</div></main>
    </div>`;
  App.refreshUnread();
  App.startPolling();
}

function route() {
  if (!state.user) return;
  const raw = (location.hash || '#/dashboard').replace(/^#\/?/, '');
  let page = PAGE_META[raw] ? raw : 'dashboard';
  if (state.user.role !== 'admin' && ['users', 'settings'].includes(page)) page = 'dashboard';
  state.page = page;
  const [title, crumb] = PAGE_META[page];
  $('#page-title').textContent = title;
  $('#crumb').textContent = crumb;
  $$('.nav a').forEach((a) => a.classList.toggle('active', a.dataset.page === page));
  const view = $('#view');
  view.innerHTML = '<div class="empty"><span class="big">⏳</span>加载中…</div>';
  const fn = PAGES[page];
  if (!fn) { view.innerHTML = '<div class="empty">页面不存在</div>'; return; }
  Promise.resolve(fn()).catch((err) => {
    console.error(err);
    view.innerHTML = `<div class="card card-pad"><div class="badge red">加载失败</div><p class="muted">${esc(err.message)}</p>
      <button class="btn" onclick="route()">重试</button></div>`;
  });
}

/* ------------------------------------------------------------------ shared UI */
function badgeForStatus(status) {
  const map = {
    online: ['green', '在线'], offline: ['', '离线'], error: ['red', '异常'],
    paid: ['amber', '待发货'], delivered: ['green', '已发货'], failed: ['red', '失败'], refunded: ['', '已退款'],
    on_sale: ['green', '在售'], off_shelf: ['', '已下架'],
    available: ['green', '可用'], used: ['', '已使用'],
    notify: ['blue', '通知'], dm: ['teal', '私信'], order: ['amber', '下单'],
    text: ['', '文本'], image: ['blue', '图片'], ai: ['teal', 'AI'],
    fixed: ['', '固定内容'], stock: ['blue', '库存卡密'], api: ['amber', 'API'], workflow: ['teal', '流程'],
    all: ['', '全部商品'], goods: ['blue', '指定商品'],
    exact: ['', '精确'], keyword: ['blue', '关键词'], regex: ['teal', '正则'],
    ok: ['green', '成功'], running: ['amber', '运行中'],
  };
  const [cls, label] = map[status] || ['', status || '—'];
  return `<span class="badge ${cls}">${esc(label)}</span>`;
}

function statCard(label, value, sub, icon) {
  return `<div class="card stat"><div class="row"><span class="label">${esc(label)}</span><div class="spacer"></div>
    <span class="ico">${icon}</span></div><div class="value">${esc(value)}</div><div class="delta">${esc(sub || '')}</div></div>`;
}

function emptyRow(cols, text = '暂无数据') {
  return `<tr><td colspan="${cols}"><div class="empty"><span class="big">🗂️</span>${esc(text)}</div></td></tr>`;
}

function selectOptions(items, valueKey, labelKey, selected, emptyLabel) {
  let html = emptyLabel ? `<option value="">${esc(emptyLabel)}</option>` : '';
  for (const it of items) {
    html += `<option value="${esc(it[valueKey])}" ${String(it[valueKey]) === String(selected ?? '') ? 'selected' : ''}>${esc(it[labelKey])}</option>`;
  }
  return html;
}

function openConfirmDelete(message, fn) {
  openModal('确认删除', `<div>${esc(message)}</div>`, {
    submitText: '删除',
    onSubmit: async () => { await fn(); toast('已删除', 'ok'); route(); },
  });
}

/* ------------------------------------------------------------------ pages */
const PAGES = {};

/* ---------- dashboard ---------- */
PAGES.dashboard = async () => {
  const range = state.dashDays || 7;
  const data = await api(`/dashboard?days=${range}`);
  const s = data.stats;
  const max = Math.max(1, ...data.days.map((d) => Math.max(d.orders, d.delivered)));
  const chart = data.days.map((d) => `
    <div class="bar-wrap"><div class="bars">
      <div class="bar" style="height:${Math.max(3, d.orders / max * 100)}%" title="订单 ${d.orders}"></div>
      <div class="bar delivered" style="height:${Math.max(3, d.delivered / max * 100)}%" title="已发货 ${d.delivered}"></div>
    </div><div class="cap">${esc(d.date.slice(5))}</div></div>`).join('');
  const orders = data.recent_orders.map((o) => `
    <tr><td class="mono small">${esc(o.order_no)}</td><td>${esc(o.goods_title || '—')}</td><td>${esc(o.buyer)}</td>
    <td>${money(o.amount)}</td><td>${badgeForStatus(o.status)}</td><td class="small muted">${fmtTime(o.created_at)}</td></tr>`).join('');
  const messages = data.recent_messages.map((m) => `
    <div class="conv-item" style="cursor:default"><div class="top"><b>${esc(m.buyer || '买家')}</b>
      <span class="spacer"></span><span class="small muted">${fmtTime(m.created_at)}</span></div>
      <div class="preview">${m.direction === 'out' ? '我：' : ''}${esc(m.content)}</div></div>`).join('');

  $('#view').innerHTML = `
    <div class="row" style="margin-bottom:12px"><span class="hint">经营概览</span><div class="spacer"></div>
      <button class="btn sm ${range === 7 ? 'primary' : ''}" onclick="App.dashboard.range(7)">近 7 天</button>
      <button class="btn sm ${range === 30 ? 'primary' : ''}" onclick="App.dashboard.range(30)">近 30 天</button></div>
    <div class="grid cols-4">
      ${statCard('在线账号', `${s.accounts_online}/${s.accounts}`, '账号连接状态', '👤')}
      ${statCard(`近 ${range} 天订单`, s.orders_range, `待发货 ${s.orders_pending} · 失败 ${s.orders_failed}`, '🧾')}
      ${statCard(`近 ${range} 天收入`, money(s.revenue_range), `退款 ${money(s.refund_amount_range)}`, '💰')}
      ${statCard('库存卡密', s.stock_available, `未读消息 ${s.unread}`, '🔑')}
    </div>
    <div class="grid cols-2" style="margin-top:16px">
      <div class="card"><div class="card-head"><h3>近 ${range} 天订单</h3><div class="spacer"></div>
        <span class="badge blue">订单</span><span class="badge amber">已发货</span></div>
        <div class="card-pad"><div class="chart">${chart}</div></div></div>
      <div class="card"><div class="card-head"><h3>最近消息</h3><div class="spacer"></div>
        <a class="btn sm" href="#/conversations">进入会话</a></div>
        <div style="max-height:210px;overflow:auto">${messages || '<div class="empty">暂无消息</div>'}</div></div>
    </div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>最近订单</h3><div class="spacer"></div>
      <a class="btn sm" href="#/orders">查看全部</a></div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th>订单号</th><th>商品</th><th>买家</th><th>金额</th><th>状态</th><th>时间</th></tr></thead>
      <tbody>${orders || emptyRow(6, '还没有订单，去模拟器下一单试试')}</tbody></table></div></div>`;
};

/* ---------- accounts ---------- */
PAGES.accounts = async () => {
  const { accounts } = await api('/accounts');
  const rows = accounts.map((a) => `
    <tr><td><input type="checkbox" class="acc-check" value="${a.id}"></td>
      <td><b style="cursor:pointer" onclick="App.accounts.detail(${a.id})">${esc(a.name)}</b>${a.nickname ? ` <span class="badge teal">${esc(a.nickname)}</span>` : ''}
      <div class="small muted">${[a.platform_user_id ? 'ID ' + a.platform_user_id : '', a.note || ''].filter(Boolean).map(esc).join(' · ')}</div></td>
      <td>${badgeForStatus(a.status)}</td><td>${a.goods_count}</td><td>${a.order_count}</td>
      <td>${a.ai_enabled ? '<span class="badge teal">开启</span>' : '<span class="badge">关闭</span>'}</td>
      <td class="small muted">${fmtTime(a.last_seen_at)}</td>
      <td class="actions">
        ${a.status === 'online'
          ? `<button class="btn sm" onclick="App.accounts.disconnect(${a.id})">断开</button>`
          : `<button class="btn sm primary" onclick="App.accounts.connect(${a.id})">连接</button>`}
        ${!String(a.cookie || '').startsWith('demo') ? `<button class="btn sm" onclick="App.accounts.qr(${a.id})">扫码</button>
        <button class="btn sm" onclick="App.accounts.mtop(${a.id})">mtop</button>
        <button class="btn sm" onclick="App.accounts.wsTest(${a.id})">WS</button>
        <button class="btn sm" onclick="App.accounts.polish(${a.id})">擦亮</button>
        <button class="btn sm" onclick="App.accounts.proxyTest(${a.id})">测代理</button>
        <button class="btn sm" onclick="App.accounts.refreshInfo(${a.id})">资料</button>` : ''}
        <button class="btn sm" onclick="App.accounts.edit(${a.id})">编辑</button>
        <button class="btn sm danger" onclick="App.accounts.remove(${a.id})">删除</button>
      </td></tr>`).join('');
  $('#view').innerHTML = `
    <div class="card"><div class="card-head"><h3>账号列表</h3><div class="spacer"></div>
      <button class="btn sm" onclick="App.accounts.batch('connect')">批量连接</button>
      <button class="btn sm" onclick="App.accounts.batch('disconnect')">批量断开</button>
      <button class="btn sm" onclick="App.accounts.batch('enable')">批量启用</button>
      <button class="btn sm" onclick="App.accounts.batch('disable')">批量停用</button>
      <a class="btn sm" href="/api/accounts/export">导出 JSON</a>
      <button class="btn sm" onclick="App.accounts.encryptedExport()">加密导出</button>
      <button class="btn sm" onclick="$('#acc-import').click()">导入 JSON</button>
      <input type="file" id="acc-import" accept=".json,application/json" style="display:none"
        onchange="App.accounts.importFile(this)">
      <button class="btn primary" onclick="App.accounts.create()">＋ 新建账号</button></div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th><input type="checkbox" id="acc-all" onchange="App.accounts.selectAll(this.checked)"></th><th>账号</th><th>状态</th><th>商品</th><th>订单</th><th>AI</th><th>最近在线</th><th></th></tr></thead>
      <tbody>${rows || emptyRow(8, '还没有账号')}</tbody></table></div></div>
    <div class="card card-pad" style="margin-top:16px"><b>接入说明</b>
      <p class="muted small" style="margin:8px 0 0">Cookie 以 <span class="mono">demo</span> 开头为本地 Mock 账号。
      真实账号可点「扫码」调用闲鱼 passport 二维码登录，扫码确认后自动校验登录态并保存 Cookie；
      「mtop」可诊断商品详情接口（已实现签名/令牌重试/搜索），消息与订单同步仍需 WebSocket/更多接口。</p></div>`;
  state.accounts = accounts;
};

/* ---------- goods ---------- */
PAGES.goods = async () => {
  const qs = new URLSearchParams();
  if (state.goodsQuery) qs.set('q', state.goodsQuery);
  if (state.goodsStatus) qs.set('status', state.goodsStatus);
  const [{ goods }, { accounts }] = await Promise.all([
    api(`/goods${qs.toString() ? '?' + qs : ''}`), api('/accounts')]);
  state.accounts = accounts;
  const rows = goods.map((g) => `
    <tr><td><div class="row" style="gap:10px">${g.image_url ? `<img src="${esc(g.image_url)}" alt="" style="width:38px;height:38px;object-fit:cover;border-radius:8px;border:1px solid var(--line)">` : ''}
      <div><b>${esc(g.title)}</b><div class="small muted">${esc((g.description || '').slice(0, 60))}</div></div></div></td>
      <td>${esc(g.account_name || '—')}</td><td>${money(g.price)}</td><td>${g.stock}</td>
      <td>${badgeForStatus(g.status)}</td><td class="small muted">${fmtDate(g.created_at)}</td>
      <td class="actions"><button class="btn sm" onclick="App.goods.edit(${g.id})">编辑</button>
      ${g.status === 'on_sale' ? `<button class="btn sm amber" onclick="App.goods.offline(${g.id})">下架</button>` : ''}
      <button class="btn sm danger" onclick="App.goods.remove(${g.id})">删除</button></td></tr>`).join('');
  const tabs = [['', '全部'], ['on_sale', '在售'], ['off_shelf', '已下架']].map(([v, label]) =>
    `<button class="btn sm ${(state.goodsStatus || '') === v ? 'primary' : ''}" onclick="App.goods.filterStatus('${v}')">${label}</button>`).join('');
  $('#view').innerHTML = `
    <div class="card"><div class="card-head"><h3>商品列表</h3><div class="spacer"></div>
      <a class="btn" href="/api/exports/goods.xlsx">导出 XLSX</a>
      <button class="btn amber" onclick="App.goods.offlineAll()">全部下架</button>
      <button class="btn primary" onclick="App.goods.create()">＋ 新建商品</button></div>
      <div class="row" style="padding:0 16px 12px;gap:8px;flex-wrap:wrap">${tabs}
        <div class="spacer"></div>
        <input class="input" style="max-width:260px" placeholder="搜索商品标题" value="${esc(state.goodsQuery || '')}"
          onkeydown="if(event.key==='Enter'){App.goods.search(this.value)}"></div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th>商品</th><th>账号</th><th>价格</th><th>库存</th><th>状态</th><th>创建</th><th></th></tr></thead>
      <tbody>${rows || emptyRow(7, '没有匹配的商品')}</tbody></table></div></div>`;
  state.goods = goods;
};

/* ---------- publish ---------- */
PAGES.publish = async () => {
  const [mData, logData, accData] = await Promise.all([api('/materials'), api('/product-publish/logs'), api('/accounts')]);
  state.materials = mData.materials;
  state.accounts = accData.accounts;
  const rows = mData.materials.map((m) => `
    <tr><td><input type="checkbox" class="pub-check" value="${m.id}"></td>
      <td><div class="row" style="gap:10px">${m.image_url ? `<img src="${esc(m.image_url)}" style="width:36px;height:36px;object-fit:cover;border-radius:8px">` : ''}
      <div><b>${esc(m.title)}</b><div class="small muted">${esc(m.name)}</div></div></div></td>
      <td>${esc(m.account_name || '—')}</td><td>${money(m.price)}</td><td>${m.stock}</td>
      <td class="actions"><button class="btn sm primary" onclick="App.publish.publish(${m.id})">发布</button>
      <button class="btn sm" onclick="App.publish.edit(${m.id})">编辑</button>
      <button class="btn sm danger" onclick="App.publish.remove(${m.id})">删除</button></td></tr>`).join('');
  const logs = logData.logs.slice(0, 40).map((l) => `<tr><td class="small muted">${fmtTime(l.created_at)}</td>
    <td>${esc(l.material_name || '—')}</td><td>${esc(l.account_name || '—')}</td>
    <td>${l.status === 'success' ? '<span class="badge green">成功</span>' : '<span class="badge red">失败</span>'}</td>
    <td class="small mono">${esc(l.item_id || l.message || '')}</td>
    <td>${l.goods_id ? `#${l.goods_id}` : '—'}</td></tr>`).join('');
  $('#view').innerHTML = `
    <div class="card"><div class="card-head"><h3>素材库</h3><div class="spacer"></div>
      <button class="btn" onclick="App.publish.publishSelected()">发布选中</button>
      <button class="btn primary" onclick="App.publish.create()">＋ 新建素材</button></div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th style="width:34px"></th><th>素材</th><th>账号</th><th>价格</th><th>库存</th><th></th></tr></thead>
      <tbody>${rows || emptyRow(6, '还没有素材')}</tbody></table></div></div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>发布日志</h3></div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th>时间</th><th>素材</th><th>账号</th><th>结果</th><th>平台 Item ID</th><th>商品</th></tr></thead>
      <tbody>${logs || emptyRow(6, '暂无发布记录')}</tbody></table></div></div>`;
};

/* ---------- relist ---------- */
PAGES.relist = async () => {
  const [rData, logData, gData, mData] = await Promise.all([
    api('/auto-relist/rules'), api('/auto-relist/logs'), api('/goods'), api('/materials')]);
  state.relistRules = rData.rules;
  state.goods = gData.goods;
  state.materials = mData.materials;
  const rows = rData.rules.map((r) => `
    <tr><td><b>${esc(r.goods_title || '商品已删除')}</b><div class="small muted">${badgeForStatus(r.goods_status)} 库存 ${r.goods_stock ?? '—'}</div></td>
      <td>${esc(r.material_name || '—')}</td><td>${r.interval_seconds}s</td>
      <td>${r.enabled ? '<span class="badge green">启用</span>' : '<span class="badge">停用</span>'}</td>
      <td class="small muted">${fmtTime(r.last_run_at)}</td>
      <td class="actions"><button class="btn sm primary" onclick="App.relist.run(${r.id})">立即补货</button>
      <button class="btn sm" onclick="App.relist.edit(${r.id})">编辑</button>
      <button class="btn sm danger" onclick="App.relist.remove(${r.id})">删除</button></td></tr>`).join('');
  const logs = logData.logs.slice(0, 40).map((l) => `<tr><td class="small muted">${fmtTime(l.created_at)}</td>
    <td>${esc(l.goods_title || '—')}</td><td>${l.status === 'success' ? '<span class="badge green">已补货</span>' : l.status === 'skipped' ? '<span class="badge">跳过</span>' : '<span class="badge red">失败</span>'}</td>
    <td class="small">${esc(l.message)}</td></tr>`).join('');
  $('#view').innerHTML = `
    <div class="card"><div class="card-head"><h3>补货规则</h3><div class="spacer"></div>
      <button class="btn primary" onclick="App.relist.create()">＋ 新建规则</button></div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th>商品</th><th>素材</th><th>间隔</th><th>状态</th><th>最近运行</th><th></th></tr></thead>
      <tbody>${rows || emptyRow(6, '还没有补货规则')}</tbody></table></div></div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>补货日志</h3></div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th>时间</th><th>商品</th><th>结果</th><th>说明</th></tr></thead>
      <tbody>${logs || emptyRow(4, '暂无补货记录')}</tbody></table></div></div>`;
};

/* ---------- orders ---------- */
PAGES.movie = async () => {
  const qs = new URLSearchParams();
  if (state.movieQuery) qs.set('q', state.movieQuery);
  if (state.movieStatus) qs.set('status', state.movieStatus);
  const suffix = qs.toString() ? '?' + qs : '';
  const { tickets } = await api('/movie-tickets' + suffix);
  const statuses = [['pending', '待支付'], ['paid', '已支付'], ['used', '已核销'], ['refunded', '已退款'], ['cancelled', '已取消']];
  const paidCount = tickets.filter((t) => t.status === 'paid').length;
  const usedCount = tickets.filter((t) => t.status === 'used').length;
  const revenue = tickets.filter((t) => ['paid', 'used'].includes(t.status)).reduce((s, t) => s + (t.amount || 0), 0);
  const rows = tickets.map((t) => `<tr>
    <td class="mono small">${esc(t.order_no)}</td>
    <td><b>${esc(t.movie_name)}</b><div class="small muted">${esc(t.cinema || '—')}</div></td>
    <td class="small">${esc(t.show_time || '—')}</td>
    <td class="small">${esc(t.seats || '—')}</td>
    <td>${t.quantity}</td><td>${money(t.amount)}</td><td>${esc(t.buyer || '—')}</td>
    <td><select class="input" style="max-width:110px" onchange="App.movie.status(${t.id}, this.value)">
      ${statuses.map(([v, label]) => `<option value="${v}" ${t.status === v ? 'selected' : ''}>${label}</option>`).join('')}
    </select>${t.used_at ? `<div class="small muted">${fmtTime(t.used_at)}</div>` : ''}</td>
    <td class="actions">${t.status === 'paid' ? `<button class="btn sm primary" onclick="App.movie.verify(${t.id})">核销</button>` : ''}
      <button class="btn sm" onclick="App.movie.qr(${t.id})">票码</button>
      <button class="btn sm" onclick="App.movie.form(${t.id})">编辑</button>
      <button class="btn sm danger" onclick="App.movie.remove(${t.id})">删除</button></td></tr>`).join('');
  $('#view').innerHTML = `<div class="card"><div class="card-head"><h3>电影票订单</h3>
      <span class="badge">共 ${tickets.length}</span><span class="badge teal">已支付 ${paidCount}</span>
      <span class="badge green">已核销 ${usedCount}</span><span class="badge blue">票款 ${money(revenue)}</span>
      <div class="spacer"></div>
      <a class="btn" href="/api/movie-tickets.xlsx${suffix}">导出 XLSX</a>
      <button class="btn primary" onclick="App.movie.form()">＋ 新建电影票</button></div>
    <div class="row" style="padding:0 16px 12px;gap:8px;flex-wrap:wrap">
      <input class="input" style="max-width:240px" placeholder="订单号 / 影片 / 买家" value="${esc(state.movieQuery || '')}"
        onkeydown="if(event.key==='Enter'){App.movie.search(this.value)}">
      <select class="input" style="max-width:140px" onchange="App.movie.filter(this.value)">
        <option value="">全部状态</option>${statuses.map(([v, label]) => `<option value="${v}" ${state.movieStatus === v ? 'selected' : ''}>${label}</option>`).join('')}
      </select>
    </div>
    <div class="table-wrap"><table class="tbl"><thead><tr><th>订单号</th><th>影片</th><th>场次</th><th>座位</th>
      <th>数量</th><th>金额</th><th>买家</th><th>状态</th><th></th></tr></thead>
    <tbody>${rows || emptyRow(9, '还没有电影票订单')}</tbody></table></div></div>`;
  state.movieTickets = tickets;
};

PAGES.orders = async () => {
  const status = state.orderFilter || '';
  const q = state.orderQuery || '';
  const statsDays = state.orderStatsDays || 0;
  const [{ orders }, stats] = await Promise.all([
    api(`/orders?status=${encodeURIComponent(status)}&q=${encodeURIComponent(q)}`),
    api('/orders/stats' + (statsDays ? `?days=${statsDays}` : ''))]);
  const rows = orders.map((o) => `
    <tr><td class="mono small">${esc(o.order_no)}</td><td>${esc(o.goods_title || '—')}</td><td>${esc(o.buyer)}</td>
      <td>${o.quantity}</td><td>${money(o.amount)}</td><td>${badgeForStatus(o.status)}${o.refund_status ? `<span class="badge amber" style="margin-left:6px">退款 ${esc(o.refund_status)}</span>` : ''}</td>
      <td class="small muted">${fmtTime(o.created_at)}</td>
      <td class="actions">
        <button class="btn sm" onclick="App.orders.detail(${o.id})">详情</button>
        ${o.status === 'paid' ? `<button class="btn sm primary" onclick="App.orders.deliver(${o.id},false)">发货</button>` : ''}
        ${o.status === 'failed' ? `<button class="btn sm amber" onclick="App.orders.deliver(${o.id},true)">重试</button>` : ''}
        <button class="btn sm danger" onclick="App.orders.remove(${o.id})">删除</button>
      </td></tr>`).join('');
  const tabs = [['', '全部'], ['paid', '待发货'], ['delivered', '已发货'], ['failed', '失败']].map(([v, l]) => {
    const n = v ? ((stats.by_status[v] || {}).count || 0) : stats.total;
    return `<button class="${status === v ? 'active' : ''}" onclick="App.orders.filter('${v}')">${l} <span class="badge">${n}</span></button>`;
  }).join('');
  $('#view').innerHTML = `
    <div class="row" style="margin-bottom:14px"><div class="tabs">${tabs}</div>
      <select class="input" style="max-width:120px" onchange="App.orders.statsDays(this.value)">
        <option value="0">全部时间</option>
        <option value="7" ${statsDays == 7 ? 'selected' : ''}>近 7 天</option>
        <option value="30" ${statsDays == 30 ? 'selected' : ''}>近 30 天</option>
      </select><div class="spacer"></div>
      <button class="btn" onclick="App.orders.syncModal()">同步订单</button>
      <button class="btn" onclick="App.orders.syncListModal()">同步列表</button>
      <a class="btn" href="/api/exports/orders.xlsx">导出 XLSX</a>
      <input class="input" id="order-q" style="width:240px" placeholder="订单号 / 买家 / 商品 / 备注" value="${esc(q)}"
        onkeydown="if(event.key==='Enter'){App.orders.search(this.value)}">
      <button class="btn" onclick="App.orders.search(document.getElementById('order-q').value)">刷新</button></div>
    <div class="card"><div class="table-wrap"><table class="tbl"><thead><tr><th>订单号</th><th>商品</th><th>买家</th><th>数量</th><th>金额</th><th>状态</th><th>时间</th><th></th></tr></thead>
      <tbody>${rows || emptyRow(8, '没有符合条件的订单')}</tbody></table></div></div>`;
};

/* ---------- conversations ---------- */
PAGES.buyers = async () => {
  const qs = new URLSearchParams();
  if (state.buyerQuery) qs.set('q', state.buyerQuery);
  const suffix = qs.toString() ? '?' + qs : '';
  const [{ tags }, { blacklist }] = await Promise.all([
    api('/buyer-tags' + suffix), api('/buyer-blacklist' + suffix)]);
  const rows = tags.map((t) => `<tr><td><b>${esc(t.buyer)}</b></td>
    <td><span class="badge teal">${esc(t.tag)}</span></td><td class="small">${esc(t.note || '—')}</td>
    <td class="small muted">${fmtTime(t.updated_at)}</td>
    <td class="actions"><button class="btn sm danger" onclick="App.buyerTags.remove(${t.id})">删除</button></td></tr>`).join('');
  const blocked = blacklist.map((b) => `<tr><td><b>${esc(b.buyer)}</b></td>
    <td class="small">${esc(b.reason || '—')}</td><td class="small muted">${fmtTime(b.created_at)}</td>
    <td class="actions"><button class="btn sm danger" onclick="App.buyerTags.removeBlacklist(${b.id})">移出</button></td></tr>`).join('');
  $('#view').innerHTML = `<div class="card"><div class="card-head"><h3>买家标签</h3><div class="spacer"></div>
      <button class="btn primary" onclick="App.buyerTags.form()">＋ 新建标签</button></div>
    <div class="row" style="padding:0 16px 12px"><input class="input" style="max-width:260px"
      placeholder="买家 / 标签 / 备注" value="${esc(state.buyerQuery || '')}"
      onkeydown="if(event.key==='Enter'){App.buyerTags.search(this.value)}"></div>
    <div class="table-wrap"><table class="tbl"><thead><tr><th>买家</th><th>标签</th><th>备注</th><th>更新时间</th><th></th></tr></thead>
    <tbody>${rows || emptyRow(5, '还没有买家标签')}</tbody></table></div></div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>自动回复黑名单</h3><div class="spacer"></div>
      <button class="btn amber" onclick="App.buyerTags.addBlacklist()">＋ 拉黑买家</button></div>
    <div class="table-wrap"><table class="tbl"><thead><tr><th>买家</th><th>原因</th><th>加入时间</th><th></th></tr></thead>
    <tbody>${blocked || emptyRow(4, '黑名单为空')}</tbody></table></div></div>`;
};

PAGES.conversations = async () => {
  const qs = new URLSearchParams();
  if (state.convQuery) qs.set('q', state.convQuery);
  if (state.convUnread) qs.set('unread', '1');
  if (state.convTag) qs.set('tag', state.convTag);
  const [{ conversations }, { tags }] = await Promise.all([
    api(`/conversations${qs.toString() ? '?' + qs : ''}`), api('/buyer-tags')]);
  state.conversations = conversations;
  const tagNames = [...new Set(tags.map((t) => t.tag))];
  const toolbar = `<div class="row" style="margin-bottom:12px;gap:8px;flex-wrap:wrap">
    <input class="input" style="max-width:260px" placeholder="搜索买家 / 消息" value="${esc(state.convQuery || '')}"
      onkeydown="if(event.key==='Enter'){App.chat.search(this.value)}">
    <button class="btn ${state.convUnread ? 'primary' : ''}" onclick="App.chat.toggleUnread()">只看未读</button>
    <select class="input" style="max-width:140px" onchange="App.chat.filterTag(this.value)">
      <option value="">全部标签</option>${tagNames.map((t) => `<option value="${esc(t)}" ${state.convTag === t ? 'selected' : ''}>${esc(t)}</option>`).join('')}
    </select>
    <button class="btn" onclick="App.chat.markAllRead()">全部已读</button>
    <span class="hint">会话与消息保存在本地，可随时导出</span>
    <div class="spacer"></div><a class="btn" href="/api/exports/messages.xlsx">导出全部消息 XLSX</a></div>`;
  if (!conversations.length) {
    $('#view').innerHTML = toolbar + `<div class="card"><div class="empty"><span class="big">💬</span>没有匹配的会话</div></div>`;
    return;
  }
  if (!state.convId || !conversations.find((c) => c.id === state.convId)) state.convId = conversations[0].id;
  const list = conversations.map((c) => `
    <div class="conv-item ${c.id === state.convId ? 'active' : ''}" onclick="App.chat.open(${c.id})">
      <div class="top"><b>${esc(c.buyer)}</b>${c.unread ? `<span class="badge red">${c.unread}</span>` : ''}
        ${(c.tags || '').split(',').filter(Boolean).map((t) => `<span class="badge teal">${esc(t)}</span>`).join('')}
        <span class="spacer"></span><span class="small muted">${fmtTime(c.updated_at).slice(5, 16)}</span></div>
      <div class="preview">${esc(c.last_message)}</div></div>`).join('');
  $('#view').innerHTML = `${toolbar}
    <div class="card"><div class="chat-shell">
    <div class="conv-list">${list}</div>
    <div class="chat-pane" id="chat-pane"><div class="empty">选择会话</div></div></div></div>`;
  await App.chat.open(state.convId);
};

/* ---------- auto reply ---------- */
PAGES.autoreply = async () => {
  const [{ rules }, { accounts }, { goods }] = await Promise.all([api('/autoreply/rules'), api('/accounts'), api('/goods')]);
  state.accounts = accounts; state.goods = goods; state.replyRules = rules;
  const rows = rules.map((r) => `
    <tr><td><b>${esc(r.name)}</b>${r.goods_title ? `<div class="small muted">商品：${esc(r.goods_title)}</div>` : ''}</td>
      <td>${r.account_name ? esc(r.account_name) : '<span class="muted">全部账号</span>'}</td>
      <td>${badgeForStatus(r.scope)}</td><td>${badgeForStatus(r.match_type)}<div class="small muted mono">${esc((r.pattern || '').slice(0, 40))}</div></td>
      <td>${badgeForStatus(r.reply_type)}<div class="small muted">${esc((r.content || '').slice(0, 40))}</div></td>
      <td>${r.priority}</td><td>${r.enabled ? '<span class="badge green">启用</span>' : '<span class="badge">停用</span>'}</td>
      <td class="actions"><button class="btn sm" onclick="App.reply.edit(${r.id})">编辑</button>
      <button class="btn sm danger" onclick="App.reply.remove(${r.id})">删除</button></td></tr>`).join('');
  $('#view').innerHTML = `
    <div class="card"><div class="card-head"><h3>回复规则</h3><div class="spacer"></div>
      <button class="btn primary" onclick="App.reply.create()">＋ 新建规则</button></div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th>规则</th><th>账号</th><th>范围</th><th>匹配</th><th>回复</th><th>优先级</th><th>状态</th><th></th></tr></thead>
      <tbody>${rows || emptyRow(8, '还没有回复规则')}</tbody></table></div></div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>规则测试</h3></div><div class="card-pad">
      <div class="row wrap"><input class="input" id="reply-test-text" style="flex:1;min-width:260px" placeholder="输入一条买家消息，例如：能便宜点吗？">
      <button class="btn primary" onclick="App.reply.test()">测试匹配</button></div>
      <div id="reply-test-result" style="margin-top:12px"></div></div></div>`;
};

/* ---------- auto delivery ---------- */
PAGES.autosell = async () => {
  const [{ rules }, { goods }, { workflows }, { logs }] = await Promise.all([
    api('/autosell/rules'), api('/goods'), api('/workflows'), api('/autosell/logs')]);
  state.goods = goods; state.workflows = workflows; state.sellRules = rules;
  const rows = rules.map((r) => `
    <tr><td><b>${esc(r.name)}</b></td><td>${esc(r.goods_title || '<全部商品>')}</td>
      <td>${badgeForStatus(r.delivery_type)}</td><td>${r.stock_available ?? '—'}</td>
      <td>${r.multi_quantity ? '<span class="badge blue">按数量</span>' : '—'}</td>
      <td>${r.enabled ? '<span class="badge green">启用</span>' : '<span class="badge">停用</span>'}</td>
      <td class="actions">${r.delivery_type === 'stock' ? `<button class="btn sm" onclick="App.sell.stock(${r.id})">库存</button>` : ''}
        <button class="btn sm" onclick="App.sell.preview(${r.id})">预览</button>
        <button class="btn sm" onclick="App.sell.edit(${r.id})">编辑</button>
        <button class="btn sm danger" onclick="App.sell.remove(${r.id})">删除</button></td></tr>`).join('');
  const logRows = logs.slice(0, 30).map((l) => `<tr><td class="mono small">${esc(l.order_no || '—')}</td>
    <td>${esc(l.buyer || '—')}</td><td>${l.status === 'success' ? '<span class="badge green">成功</span>' : '<span class="badge red">失败</span>'}</td>
    <td class="small"><span class="mono">${esc((l.content || l.error || '').slice(0, 80))}</span></td>
    <td class="small muted">${fmtTime(l.created_at)}</td></tr>`).join('');
  $('#view').innerHTML = `
    <div class="card"><div class="card-head"><h3>发货规则</h3><div class="spacer"></div>
      <button class="btn primary" onclick="App.sell.create()">＋ 新建规则</button></div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th>规则</th><th>商品</th><th>类型</th><th>可用库存</th><th>多数量</th><th>状态</th><th></th></tr></thead>
      <tbody>${rows || emptyRow(7, '还没有发货规则')}</tbody></table></div></div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>最近交付日志</h3></div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th>订单号</th><th>买家</th><th>结果</th><th>内容 / 错误</th><th>时间</th></tr></thead>
      <tbody>${logRows || emptyRow(5, '暂无交付记录')}</tbody></table></div></div>`;
};

/* ---------- monitor ---------- */
PAGES.monitor = async () => {
  const [{ tasks }, { items }] = await Promise.all([api('/monitor/tasks'), api('/monitor/items')]);
  state.monitorTasks = tasks;
  const rows = tasks.map((t) => `
    <tr><td><b>${esc(t.name)}</b></td><td>${esc(t.keyword)}</td>
      <td>${t.min_price ?? '—'} ~ ${t.max_price ?? '—'}</td><td>${badgeForStatus(t.action)}</td>
      <td>${t.interval_seconds}s</td><td>${t.item_count}</td><td class="small muted">${fmtTime(t.last_run_at)}</td>
      <td class="actions"><button class="btn sm primary" onclick="App.monitor.run(${t.id})">立即运行</button>
      <button class="btn sm" onclick="App.monitor.edit(${t.id})">编辑</button>
      <button class="btn sm danger" onclick="App.monitor.remove(${t.id})">删除</button></td></tr>`).join('');
  const itemRows = items.map((i) => `<tr><td>${esc(i.title)}</td><td>${money(i.price)}</td><td class="small muted">${esc(i.keyword)}</td>
    <td class="small muted">${fmtTime(i.found_at)}</td><td>${i.url ? `<a class="btn sm" href="${esc(i.url)}" target="_blank" rel="noopener">打开</a>` : '—'}</td></tr>`).join('');
  $('#view').innerHTML = `
    <div class="card"><div class="card-head"><h3>监控任务</h3><div class="spacer"></div>
      <button class="btn" onclick="App.monitor.mockItem()">＋ 模拟商品</button>
      <button class="btn primary" onclick="App.monitor.create()">＋ 新建任务</button></div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th>任务</th><th>关键词</th><th>价格</th><th>动作</th><th>间隔</th><th>命中</th><th>最近运行</th><th></th></tr></thead>
      <tbody>${rows || emptyRow(8, '还没有监控任务')}</tbody></table></div></div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>命中商品</h3></div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th>标题</th><th>价格</th><th>任务</th><th>发现时间</th><th></th></tr></thead>
      <tbody>${itemRows || emptyRow(5, '还没有命中记录')}</tbody></table></div></div>`;
};

/* ---------- knowledge ---------- */
PAGES.knowledge = async () => {
  const [b, s] = await Promise.all([api('/knowledge/bases'), api('/knowledge/stats')]);
  state.kbBases = b.bases;
  if (!state.kbSelected || !b.bases.some((x) => x.id === state.kbSelected)) {
    state.kbSelected = b.bases[0]?.id || null;
  }
  const selected = (b.bases.find((x) => x.id === state.kbSelected)) || null;
  const docs = selected ? (await api(`/knowledge/bases/${selected.id}/documents`)).documents : [];
  const cards = b.bases.map((kb) => `
    <div class="card card-pad" style="cursor:pointer;${kb.id === state.kbSelected ? 'border-color:var(--brand);box-shadow:0 0 0 2px rgba(13,148,136,.12)' : ''}"
      onclick="App.knowledge.select(${kb.id})">
      <div class="row"><b>${esc(kb.name)}</b><div class="spacer"></div>
        <span class="badge ${kb.enabled ? 'green' : ''}">${kb.enabled ? '启用' : '停用'}</span></div>
      <p class="hint" style="min-height:34px">${esc(kb.description || '暂无描述')}</p>
      <div class="row"><span class="badge blue">${kb.doc_count} 文档</span><span class="badge">${kb.chunk_count} 分块</span>
        <div class="spacer"></div>
        <button class="btn sm" onclick="event.stopPropagation();App.knowledge.editBase(${kb.id})">编辑</button>
        <button class="btn sm danger" onclick="event.stopPropagation();App.knowledge.removeBase(${kb.id})">删除</button></div>
    </div>`).join('');
  const docRows = docs.map((d) => `<tr><td><b>${esc(d.title)}</b></td><td>${d.chunk_count}</td>
    <td class="small muted">${fmtTime(d.updated_at)}</td>
    <td class="actions"><button class="btn sm" onclick="App.knowledge.editDoc(${d.id})">编辑</button>
    <button class="btn sm danger" onclick="App.knowledge.removeDoc(${d.id})">删除</button></td></tr>`).join('');
  $('#view').innerHTML = `
    <div class="grid cols-3">
      ${statCard('知识库', String(s.stats.bases), '按店铺/业务分组', '📚')}
      ${statCard('文档', String(s.stats.documents), '支持长文自动分块', '📄')}
      ${statCard('检索分块', String(s.stats.chunks), '中文二元组 + TF-IDF', '🔍')}
    </div>
    <div class="row" style="margin:16px 0 10px"><h3 style="margin:0;font-size:15px">知识库</h3>
      <div class="spacer"></div><button class="btn primary" onclick="App.knowledge.createBase()">＋ 新建知识库</button></div>
    <div class="grid cols-3">${cards || '<div class="card"><div class="empty">还没有知识库</div></div>'}</div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>${selected ? '文档：' + esc(selected.name) : '文档'}</h3>
      <div class="spacer"></div>${selected ? `<button class="btn primary" onclick="App.knowledge.createDoc()">＋ 新建文档</button>` : ''}</div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th>标题</th><th>分块</th><th>更新时间</th><th></th></tr></thead>
      <tbody>${docRows || emptyRow(4, selected ? '还没有文档' : '先创建知识库')}</tbody></table></div></div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>检索测试</h3></div><div class="card-pad">
      <div class="row wrap"><select class="input" id="kb-search-base" style="max-width:220px">
        <option value="">全部知识库</option>${b.bases.map((kb) => `<option value="${kb.id}">${esc(kb.name)}</option>`).join('')}</select>
        <input class="input" id="kb-search-q" style="flex:1;min-width:260px" placeholder="输入买家问题，例如：多久发货？卡密无效怎么办？">
        <button class="btn primary" onclick="App.knowledge.search()">检索</button></div>
      <div id="kb-results" style="margin-top:12px"></div></div></div>`;
};

/* ---------- notifications ---------- */
PAGES.notifications = async () => {
  const [chData, logData, accData, metaData] = await Promise.all([
    api('/notifications/channels'), api('/notifications/logs'), api('/accounts'), api('/notifications/meta')]);
  state.notifyChannels = chData.channels;
  state.accounts = accData.accounts;
  state.notifyTypes = metaData.types;
  const typeLabel = (t) => state.notifyTypes[t]?.label || t;
  const rows = chData.channels.map((ch) => `
    <tr><td><b>${esc(ch.name)}</b><div class="small muted mono">${esc(ch.config?.url || ch.config?.server || ch.config?.host || '')}</div></td>
      <td><span class="badge blue">${esc(typeLabel(ch.type))}</span></td>
      <td>${ch.account_ids.length ? ch.account_ids.map((id) => `<span class="badge">${esc((state.accounts.find((a) => a.id === id) || {}).name || id)}</span>`).join(' ') : '<span class="badge teal">全局</span>'}</td>
      <td>${ch.enabled ? '<span class="badge green">启用</span>' : '<span class="badge">停用</span>'}</td>
      <td class="actions"><button class="btn sm primary" onclick="App.notify.test(${ch.id})">测试</button>
        <button class="btn sm" onclick="App.notify.edit(${ch.id})">编辑</button>
        <button class="btn sm danger" onclick="App.notify.remove(${ch.id})">删除</button></td></tr>`).join('');
  const logs = logData.logs.slice(0, 50).map((l) => `<tr><td class="small muted">${fmtTime(l.created_at)}</td>
    <td>${esc(l.channel_name || '—')}</td><td><span class="badge">${esc(l.event)}</span></td>
    <td>${l.status === 'sent' ? '<span class="badge green">已发送</span>' : '<span class="badge red">失败</span>'}</td>
    <td class="small">${esc((l.error || l.message || '').slice(0, 90))}</td></tr>`).join('');
  $('#view').innerHTML = `
    <div class="card"><div class="card-head"><h3>通知渠道</h3><div class="spacer"></div>
      <button class="btn primary" onclick="App.notify.create()">＋ 新建渠道</button></div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th>渠道</th><th>类型</th><th>绑定账号</th><th>状态</th><th></th></tr></thead>
      <tbody>${rows || emptyRow(5, '还没有通知渠道')}</tbody></table></div></div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>发送日志</h3><div class="spacer"></div>
      <span class="small muted">订单发货、发货失败、监控命中、流程通知、登录限流会触发</span></div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th>时间</th><th>渠道</th><th>事件</th><th>结果</th><th>内容 / 错误</th></tr></thead>
      <tbody>${logs || emptyRow(5, '暂无通知记录')}</tbody></table></div></div>`;
};

/* ---------- scheduled jobs ---------- */
PAGES.jobs = async () => {
  const { jobs: list, types } = await api('/jobs');
  state.jobs = list;
  const rows = list.map((j) => `<tr><td><b>${esc(j.name)}</b></td>
    <td><span class="badge">${esc(types[j.type] || j.type)}</span></td>
    <td class="mono">${j.interval_seconds}s</td>
    <td class="small muted">${j.last_run_at ? fmtTime(j.last_run_at) : '—'}</td>
    <td class="small muted">${j.next_run_at && j.enabled ? fmtTime(j.next_run_at) : '—'}</td>
    <td>${j.enabled ? '<span class="badge green">启用</span>' : '<span class="badge">停用</span>'}
      ${j.last_status ? `<span class="badge ${j.last_status === 'success' ? 'teal' : 'red'}">${j.last_status === 'success' ? '成功' : '失败'}</span>` : ''}</td>
    <td class="small muted" title="${esc(j.last_message || '')}">${esc((j.last_message || '—').slice(0, 40))}</td>
    <td class="actions"><button class="btn sm primary" onclick="App.jobs.run(${j.id})">运行</button>
      <button class="btn sm" onclick="App.jobs.runs(${j.id})">记录</button>
      <button class="btn sm" onclick="App.jobs.edit(${j.id})">编辑</button>
      <button class="btn sm ${j.enabled ? 'amber' : ''}" onclick="App.jobs.toggle(${j.id},${j.enabled ? 0 : 1})">${j.enabled ? '停用' : '启用'}</button>
      <button class="btn sm danger" onclick="App.jobs.remove(${j.id})">删除</button></td></tr>`).join('');
  $('#view').innerHTML = `
    <div class="card"><div class="card-head"><h3>周期任务</h3><div class="spacer"></div>
      <button class="btn primary" onclick="App.jobs.create()">＋ 新建任务</button></div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th>名称</th><th>类型</th><th>间隔</th><th>上次运行</th><th>下次运行</th><th>状态</th><th>最近结果</th><th></th></tr></thead>
      <tbody>${rows || emptyRow(8, '还没有定时任务')}</tbody></table></div></div>
    <div class="card card-pad" style="margin-top:16px"><b>说明</b>
      <p class="muted small" style="margin:8px 0 0">调度器每 5 秒检查一次到期任务；订单同步按固定订单号执行（平台暂无订单列表接口），
      监控/补货复用现有规则，自动备份仅管理员可建。每次运行写入运行记录，失败不会中断调度器。</p></div>`;
};

/* ---------- workflows ---------- */
PAGES.workflows = async () => {
  const { workflows } = await api('/workflows');
  state.workflows = workflows;
  const cards = workflows.map((w) => `
    <div class="card card-pad" style="margin-bottom:12px">
      <div class="row"><b>${esc(w.name)}</b><span class="badge blue">${w.nodes.length} 节点</span>
        <span class="badge ${w.enabled ? 'green' : ''}">${w.enabled ? '启用' : '停用'}</span><div class="spacer"></div>
        <button class="btn sm" onclick="App.wf.edit(${w.id})">编辑</button>
        <button class="btn sm primary" onclick="App.wf.run(${w.id})">运行</button>
        <button class="btn sm danger" onclick="App.wf.remove(${w.id})">删除</button></div>
      <div class="tag-list" style="margin-top:10px">${w.nodes.map((n) => `<span class="badge">${esc(n.type)}:${esc(n.id)}</span>`).join('')}</div>
    </div>`).join('');
  $('#view').innerHTML = `
    <div class="row" style="margin-bottom:14px"><div class="muted small">节点类型：trigger / set / extract / api / condition / delay / deliver / notify</div>
      <div class="spacer"></div><button class="btn primary" onclick="App.wf.create()">＋ 新建流程</button></div>
    ${cards || '<div class="card"><div class="empty"><span class="big">🧩</span>还没有流程</div></div>'}`;
};

/* ---------- simulator ---------- */
PAGES.simulator = async () => {
  const [{ accounts }, { goods }] = await Promise.all([api('/accounts'), api('/goods')]);
  state.accounts = accounts; state.goods = goods;
  $('#view').innerHTML = `
    <div class="grid cols-2">
      <div class="card"><div class="card-head"><h3>模拟买家消息</h3></div><div class="card-pad">
        <div class="field"><label>账号</label><select class="input" id="sim-msg-account">${selectOptions(accounts, 'id', 'name', accounts[0]?.id)}</select></div>
        <div class="field"><label>商品（可选）</label><select class="input" id="sim-msg-goods">${selectOptions(goods, 'id', 'title', '', '不关联商品')}</select></div>
        <div class="field"><label>买家昵称</label><input class="input" id="sim-msg-buyer" value="demo_buyer"></div>
        <div class="field"><label>消息内容</label><input class="input" id="sim-msg-text" value="能便宜一点吗？"></div>
        <button class="btn primary" onclick="App.sim.message()">发送并触发自动回复</button></div></div>
      <div class="card"><div class="card-head"><h3>模拟下单</h3></div><div class="card-pad">
        <div class="field"><label>商品</label><select class="input" id="sim-order-goods">${selectOptions(goods, 'id', 'title', goods[0]?.id)}</select></div>
        <div class="field"><label>数量</label><input class="input" id="sim-order-qty" type="number" min="1" value="1"></div>
        <div class="field"><label>买家</label><input class="input" id="sim-order-buyer" value="demo_buyer"></div>
        <button class="btn primary" onclick="App.sim.order()">创建订单并自动发货</button>
        <button class="btn" style="margin-left:8px" onclick="App.sim.seed()">载入演示数据</button></div></div>
    </div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>执行结果</h3><div class="spacer"></div>
      <span class="small muted">最近一次调用的 JSON 响应</span></div>
      <div class="card-pad"><div class="code-box" id="sim-output">等待操作…</div></div></div>`;
};

/* ---------- settings ---------- */
PAGES.settings = async () => {
  const [data, bk, kbs, tok, sys] = await Promise.all([
    api('/settings'), api('/backups'), api('/knowledge/bases'), api('/integrations/token'),
    api('/system/status')]);
  state.kbBases = kbs.bases;
  const aiCfg = data.ai;
  const backupRows = bk.backups.map((b) => `<tr><td class="mono small">${esc(b.name)}</td>
    <td>${(b.size / 1024).toFixed(1)} KB</td><td class="small muted">${fmtTime(b.created_at)}</td>
    <td class="actions"><a class="btn sm" href="/api/backups/${encodeURIComponent(b.name)}/download">下载</a>
    <button class="btn sm danger" onclick="App.backup.remove('${esc(b.name)}')">删除</button></td></tr>`).join('');
  $('#view').innerHTML = `
    <div class="grid cols-2">
      <div class="card"><div class="card-head"><h3>AI 客服</h3><div class="spacer"></div>
        <span class="badge ${aiCfg.enabled ? 'green' : ''}">${aiCfg.enabled ? '已启用' : '未启用'}</span></div>
        <div class="card-pad">
          <div class="field"><label class="row" style="gap:8px"><input type="checkbox" id="set-ai-enabled" ${aiCfg.enabled ? 'checked' : ''}> 启用 AI 回复</label></div>
          <div class="field"><label>Base URL（OpenAI 兼容）</label><input class="input" id="set-ai-base" value="${esc(aiCfg.base_url)}" placeholder="https://api.openai.com/v1"></div>
          <div class="field"><label>模型</label><input class="input" id="set-ai-model" value="${esc(aiCfg.model)}"></div>
          <div class="field"><label>知识库增强</label><select class="input" id="set-ai-kb">${selectOptions(kbs.bases, 'id', 'name', aiCfg.kb_id, '不使用知识库')}</select>
            <div class="hint">命中知识库分块后会作为系统提示注入 AI 回复</div></div>
          <div class="field"><label>API Key</label><input class="input" id="set-ai-key" type="password" placeholder="${aiCfg.has_key ? '已保存，留空保持不变' : 'sk-...'}"></div>
          <div class="field"><label>系统提示词</label><textarea class="input" id="set-ai-prompt" rows="5">${esc(aiCfg.system_prompt)}</textarea></div>
          <button class="btn primary" onclick="App.settings.save()">保存设置</button>
          <button class="btn" onclick="App.settings.test()">测试连接</button>
          <span id="ai-test-result" class="small muted" style="margin-left:8px"></span>
        </div></div>
      <div class="card"><div class="card-head"><h3>关于</h3></div><div class="card-pad">
        <div class="kv">
          <div class="k">产品</div><div>FishAutoPro Clone 1.0.0</div>
          <div class="k">架构</div><div>Flask + SQLite + 原生 JS</div>
          <div class="k">许可</div><div>自托管，无许可证校验</div>
          <div class="k">平台</div><div>Mock 适配器（真实闲鱼接入见 goofish.py）</div>
        </div>
        <p class="hint" style="margin-top:14px">修改密码请重新初始化数据库或直接更新 users 表；生产部署建议置于反向代理 + HTTPS 之后，并限制访问来源。</p>
      </div></div>
    </div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>消息接入（外部桥）</h3><div class="spacer"></div>
      <button class="btn" onclick="App.settings.copyToken('${esc(tok.token || '')}')">复制令牌</button>
      <button class="btn amber" onclick="App.settings.rotateToken()">${tok.configured ? '轮换令牌' : '生成令牌'}</button></div>
      <div class="card-pad">
        <div class="field"><label>接入令牌</label><input class="input mono" id="ingest-token" readonly value="${esc(tok.token || '')}" placeholder="尚未生成"></div>
        <p class="hint">外部桥（浏览器插件 / Android 通知监听）用该令牌调用以下接口，无需登录 Cookie：</p>
        <pre class="code-box">POST /api/integrations/messages   {"account_id":1,"buyer":"买家","text":"在吗","external_id":"可选唯一ID"}
GET  /api/integrations/outbox     轮询待发送的自动回复
POST /api/integrations/outbox/{id}/ack  {"status":"sent"}
POST /api/integrations/send        {"account_id":1,"buyer":"买家","content":"人工消息"}</pre>
        <p class="hint">请求头使用 <span class="mono">X-FAP-Token</span> 或 <span class="mono">Authorization: Bearer &lt;token&gt;</span>；令牌只在管理员设置页展示。</p>
      </div></div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>系统状态</h3><div class="spacer"></div>
      <button class="btn amber" onclick="App.maintenance.prune()">清理 30 天前日志</button></div>
      <div class="card-pad"><div class="kv">
        <div class="k">版本</div><div>${esc(sys.status.version)}</div>
        <div class="k">运行时长</div><div>${Math.floor(sys.status.uptime_seconds / 3600)} 小时 ${Math.floor((sys.status.uptime_seconds % 3600) / 60)} 分</div>
        <div class="k">数据库</div><div>${(sys.status.db_size / 1024 / 1024).toFixed(1)} MB（WAL ${(sys.status.wal_size / 1024).toFixed(0)} KB）</div>
        <div class="k">调度器</div><div>${sys.status.scheduler ? '运行中' : '已禁用'}</div>
        <div class="k">数据量</div><div class="small">账号 ${sys.status.counts.accounts} · 商品 ${sys.status.counts.goods} · 订单 ${sys.status.counts.orders} · 会话 ${sys.status.counts.conversations} · 消息 ${sys.status.counts.messages} · 任务 ${sys.status.counts.job_tasks}</div>
      </div></div></div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>备份与恢复</h3><div class="spacer"></div>
      <button class="btn primary" onclick="App.backup.create()">创建备份</button></div>
      <div class="card-pad">
        ${bk.pending_restore ? '<div class="badge amber" style="margin-bottom:10px">已上传恢复文件，重启服务后生效</div>' : ''}
        <div class="table-wrap"><table class="tbl"><thead><tr><th>文件</th><th>大小</th><th>时间</th><th></th></tr></thead>
        <tbody>${backupRows || emptyRow(4, '还没有备份')}</tbody></table></div>
        <div class="row wrap" style="margin-top:14px">
          <input type="file" id="restore-file" accept=".zip,.db" class="input" style="max-width:320px">
          <button class="btn amber" onclick="App.backup.restore()">上传并安排恢复</button>
          <span class="hint">恢复会在服务重启后替换数据库；当前数据会自动备份为 app.db.bak-*</span>
        </div>
      </div></div>`;
};

/* ---------- login sessions ---------- */
PAGES.sessions = async () => {
  const { sessions } = await api('/auth/sessions');
  const rows = sessions.map((s) => `<tr><td>${s.current ? '<span class="badge green">当前设备</span>' : '<span class="badge">其他设备</span>'}</td>
    <td class="small">${esc((s.user_agent || '未知').slice(0, 80))}</td><td class="mono small">${esc(s.ip || '—')}</td>
    <td class="small muted">${fmtTime(s.created_at)}</td><td class="small muted">${fmtTime(s.last_seen_at)}</td>
    <td class="actions"><button class="btn sm danger" onclick="App.sessions.revoke(${s.id},${s.current})">吊销</button></td></tr>`).join('');
  $('#view').innerHTML = `
    <div class="card"><div class="card-head"><h3>登录设备</h3></div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th>状态</th><th>设备 / UA</th><th>IP</th><th>登录时间</th><th>最近活跃</th><th></th></tr></thead>
      <tbody>${rows || emptyRow(6, '没有有效会话')}</tbody></table></div></div>
    <div class="card card-pad" style="margin-top:16px"><b>说明</b>
      <p class="muted small" style="margin:8px 0 0">每次登录都会生成独立会话；吊销后该设备立即退出。修改密码会让所有旧会话失效。</p></div>`;
};

/* ---------- users ---------- */
PAGES.users = async () => {
  const { users } = await api('/users');
  state.users = users;
  const rows = users.map((u) => `<tr><td><b>${esc(u.username)}</b>${u.id === state.user.id ? ' <span class="badge teal">当前</span>' : ''}</td>
    <td><span class="badge ${u.role === 'admin' ? 'teal' : ''}">${u.role === 'admin' ? '管理员' : '运营'}</span></td>
    <td>${u.is_active ? '<span class="badge green">启用</span>' : '<span class="badge red">停用</span>'}</td>
    <td>${u.account_count}</td><td class="small muted">${fmtTime(u.created_at)}</td>
    <td class="actions"><button class="btn sm" onclick="App.users.edit(${u.id})">编辑</button>
      ${u.id !== state.user.id ? `<button class="btn sm ${u.is_active ? 'amber' : ''}" onclick="App.users.toggle(${u.id},${u.is_active ? 0 : 1})">${u.is_active ? '停用' : '启用'}</button>
      <button class="btn sm danger" onclick="App.users.remove(${u.id})">删除</button>` : ''}</td></tr>`).join('');
  $('#view').innerHTML = `
    <div class="card"><div class="card-head"><h3>用户列表</h3><div class="spacer"></div>
      <button class="btn primary" onclick="App.users.create()">＋ 新建用户</button></div>
      <div class="table-wrap"><table class="tbl"><thead><tr><th>用户名</th><th>角色</th><th>状态</th><th>账号数</th><th>创建时间</th><th></th></tr></thead>
      <tbody>${rows || emptyRow(6)}</tbody></table></div></div>
    <div class="card card-pad" style="margin-top:16px"><b>数据归属</b>
      <p class="muted small" style="margin:8px 0 0">管理员能看到全部数据；运营（operator）只能看到自己创建的账号、商品、订单、会话、规则、流程、知识库、素材、监控与通知渠道。删除用户前需先清理其数据。</p></div>`;
};

/* ---------- audit ---------- */
PAGES.audit = async () => {
  const qs = new URLSearchParams();
  if (state.auditQuery) qs.set('q', state.auditQuery);
  if (state.auditAction) qs.set('action', state.auditAction);
  if (state.auditDays) qs.set('days', state.auditDays);
  const suffix = qs.toString() ? '?' + qs : '';
  const r = await api('/audit-logs' + suffix + (suffix ? '&' : '?') + 'limit=100');
  state.auditData = { logs: r.logs, before: r.before_id, more: r.has_more, suffix };
  App.audit.render();
};

/* ------------------------------------------------------------------ actions */
const App = {
  audit: {
    search: (q) => { state.auditQuery = (q || '').trim(); route(); },
    action: (a) => { state.auditAction = (a || '').trim(); route(); },
    days: (d) => { state.auditDays = Number(d) || 0; route(); },
    render: () => {
      const d = state.auditData || { logs: [], suffix: '', more: false };
      const rows = d.logs.map((l) => `<tr><td class="small muted">${fmtTime(l.created_at)}</td><td><span class="badge">${esc(l.action)}</span></td>
        <td class="small mono">${esc(l.detail)}</td><td>${l.user_id ?? '—'}</td></tr>`).join('');
      $('#view').innerHTML = `<div class="card"><div class="card-head"><h3>操作日志</h3><div class="spacer"></div>
          <a class="btn" href="/api/audit-logs.xlsx${d.suffix}">导出 XLSX</a></div>
        <div class="row" style="padding:0 16px 12px;gap:8px;flex-wrap:wrap">
          <input class="input" style="max-width:220px" placeholder="搜索动作/详情" value="${esc(state.auditQuery || '')}"
            onkeydown="if(event.key==='Enter'){App.audit.search(this.value)}">
          <input class="input" style="max-width:180px" placeholder="动作前缀，如 order." value="${esc(state.auditAction || '')}"
            onkeydown="if(event.key==='Enter'){App.audit.action(this.value)}">
          <select class="input" style="max-width:140px" onchange="App.audit.days(this.value)">
            <option value="0">全部时间</option><option value="7" ${state.auditDays == 7 ? 'selected' : ''}>近 7 天</option>
            <option value="30" ${state.auditDays == 30 ? 'selected' : ''}>近 30 天</option></select>
        </div>
        <div class="table-wrap"><table class="tbl"><thead><tr><th>时间</th><th>动作</th><th>详情</th><th>用户</th></tr></thead>
        <tbody>${rows || emptyRow(4)}</tbody></table></div>
        ${d.more ? `<div style="text-align:center;padding:12px"><button class="btn" onclick="App.audit.more()">加载更早</button></div>` : ''}</div>`;
    },
    more: async () => {
      const d = state.auditData;
      if (!d || !d.more) return;
      const r = await api('/audit-logs' + d.suffix + (d.suffix ? '&' : '?') + 'limit=100&before_id=' + d.before);
      d.logs = d.logs.concat(r.logs);
      d.before = r.before_id;
      d.more = r.has_more;
      App.audit.render();
    },
  },
  dashboard: { range: (d) => { state.dashDays = d; route(); } },
  refreshUnread: async () => {
    try {
      const { conversations } = await api('/conversations?unread=1');
      const n = conversations.reduce((sum, c) => sum + (c.unread || 0), 0);
      state.unread = n;
      const el = $('#nav-unread');
      if (el) { el.textContent = n > 99 ? '99+' : String(n); el.style.display = n ? '' : 'none'; }
      document.title = n ? `(${n}) FishAutoPro Clone` : 'FishAutoPro Clone';
    } catch (e) { /* ignore transient polling errors */ }
  },
  startPolling: () => {
    if (state.pollTimer) { clearTimeout(state.pollTimer); state.pollTimer = null; }
    state.polling = true;
    state.eventCursor = { message: 0, order: 0, job: 0 };
    state.eventFirst = true;
    App.pollEvents();
  },
  pollEvents: async () => {
    if (!state.user || !state.polling) return;
    const c = state.eventCursor || { message: 0, order: 0, job: 0 };
    try {
      const r = await api(`/events/wait?after_message=${c.message}&after_order=${c.order}&after_job=${c.job}&timeout=20`);
      state.eventCursor = r.cursor;
      if (!state.eventFirst) {
        const incoming = (r.messages || []).filter((m) => m.direction === 'in');
        if (incoming.length) {
          App.refreshUnread();
          const m = incoming[incoming.length - 1];
          toast(`新消息 ${m.buyer}：${(m.content || '').slice(0, 24)}`);
        }
        if ((r.orders || []).length) {
          const o = r.orders[r.orders.length - 1];
          toast(`新订单 ${o.order_no} · ${o.buyer}`);
        }
        const failed = (r.jobs || []).filter((j) => j.status === 'failed');
        if (failed.length) toast(`任务失败：${failed[0].task_name}`, 'error');
      }
      state.eventFirst = false;
    } catch (e) { /* reconnect after a short delay */ }
    if (state.polling && state.user) {
      state.pollTimer = setTimeout(() => App.pollEvents(), 50);
    }
  },
  buyerTags: {
    search: (v) => { state.buyerQuery = (v || '').trim(); route(); },
    form: (buyer = '') => {
      modalForm('新建买家标签', [
        { name: 'buyer', label: '买家昵称' },
        { name: 'tag', label: '标签', placeholder: '老客 / 价格敏感 / 高风险' },
        { name: 'note', label: '备注', type: 'textarea', rows: 2 },
      ], { buyer }, async (data) => {
        if (!data.buyer || !data.tag) return toast('买家与标签不能为空', 'error');
        await api('/buyer-tags', { method: 'POST', body: data });
        toast('标签已保存', 'ok'); closeModal(); route();
      });
    },
    summary: async (buyer) => {
      try {
        const d = await api('/buyers/summary?buyer=' + encodeURIComponent(buyer));
        const tags = d.tags.map((t) => `<span class="badge teal">${esc(t.tag)}</span>`).join('') || '<span class="muted">无标签</span>';
        const orders = d.recent_orders.map((o) => `<tr><td class="mono small">${esc(o.order_no)}</td>
          <td>${esc(o.goods_title || '—')}</td><td>${money(o.amount)}</td><td>${badgeForStatus(o.status)}</td></tr>`).join('');
        const messages = (d.recent_messages || []).slice().reverse().map((m) => `<div class="msg ${m.direction === 'in' ? 'in' : 'out'}" style="margin:6px 0"><div class="bubble">${esc(m.content)}</div></div>`).join('');
        openModal('买家概览', `<div class="kv">
          <div class="k">买家</div><div><b>${esc(d.buyer)}</b></div>
          <div class="k">标签</div><div>${tags}</div>
          <div class="k">订单</div><div>${d.orders} 笔 / ${money(d.spend)}</div>
          <div class="k">会话</div><div>${d.conversations} 个 / 未读 ${d.unread}</div>
          <div class="k">最近下单</div><div class="small">${fmtTime(d.last_order_at)}</div>
          </div>
          <div class="row" style="gap:8px;margin:12px 0">
            <button class="btn sm" onclick="App.buyerTags.messages(decodeURIComponent('${encodeURIComponent(d.buyer)}'))">查看全部消息</button>
            <a class="btn sm" href="/api/buyers/messages.xlsx?buyer=${encodeURIComponent(d.buyer)}">导出消息 XLSX</a>
          </div>
          <h4 style="margin:16px 0 8px">最近订单</h4>
          <table class="tbl"><thead><tr><th>订单号</th><th>商品</th><th>金额</th><th>状态</th></tr></thead>
          <tbody>${orders || emptyRow(4)}</tbody></table>
          <h4 style="margin:16px 0 8px">最近消息</h4>
          <div style="max-height:180px;overflow:auto;background:var(--bg);border-radius:10px;padding:10px">
            ${messages || '<div class="muted small">暂无消息</div>'}</div>`, {});
      } catch (err) { toast(err.message, 'error'); }
    },
    messages: async (buyer) => {
      try {
        const r = await api('/buyers/messages?buyer=' + encodeURIComponent(buyer) + '&limit=20');
        state.buyerMessages = { buyer, messages: r.messages, beforeId: r.before_id, hasMore: r.has_more };
        App.buyerTags.showMessages();
      } catch (err) { toast(err.message, 'error'); }
    },
    showMessages: () => {
      const s = state.buyerMessages;
      if (!s) return;
      const bubbles = s.messages.map((m) => `<div class="msg ${m.direction}" style="margin:6px 0">
        <div class="bubble">${esc(m.content)}</div></div>`).join('');
      openModal(`买家消息 · ${s.buyer}`, `<div style="max-height:60vh;overflow:auto">
        ${bubbles || '<div class="muted">暂无消息</div>'}
        ${s.hasMore ? `<div style="text-align:center;margin-top:8px"><button class="btn sm" onclick="App.buyerTags.moreMessages()">加载更早</button></div>` : ''}
        </div>`, {});
    },
    moreMessages: async () => {
      const s = state.buyerMessages;
      if (!s || !s.hasMore) return;
      try {
        const r = await api(`/buyers/messages?buyer=${encodeURIComponent(s.buyer)}&limit=20&before_id=${s.beforeId}`);
        s.messages = s.messages.concat(r.messages);
        s.beforeId = r.before_id;
        s.hasMore = r.has_more;
        App.buyerTags.showMessages();
      } catch (err) { toast(err.message, 'error'); }
    },
    addBlacklist: () => {
      modalForm('拉黑买家', [
        { name: 'buyer', label: '买家昵称' },
        { name: 'reason', label: '原因', type: 'textarea', rows: 2 },
      ], {}, async (data) => {
        if (!data.buyer) return toast('买家不能为空', 'error');
        await api('/buyer-blacklist', { method: 'POST', body: data });
        toast('已加入黑名单', 'ok'); closeModal(); route();
      });
    },
    removeBlacklist: (id) => openConfirmDelete('将该买家移出黑名单？', () => api(`/buyer-blacklist/${id}`, { method: 'DELETE' })),
    remove: (id) => openConfirmDelete('删除该买家标签？', () => api(`/buyer-tags/${id}`, { method: 'DELETE' })),
  },
  movie: {
    search: (v) => { state.movieQuery = (v || '').trim(); route(); },
    filter: (v) => { state.movieStatus = v || ''; route(); },
    verify: async (id) => {
      if (!window.confirm('确认核销该电影票？核销后不可重复使用。')) return;
      try {
        const r = await api(`/movie-tickets/${id}/verify`, { method: 'POST' });
        toast(r.already ? '该票已核销' : '核销成功', 'ok'); route();
      } catch (err) { toast(err.message, 'error'); }
    },
    status: async (id, status) => {
      try { await api(`/movie-tickets/${id}`, { method: 'PATCH', body: { status } }); toast('状态已更新', 'ok'); route(); }
      catch (err) { toast(err.message, 'error'); }
    },
    form: (id) => {
      const t = id ? (state.movieTickets || []).find((x) => x.id === id) : null;
      modalForm(id ? '编辑电影票' : '新建电影票', [
        { name: 'movie_name', label: '影片名称' },
        { name: 'cinema', label: '影院' },
        { name: 'show_time', label: '场次', placeholder: '2026-11-01 19:30' },
        { name: 'seats', label: '座位', placeholder: '7排8座,7排9座' },
        { name: 'quantity', label: '数量', type: 'number' },
        { name: 'amount', label: '金额', type: 'number' },
        { name: 'buyer', label: '买家' },
        { name: 'phone', label: '手机号' },
        { name: 'note', label: '备注', type: 'textarea', rows: 2 },
      ], t || { quantity: 1, amount: 0 }, async (data) => {
        if (!data.movie_name) return toast('请填写影片名称', 'error');
        if (id) await api(`/movie-tickets/${id}`, { method: 'PATCH', body: data });
        else await api('/movie-tickets', { method: 'POST', body: data });
        toast(id ? '已保存' : '已创建', 'ok'); closeModal(); route();
      });
    },
    qr: async (id) => {
      try {
        const r = await api(`/movie-tickets/${id}/qr`);
        openModal('取票码', `<div style="text-align:center"><img src="${r.data_url}" alt="取票码"
          style="width:220px;height:220px"><div class="mono small" style="margin-top:8px">${esc(r.code)}</div>
          <p class="muted small">出示此二维码或取票码核销</p></div>`, {});
      } catch (err) { toast(err.message, 'error'); }
    },
    remove: (id) => openConfirmDelete('删除该电影票订单？', () => api(`/movie-tickets/${id}`, { method: 'DELETE' })),
  },
  sessions: {
    revoke: async (id, current) => {
      if (!window.confirm('吊销该登录会话？该设备会立即退出。')) return;
      try {
        await api(`/auth/sessions/${id}`, { method: 'DELETE' });
        if (current) { state.user = null; renderLogin(); }
        else { toast('会话已吊销', 'ok'); route(); }
      } catch (err) { toast(err.message, 'error'); }
    },
  },
  passwordModal: () => {
    openModal('修改密码', `
      <div class="field"><label>当前密码</label><input class="input" id="pw-old" type="password"></div>
      <div class="field"><label>新密码（至少 6 位）</label><input class="input" id="pw-new" type="password"></div>
      <div class="field"><label>确认新密码</label><input class="input" id="pw-confirm" type="password"></div>
      <p class="hint">修改后其他设备的登录会立即失效，当前设备保持登录。</p>`, {
      submitText: '保存',
      onSubmit: async () => {
        const oldPw = $('#pw-old').value;
        const newPw = $('#pw-new').value;
        if (newPw !== $('#pw-confirm').value) throw new Error('两次输入的新密码不一致');
        await api('/auth/password', { method: 'POST', body: { old_password: oldPw, new_password: newPw } });
        toast('密码已修改', 'ok'); closeModal();
      },
    });
  },
  logout: async () => {
    try { await api('/auth/logout', { method: 'POST' }); } catch (e) {}
    if (state.pollTimer) { clearTimeout(state.pollTimer); state.pollTimer = null; }
    state.polling = false;
    state.user = null;
    state.unread = 0;
    if (navigator.serviceWorker && navigator.serviceWorker.controller) {
      navigator.serviceWorker.controller.postMessage({ type: 'clear-data' });
    }
    document.title = 'FishAutoPro Clone';
    renderLogin();
  },
  accounts: {
    create: () => openFormAccount(null),
    edit: (id) => openFormAccount(state.accounts.find((a) => a.id === id)),
    connect: async (id) => {
      try { await api(`/accounts/${id}/connect`, { method: 'POST' }); toast('连接成功', 'ok'); closeModal(); route(); }
      catch (err) { toast(err.message, 'error'); }
    },
    disconnect: async (id) => { await api(`/accounts/${id}/disconnect`, { method: 'POST' }); closeModal(); route(); },
    qr: async (id) => {
      try {
        const r = await api(`/accounts/${id}/qr/start`, { method: 'POST' });
        const res = r.result;
        openModal('扫码登录闲鱼', `
          <div style="text-align:center">
            <img id="qr-img" src="${res.qr_image}" alt="QR" style="width:240px;height:240px;border:1px solid var(--line);border-radius:12px;background:#fff">
            <div id="qr-status" class="badge amber" style="margin-top:12px">等待扫码…</div>
            <p class="hint">用闲鱼 App 扫码并在手机上确认；二维码 5 分钟内有效。</p>
          </div>`, {});
        let attempts = 0;
        const timer = setInterval(async () => {
          if (!document.getElementById('qr-img')) { clearInterval(timer); return; }
          attempts += 1;
          if (attempts > 150) { clearInterval(timer); return; }
          try {
            const s = await api(`/accounts/${id}/qr/status/${res.session_id}`);
            const st = s.result;
            const el = $('#qr-status');
            if (el) {
              const cls = st.status === 'confirmed' ? 'green' : st.status === 'scanned' ? 'blue' : st.status === 'waiting' ? 'amber' : 'red';
              el.className = 'badge ' + cls;
              el.textContent = st.message || st.status;
            }
            if (st.status === 'confirmed') {
              clearInterval(timer);
              toast('登录成功', 'ok');
              setTimeout(() => { closeModal(); route(); }, 800);
            }
            if (st.status === 'expired' || st.status === 'canceled') clearInterval(timer);
          } catch (err) { /* transient polling errors are ignored */ }
        }, 2000);
      } catch (err) { toast(err.message, 'error'); }
    },
    mtop: (id) => {
      openModal('mtop 诊断', `
        <div class="field"><label>商品 ID</label><input class="input" id="mtop-item" placeholder="例如 1234567890">
          <div class="hint">调用 mtop.taobao.idle.pc.detail（需要真实 Cookie；无登录态也可能返回业务错误）</div></div>
        <button class="btn primary" onclick="App.accounts.mtopTest(${id})">调用详情接口</button>
        <div id="mtop-result" style="margin-top:12px"></div>`, {});
    },
    mtopTest: async (id) => {
      const itemId = ($('#mtop-item').value || '').trim();
      const box = $('#mtop-result');
      if (!itemId) return toast('请输入商品 ID', 'error');
      box.innerHTML = '<span class="badge">请求中…</span>';
      try {
        const r = await api(`/accounts/${id}/mtop/test`, { method: 'POST', body: { item_id: itemId } });
        box.innerHTML = `<pre class="code-box">${esc(JSON.stringify(r.data, null, 2).slice(0, 3000))}</pre>`;
      } catch (err) {
        const data = err.data || {};
        box.innerHTML = `<div class="badge red">${esc(data.mtop_code || '失败')}</div>
          <pre class="code-box" style="margin-top:8px">${esc(err.message)}</pre>`;
      }
    },
    proxyTest: async (id) => {
      openModal('代理检测', '<div id="proxy-result" class="muted">检测中…</div>', {});
      try {
        const r = await api(`/accounts/${id}/proxy-test`, { method: 'POST' });
        $('#proxy-result').innerHTML = `<div class="kv">
          <div class="k">出口 IP</div><div class="mono">${esc(r.ip)}</div>
          <div class="k">耗时</div><div>${r.elapsed_ms} ms</div>
          <div class="k">代理</div><div>${r.proxy_used ? '已使用账号代理' : '未配置代理（直连）'}</div></div>`;
      } catch (err) {
        $('#proxy-result').innerHTML = `<div class="badge red">检测失败</div><pre class="code-box" style="margin-top:8px">${esc(err.message)}</pre>`;
      }
    },
    detail: async (id) => {
      try {
        const d = await api(`/accounts/${id}/summary`);
        const a = d.account;
        const avatar = a.avatar_url ? `<img src="${esc(a.avatar_url)}" alt="" style="width:56px;height:56px;border-radius:50%;object-fit:cover">`
          : `<div class="avatar" style="width:56px;height:56px;font-size:22px">${esc((a.nickname || a.name || '?').slice(0, 1))}</div>`;
        const orders = d.recent_orders.map((o) => `<tr><td class="mono small">${esc(o.order_no)}</td><td>${esc(o.buyer)}</td>
          <td>${money(o.amount)}</td><td>${badgeForStatus(o.status)}</td></tr>`).join('');
        const goods = d.recent_goods.map((g) => `<tr><td>${esc(g.title)}</td><td>${money(g.price)}</td><td>${g.stock}</td>
          <td>${badgeForStatus(g.status)}</td></tr>`).join('');
        openModal('账号详情', `
          <div class="row" style="gap:12px;align-items:center;margin-bottom:16px">${avatar}
            <div><div style="font-size:18px;font-weight:700">${esc(a.nickname || a.name)}</div>
              <div class="small muted">${esc(a.name)}${a.platform_user_id ? ' · ID ' + esc(a.platform_user_id) : ''}</div></div>
            <div class="spacer"></div>${badgeForStatus(a.status)}</div>
          <div class="row" style="gap:8px;flex-wrap:wrap;margin-bottom:16px">
            ${a.status === 'online'
              ? `<button class="btn sm" onclick="App.accounts.disconnect(${a.id})">断开</button>`
              : `<button class="btn sm primary" onclick="App.accounts.connect(${a.id})">连接</button>`}
            ${!a.is_demo ? `<button class="btn sm" onclick="App.accounts.qr(${a.id})">扫码</button>
              <button class="btn sm" onclick="App.accounts.refreshInfo(${a.id})">刷新资料</button>` : ''}
            <button class="btn sm" onclick="App.accounts.proxyTest(${a.id})">测代理</button>
            <button class="btn sm" onclick="App.accounts.edit(${a.id})">编辑</button>
          </div>
          <div class="kv">
            <div class="k">Cookie</div><div>${a.has_cookie ? '已配置' : '未配置'}</div>
            <div class="k">代理</div><div class="mono small">${esc(a.proxy || '直连')}</div>
            <div class="k">累计收入</div><div>${money(d.revenue)}</div>
            <div class="k">数据量</div><div class="small">商品 ${d.counts.goods} · 订单 ${d.counts.orders} · 会话 ${d.counts.conversations} · 回复规则 ${d.counts.reply_rules} · 发货规则 ${d.counts.sell_rules}</div>
            <div class="k">备注</div><div>${esc(a.note || '—')}</div>
          </div>
          <h4 style="margin:16px 0 8px">最近订单</h4>
          <table class="tbl"><thead><tr><th>订单号</th><th>买家</th><th>金额</th><th>状态</th></tr></thead><tbody>${orders || emptyRow(4)}</tbody></table>
          <h4 style="margin:16px 0 8px">最近商品</h4>
          <table class="tbl"><thead><tr><th>商品</th><th>价格</th><th>库存</th><th>状态</th></tr></thead><tbody>${goods || emptyRow(4)}</tbody></table>`, {});
      } catch (err) { toast(err.message, 'error'); }
    },
    encryptedExport: async () => {
      const password = window.prompt('设置加密密码（至少 6 位）');
      if (!password) return;
      if (password.length < 6) return toast('密码至少 6 位', 'error');
      try {
        const r = await api('/accounts/export/encrypted', { method: 'POST', body: { password } });
        const blob = new Blob([JSON.stringify(r.blob, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'fap-accounts-encrypted.json';
        a.click();
        URL.revokeObjectURL(a.href);
        toast('加密文件已下载', 'ok');
      } catch (err) { toast(err.message, 'error'); }
    },
    importFile: async (input) => {
      const file = input.files && input.files[0];
      if (!file) return;
      try {
        const parsed = JSON.parse(await file.text());
        let body;
        if (parsed.format === 'fap-accounts-encrypted') {
          const password = window.prompt('输入加密文件密码');
          if (!password) return;
          body = { blob: parsed, password };
        } else {
          body = { accounts: Array.isArray(parsed) ? parsed : parsed.accounts };
        }
        const r = await api('/accounts/import', { method: 'POST', body });
        toast(`导入 ${r.imported}，跳过 ${r.skipped}`, 'ok');
        input.value = '';
        route();
      } catch (err) { toast('导入失败：' + err.message, 'error'); }
    },
    selectAll: (checked) => {
      $$('.acc-check').forEach((el) => { el.checked = checked; });
    },
    batch: async (action) => {
      const ids = $$('.acc-check:checked').map((el) => Number(el.value));
      if (!ids.length) return toast('请先选择账号', 'error');
      const labels = { connect: '连接', disconnect: '断开', enable: '启用', disable: '停用' };
      if (!window.confirm(`确认批量${labels[action]} ${ids.length} 个账号？`)) return;
      try {
        const r = await api('/accounts/batch', { method: 'POST', body: { action, ids } });
        toast(`成功 ${r.success}，失败 ${r.failed}`, r.failed ? 'error' : 'ok');
        route();
      } catch (err) { toast(err.message, 'error'); }
    },
    wsTest: async (id) => {
      try {
        const r = await api(`/accounts/${id}/ws-test`, { method: 'POST' });
        const x = r.result;
        openModal('LWP WebSocket 诊断', `<div class="kv">
          <div class="k">令牌</div><div>${x.token_ok ? '<span class="badge green">已获取</span>' : '<span class="badge red">失败</span>'}</div>
          <div class="k">握手</div><div>${x.connected ? '<span class="badge green">已连接</span>' : '<span class="badge red">失败</span>'}</div>
          <div class="k">子协议</div><div class="mono small">${esc(x.subprotocol || '—')}</div>
          <div class="k">/reg 响应</div><div class="mono small">${esc((x.responses || []).length ? JSON.stringify(x.responses).slice(0, 600) : '无（可能不需要响应）')}</div>
          <div class="k">错误</div><div class="small">${esc(x.error || '—')}</div>
          </div><p class="muted small">已发送 /reg 注册帧；消息收发协议仍在校准中。</p>`, {});
      } catch (err) {
        openModal('LWP WebSocket 诊断', `<p class="small">${esc(err.message)}</p>
          <p class="muted small">令牌获取失败，请先确认账号登录态。</p>`, {});
      }
    },
    refreshInfo: async (id) => {
      try {
        const r = await api(`/accounts/${id}/refresh-info`, { method: 'POST' });
        toast(`资料已刷新：${r.profile.nickname || '—'}`, 'ok'); closeModal(); route();
      } catch (err) { toast(err.message, 'error'); }
    },
    polish: (id) => {
      openModal('擦亮商品', `
        <div class="field"><label>商品 ID（每行一个，最多 50 个）</label>
          <textarea class="input" id="polish-items" rows="5" placeholder="1234567890&#10;0987654321"></textarea></div>
        <div class="row" style="gap:8px">
          <button class="btn" onclick="App.accounts.polishLoad(${id})">拉取在售商品</button>
          <button class="btn primary" onclick="App.accounts.polishRun(${id})">开始擦亮</button>
        </div>
        <div id="polish-result" style="margin-top:12px"></div>`, {});
    },
    polishLoad: async (id) => {
      const box = $('#polish-result');
      box.innerHTML = '<span class="badge">拉取中…</span>';
      try {
        const r = await api(`/accounts/${id}/items`);
        const lines = (r.items || []).map((x) => x.item_id).join('\n');
        if (lines) $('#polish-items').value = lines;
        box.innerHTML = `<span class="badge green">找到 ${r.count} 个商品</span>`;
      } catch (err) {
        box.innerHTML = `<span class="badge red">${esc(err.message)}</span>`;
      }
    },
    polishRun: async (id) => {
      const box = $('#polish-result');
      box.innerHTML = '<span class="badge">擦亮中…</span>';
      try {
        const r = await api(`/accounts/${id}/polish`, { method: 'POST', body: { item_ids: $('#polish-items').value } });
        const rows = r.results.map((x) => `<tr><td class="mono">${esc(x.item_id)}</td>
          <td>${x.ok ? '<span class="badge green">成功</span>' : `<span class="badge red">失败</span> <span class="small">${esc(x.error || '')}</span>`}</td></tr>`).join('');
        box.innerHTML = `<div class="badge ${r.failed ? 'amber' : 'green'}">成功 ${r.success} / 失败 ${r.failed}</div>
          <div class="table-wrap" style="margin-top:8px"><table class="tbl"><thead><tr><th>商品</th><th>结果</th></tr></thead><tbody>${rows}</tbody></table></div>`;
      } catch (err) {
        box.innerHTML = `<span class="badge red">${esc(err.message)}</span>`;
      }
    },
    remove: (id) => openConfirmDelete('删除账号会同时删除其商品与规则，确认？', () => api(`/accounts/${id}`, { method: 'DELETE' })),
  },
  goods: {
    create: () => openFormGoods(null),
    edit: (id) => openFormGoods(state.goods.find((g) => g.id === id)),
    search: (q) => { state.goodsQuery = (q || '').trim(); route(); },
    filterStatus: (s) => { state.goodsStatus = s; route(); },
    remove: (id) => openConfirmDelete('确认删除该商品？', () => api(`/goods/${id}`, { method: 'DELETE' })),
    offline: (id) => openConfirmDelete('确认下架该商品？', () => api(`/goods/${id}/offline`, { method: 'POST' })),
    offlineAll: () => {
      const ids = (state.goods || []).filter((g) => g.status === 'on_sale').map((g) => g.id);
      if (!ids.length) return toast('没有在售商品', 'error');
      openConfirmDelete(`确认下架全部 ${ids.length} 个在售商品？`, () => api('/goods/offline', { method: 'POST', body: { ids } }));
    },
  },
  publish: {
    create: () => openFormMaterial(null),
    edit: (id) => openFormMaterial((state.materials || []).find((m) => m.id === id)),
    remove: (id) => openConfirmDelete('确认删除该素材？', () => api(`/materials/${id}`, { method: 'DELETE' })),
    publish: async (id) => {
      try {
        const r = await api('/product-publish/publish', { method: 'POST', body: { material_ids: [id] } });
        const res = r.result.results[0];
        toast(res.ok ? '发布成功' : res.error, res.ok ? 'ok' : 'error');
        route();
      } catch (err) { toast(err.message, 'error'); route(); }
    },
    publishSelected: async () => {
      const ids = $$('.pub-check:checked').map((el) => Number(el.value));
      if (!ids.length) return toast('请先勾选素材', 'error');
      try {
        const r = await api('/product-publish/publish', { method: 'POST', body: { material_ids: ids } });
        toast(`发布完成：成功 ${r.result.success} / 失败 ${r.result.failed}`, r.result.failed ? 'error' : 'ok');
        route();
      } catch (err) { toast(err.message, 'error'); route(); }
    },
  },
  relist: {
    create: () => openFormRelist(null),
    edit: (id) => openFormRelist((state.relistRules || []).find((r) => r.id === id)),
    remove: (id) => openConfirmDelete('确认删除该补货规则？', () => api(`/auto-relist/rules/${id}`, { method: 'DELETE' })),
    run: async (id) => {
      try {
        const r = await api(`/auto-relist/rules/${id}/run`, { method: 'POST' });
        toast(r.result.status === 'relisted' ? '已重新上架' : r.result.message, 'ok');
        route();
      } catch (err) { toast(err.message, 'error'); route(); }
    },
  },
  orders: {
    statsDays: (d) => { state.orderStatsDays = Number(d) || 0; route(); },
    syncModal: async () => {
      const { accounts } = await api('/accounts');
      if (!accounts.length) return toast('请先创建账号', 'error');
      modalForm('同步订单', [
        { name: 'account_id', label: '账号', type: 'select', options: accounts.map((a) => ({ value: a.id, label: a.name })) },
        { name: 'order_id', label: '平台订单号', placeholder: '例如 1234567890' },
        { name: 'auto_deliver', label: '自动发货', type: 'checkbox', checkboxLabel: '同步后若待发货则执行自动发货' },
      ], { auto_deliver: 0 }, async (data) => {
        await api('/orders/sync', { method: 'POST', body: data });
        toast('订单已同步', 'ok'); route();
      });
    },
    syncListModal: async () => {
      const { accounts } = await api('/accounts');
      if (!accounts.length) return toast('请先创建账号', 'error');
      modalForm('同步订单列表', [
        { name: 'account_id', label: '账号', type: 'select', options: accounts.map((a) => ({ value: a.id, label: a.name })) },
        { name: 'limit', label: '最多拉取', type: 'number', value: 50 },
        { name: 'pages', label: '页数（每页 20 条）', type: 'number', value: 1 },
        { name: 'auto_deliver', label: '自动发货', type: 'checkbox', checkboxLabel: '同步后对待发货订单执行自动发货' },
      ], { limit: 50, pages: 1, auto_deliver: 0 }, async (data) => {
        const r = await api('/orders/sync-list', { method: 'POST', body: data });
        const res = r.result;
        toast(`拉取 ${res.fetched}，新增 ${res.created}，更新 ${res.updated}`, 'ok'); route();
      });
    },
    filter: (v) => { state.orderFilter = v; route(); },
    search: (q) => { state.orderQuery = q || ''; route(); },
    deliver: async (id, force) => {
      try { const r = await api(`/orders/${id}/deliver`, { method: 'POST', body: { force } }); toast('发货成功', 'ok'); route(); }
      catch (err) { toast(err.message, 'error'); route(); }
    },
    detail: async (id) => {
      try {
        const [{ order, logs }, { logs: auditLogs }] = await Promise.all([
          api(`/orders/${id}`), api(`/orders/${id}/history`)]);
        const logHtml = logs.map((l) => `<tr><td>${l.status === 'success' ? '<span class="badge green">成功</span>' : '<span class="badge red">失败</span>'}</td>
          <td class="small mono">${esc(l.content || l.error || '')}</td><td class="small muted">${fmtTime(l.created_at)}</td></tr>`).join('');
        const historyHtml = (auditLogs || []).map((l) => `<tr><td class="small muted">${fmtTime(l.created_at)}</td>
          <td><span class="badge">${esc(l.action)}</span></td><td class="small mono">${esc(l.detail)}</td></tr>`).join('');
        openModal('订单详情', `
          <div class="kv">
            <div class="k">订单号</div><div class="mono">${esc(order.order_no)}</div>
            <div class="k">商品</div><div>${esc(order.goods_title || '—')}</div>
            <div class="k">买家</div><div>${esc(order.buyer)}</div>
            <div class="k">数量 / 金额</div><div>${order.quantity} / ${money(order.amount)}</div>
            <div class="k">状态</div><div>${badgeForStatus(order.status)}</div>
            <div class="k">创建时间</div><div>${fmtTime(order.created_at)}</div>
            <div class="k">发货时间</div><div>${fmtTime(order.delivered_at)}</div>
            <div class="k">发货内容</div><div class="code-box" style="max-height:160px">${esc(order.delivery_content || order.delivery_error || '—')}</div>
            <div class="k">评价</div><div>${order.rated_at ? `已评价：${esc(order.rate_content)}` : (order.rate_status === 'failed' ? '自动好评失败' : '未评价')}</div>
            <div class="k">退款</div><div>${order.refund_status ? `${esc(order.refund_status)} / ${money(order.refund_amount)} ${esc(order.refund_reason || '')}` : '未退款'}</div>
            <div class="k">平台发货</div><div>${order.ship_status === 'success' ? `已同步 ${fmtTime(order.platform_shipped_at)}` : (order.ship_status === 'failed' ? '同步失败' : '未同步')}</div>
            <div class="k">备注</div><div>${esc(order.note || '—')}</div>
          </div>
          <div style="margin-top:12px"><button class="btn sm" onclick="App.orders.note(${order.id})">编辑备注</button></div>
          ${order.status === 'delivered' && !order.rated_at ? `<div style="margin-top:12px"><button class="btn primary" onclick="App.orders.rate(${order.id})">好评</button></div>` : ''}
          ${order.status === 'delivered' && order.ship_status !== 'success' ? `<div style="margin-top:12px"><button class="btn" onclick="App.orders.ship(${order.id})">同步平台发货</button></div>` : ''}
          ${order.refund_status !== 'success' ? `<div style="margin-top:12px"><button class="btn amber" onclick="App.orders.refund(${order.id})">记录退款</button></div>` : ''}
          <h4 style="margin:18px 0 8px">交付日志</h4>
          <table class="tbl"><thead><tr><th>结果</th><th>内容</th><th>时间</th></tr></thead><tbody>${logHtml || emptyRow(3)}</tbody></table>
          <h4 style="margin:18px 0 8px">操作记录</h4>
          <table class="tbl"><thead><tr><th>时间</th><th>动作</th><th>详情</th></tr></thead><tbody>${historyHtml || emptyRow(3)}</tbody></table>`, {});
      } catch (err) { toast(err.message, 'error'); }
    },
    note: async (id) => {
      const order = (state.orders || []).find((o) => o.id === id) || {};
      const note = window.prompt('订单备注', order.note || '');
      if (note === null) return;
      try {
        await api(`/orders/${id}`, { method: 'PATCH', body: { note } });
        toast('备注已保存', 'ok'); closeModal(); route();
      } catch (err) { toast(err.message, 'error'); }
    },
    ship: async (id) => {
      try {
        await api(`/orders/${id}/ship`, { method: 'POST' });
        toast('平台发货已同步', 'ok'); closeModal(); route();
      } catch (err) { toast(err.message, 'error'); }
    },
    remove: (id) => openConfirmDelete('删除订单及其交付日志？', () => api(`/orders/${id}`, { method: 'DELETE' })),
    refund: (id) => {
      const order = (state.orders || []).find((o) => o.id === id) || {};
      openModal('记录退款', `
        <div class="field"><label>退款状态</label><select class="input" id="refund-status">
          <option value="requested">已申请</option><option value="refunding">退款中</option>
          <option value="success">退款成功</option><option value="failed">退款失败</option></select></div>
        <div class="field"><label>退款金额</label><input class="input" id="refund-amount" type="number" step="0.01" value="${order.amount || 0}"></div>
        <div class="field"><label>原因 / 备注</label><textarea class="input" id="refund-reason" rows="3"></textarea></div>`, {
        submitText: '保存',
        onSubmit: async () => {
          await api(`/orders/${id}/refund`, { method: 'POST', body: {
            status: $('#refund-status').value,
            amount: Number($('#refund-amount').value || 0),
            reason: $('#refund-reason').value,
          } });
          toast('退款状态已记录', 'ok'); closeModal(); route();
        },
      });
    },
    rate: (id) => {
      openModal('订单好评', `<div class="field"><label>评价内容</label>
        <textarea class="input" id="rate-content" rows="3">宝贝很好，下次还会再来～</textarea></div>`, {
        submitText: '提交好评',
        onSubmit: async () => {
          await api(`/orders/${id}/rate`, { method: 'POST', body: { content: $('#rate-content').value } });
          toast('已好评', 'ok'); closeModal(); route();
        },
      });
    },
  },
  chat: {
    filterTag: (tag) => { state.convTag = tag || ''; route(); },
    open: async (id) => {
      state.convId = id;
      const [{ conversation, messages, has_more, before_id }, phraseData] = await Promise.all([
        api(`/conversations/${id}/messages`), api('/quick-phrases')]);
      state.chat = { conversation, messages, hasMore: has_more, beforeId: before_id };
      state.phrases = phraseData.phrases;
      $$('.conv-item').forEach((el) => el.classList.remove('active'));
      const list = $$('.conv-item');
      const convs = await api('/conversations');
      const idx = convs.conversations.findIndex((c) => c.id === id);
      if (list[idx]) list[idx].classList.add('active');
      const convMeta = convs.conversations[idx] || conversation;
      const tagHtml = (convMeta.tags || '').split(',').filter(Boolean)
        .map((t) => `<span class="badge teal">${esc(t)}</span>`).join('');
      const older = has_more ? `<div style="text-align:center;margin-bottom:8px"><button class="btn sm" onclick="App.chat.loadOlder(${id})">加载更早</button></div>` : '';
      const bubbles = older + messages.map((m) => `<div class="msg ${m.direction}"><div class="bubble">${esc(m.content)}</div></div>`).join('');
      const phraseOptions = (state.phrases || []).map((p) => `<option value="${p.id}">${esc(p.content)}</option>`).join('');
      const pane = $('#chat-pane');
      if (!pane) return;
      pane.innerHTML = `
        <div class="chat-head"><div class="avatar">${esc(conversation.buyer.slice(0, 1).toUpperCase())}</div>
          <div><b style="cursor:pointer" onclick="App.buyerTags.summary(decodeURIComponent('${encodeURIComponent(conversation.buyer)}'))">${esc(conversation.buyer)}</b>${tagHtml}<div class="small muted">${esc(conversation.goods_title || '未关联商品')}</div></div>
          <div class="spacer"></div>
          <button class="btn sm" onclick="App.buyerTags.form(decodeURIComponent('${encodeURIComponent(conversation.buyer)}'))">标签</button>
          <button class="btn sm ${conversation.autoreply_paused ? 'amber' : 'primary'}" onclick="App.chat.toggleAutoreply(${id})">${conversation.autoreply_paused ? '自动回复已暂停' : '自动回复已开启'}</button>
          <button class="btn sm ${conversation.ai_enabled ? 'primary' : ''}" onclick="App.chat.toggleAI(${id})">${conversation.ai_enabled ? 'AI 已开启' : 'AI 已关闭'}</button>
        </div>
        <div class="chat-body" id="chat-body">${bubbles || '<div class="empty">暂无消息</div>'}</div>
        <div class="chat-input">
          <select class="input" id="chat-phrase" style="max-width:160px" onchange="App.chat.usePhrase(this)">
            <option value="">快捷话术</option>${phraseOptions}</select>
          <input class="input" id="chat-input" placeholder="输入回复内容，回车发送" onkeydown="if(event.key==='Enter')App.chat.send(${id})">
          <button class="btn primary" onclick="App.chat.send(${id})">发送</button>
          <button class="btn" onclick="App.chat.managePhrases()">管理</button></div>`;
      const body = $('#chat-body'); body.scrollTop = body.scrollHeight;
    },
    loadOlder: async (id) => {
      const chat = state.chat;
      if (!chat || !chat.hasMore) return;
      const r = await api(`/conversations/${id}/messages?before_id=${chat.beforeId}&limit=200`);
      const body = $('#chat-body');
      const oldHeight = body.scrollHeight;
      chat.messages = [...r.messages, ...chat.messages];
      chat.hasMore = r.has_more;
      chat.beforeId = r.before_id;
      const older = r.has_more ? `<div style="text-align:center;margin-bottom:8px"><button class="btn sm" onclick="App.chat.loadOlder(${id})">加载更早</button></div>` : '';
      body.innerHTML = older + chat.messages.map((m) => `<div class="msg ${m.direction}"><div class="bubble">${esc(m.content)}</div></div>`).join('');
      body.scrollTop = body.scrollHeight - oldHeight;
    },
    search: (q) => { state.convQuery = (q || '').trim(); route(); },
    toggleUnread: () => { state.convUnread = !state.convUnread; route(); },
    markAllRead: async () => {
      try {
        const r = await api('/conversations/read-all', { method: 'POST' });
        toast(`已标记 ${r.updated} 个会话为已读`, 'ok'); route();
      } catch (err) { toast(err.message, 'error'); }
    },
    send: async (id) => {
      const input = $('#chat-input');
      const content = input.value.trim();
      if (!content) return;
      try {
        const r = await api(`/conversations/${id}/messages`, { method: 'POST', body: { content } });
        input.value = '';
        if (!r.sent) toast('本地已保存；平台发送未启用：' + (r.error || ''), 'error');
        await App.chat.open(id);
        route();
      } catch (err) { toast(err.message, 'error'); }
    },
    toggleAutoreply: async (id) => {
      const conv = state.chat.conversation;
      if (conv.autoreply_paused) {
        try {
          await api(`/conversations/${id}/autoreply`, { method: 'POST', body: { paused: false } });
          toast('已恢复自动回复', 'ok'); route();
        } catch (err) { toast(err.message, 'error'); }
        return;
      }
      openModal('暂停自动回复', `
        <div class="field"><label>暂停时长</label><select class="input" id="pause-minutes">
          <option value="30">30 分钟</option><option value="120">2 小时</option>
          <option value="1440">24 小时</option><option value="0">直到手动恢复</option></select></div>
        <p class="hint">暂停期间规则、AI 与外部桥都不会自动回复；到期后自动恢复。</p>`, {
        submitText: '暂停',
        onSubmit: async () => {
          await api(`/conversations/${id}/autoreply`, { method: 'POST', body: {
            paused: true, minutes: Number($('#pause-minutes').value || 0),
          } });
          toast('已暂停自动回复', 'ok'); closeModal(); route();
        },
      });
    },
    toggleAI: async (id) => {
      const conv = state.chat.conversation;
      await api(`/conversations/${id}/ai`, { method: 'POST', body: { enabled: !conv.ai_enabled } });
      route();
    },
    usePhrase: (select) => {
      if (!select.value) return;
      const text = select.selectedOptions[0]?.textContent || '';
      const input = $('#chat-input');
      if (input) { input.value = text; input.focus(); }
      select.value = '';
    },
    managePhrases: async () => {
      const { phrases } = await api('/quick-phrases');
      state.phrases = phrases;
      const rows = phrases.map((p) => `<div class="row" style="border-bottom:1px solid var(--line);padding:8px 0">
        <span style="flex:1">${esc(p.content)}</span>
        <button class="btn sm danger" onclick="App.chat.removePhrase(${p.id})">删除</button></div>`).join('');
      openModal('快捷话术', `<div style="max-height:300px;overflow:auto">${rows || '<div class="empty">暂无话术</div>'}</div>
        <div class="row" style="margin-top:12px"><input class="input" id="new-phrase" placeholder="输入新话术">
        <button class="btn primary" onclick="App.chat.addPhrase()">添加</button></div>`, {});
    },
    addPhrase: async () => {
      const content = ($('#new-phrase').value || '').trim();
      if (!content) return toast('请输入话术', 'error');
      await api('/quick-phrases', { method: 'POST', body: { content } });
      toast('已添加', 'ok');
      await App.chat.managePhrases();
    },
    removePhrase: async (id) => {
      await api(`/quick-phrases/${id}`, { method: 'DELETE' });
      await App.chat.managePhrases();
    },
  },
  reply: {
    create: () => openFormReply(null),
    edit: (id) => openFormReply(state.replyRules.find((r) => r.id === id)),
    remove: (id) => openConfirmDelete('确认删除该回复规则？', () => api(`/autoreply/rules/${id}`, { method: 'DELETE' })),
    test: async () => {
      const text = $('#reply-test-text').value.trim();
      if (!text) return toast('请输入测试消息', 'error');
      try {
        const r = await api('/autoreply/test', { method: 'POST', body: { text } });
        let html = '';
        if (r.matched) {
          html = `<div class="badge green">命中规则：${esc(r.rule.name)}</div>
            <div class="code-box" style="margin-top:8px">${esc(r.reply.content || r.reply.image_url)}</div>`;
        } else if (r.ai) {
          html = `<div class="badge teal">AI 回复</div><div class="code-box" style="margin-top:8px">${esc(r.reply.content)}</div>`;
        } else {
          html = `<div class="badge amber">未命中规则${r.error ? '：' + esc(r.error) : ''}</div>`;
        }
        $('#reply-test-result').innerHTML = html;
      } catch (err) { toast(err.message, 'error'); }
    },
  },
  sell: {
    create: () => openFormSell(null),
    edit: (id) => openFormSell(state.sellRules.find((r) => r.id === id)),
    remove: (id) => openConfirmDelete('确认删除该发货规则？', () => api(`/autosell/rules/${id}`, { method: 'DELETE' })),
    preview: async (id) => {
      try {
        const r = await api(`/autosell/rules/${id}/preview`, { method: 'POST', body: { quantity: 1 } });
        openModal('发货预览', `<div class="code-box">${esc(r.preview || '—')}</div>
          ${r.available !== undefined ? `<p class="hint">可用 ${r.available} 份 / 需要 ${r.needed} 份</p>` : ''}`, {});
      } catch (err) { toast(err.message, 'error'); }
    },
    stock: async (id) => openStockModal(id),
  },
  monitor: {
    create: () => openFormMonitor(null),
    edit: (id) => openFormMonitor(state.monitorTasks.find((t) => t.id === id)),
    remove: (id) => openConfirmDelete('确认删除该监控任务？', () => api(`/monitor/tasks/${id}`, { method: 'DELETE' })),
    run: async (id) => {
      try { const r = await api(`/monitor/tasks/${id}/run`, { method: 'POST' }); toast(`运行完成，新增 ${r.result.new} 条`, 'ok'); route(); }
      catch (err) { toast(err.message, 'error'); }
    },
    mockItem: async () => {
      openModal('添加模拟商品', `
        <div class="field"><label>标题</label><input class="input" id="mock-title" placeholder="例如：九成新 iPad Air 5"></div>
        <div class="field"><label>价格</label><input class="input" id="mock-price" type="number" value="1999"></div>
        <div class="field"><label>链接</label><input class="input" id="mock-url" value="https://example.com/item/demo"></div>`, {
        submitText: '添加',
        onSubmit: async () => {
          await api('/monitor/mock-items', { method: 'POST', body: { title: $('#mock-title').value, price: Number($('#mock-price').value), url: $('#mock-url').value } });
          toast('已添加', 'ok'); route();
        },
      });
    },
  },
  jobs: {
    create: () => openFormJob(null),
    edit: (id) => openFormJob((state.jobs || []).find((j) => j.id === id)),
    toggle: async (id, enabled) => {
      try { await api(`/jobs/${id}`, { method: 'PATCH', body: { enabled: !!enabled } }); toast('已更新', 'ok'); route(); }
      catch (err) { toast(err.message, 'error'); }
    },
    run: async (id) => {
      try { const r = await api(`/jobs/${id}/run`, { method: 'POST' }); toast(r.result?.message || '任务已完成', 'ok'); route(); }
      catch (err) { toast(err.message, 'error'); route(); }
    },
    remove: (id) => openConfirmDelete('删除任务及其运行记录？', () => api(`/jobs/${id}`, { method: 'DELETE' })),
    runs: async (id) => {
      const { runs } = await api(`/jobs/${id}/runs`);
      const rows = runs.map((r) => `<tr><td>${r.status === 'success' ? '<span class="badge green">成功</span>' : '<span class="badge red">失败</span>'}</td>
        <td class="small">${esc(r.message || '')}</td><td class="small muted">${fmtTime(r.started_at)}</td></tr>`).join('');
      openModal('运行记录', `<div class="table-wrap"><table class="tbl"><thead><tr><th>状态</th><th>结果</th><th>时间</th></tr></thead>
        <tbody>${rows || emptyRow(3, '还没有运行记录')}</tbody></table></div>`, {});
    },
    formType: () => {
      const t = $('#job-type')?.value;
      document.querySelectorAll('.job-sec').forEach((el) => {
        el.style.display = el.dataset.type === t ? '' : 'none';
      });
    },
  },
  wf: {
    create: () => openWorkflowEditor(null),
    edit: (id) => openWorkflowEditor(state.workflows.find((w) => w.id === id)),
    remove: (id) => openConfirmDelete('确认删除该流程？', () => api(`/workflows/${id}`, { method: 'DELETE' })),
    run: (id) => {
      openModal('运行流程', `<div class="field"><label>上下文 JSON</label>
        <textarea class="input" id="wf-context" rows="6">{"order_no":"DEMO001","quantity":2,"buyer":"测试买家","delivery":"KEY-1\\nKEY-2"}</textarea></div>`, {
        submitText: '运行',
        onSubmit: async () => {
          let context = {};
          try { context = JSON.parse($('#wf-context').value || '{}'); } catch (e) { throw new Error('上下文不是合法 JSON'); }
          const r = await api(`/workflows/${id}/run`, { method: 'POST', body: { context } });
          closeModal();
          openModal('运行结果', `<pre class="code-box">${esc(JSON.stringify(r.result, null, 2))}</pre>`, {});
        },
      });
    },
  },
  knowledge: {
    select: (id) => { state.kbSelected = id; route(); },
    createBase: () => openFormKnowledgeBase(null),
    editBase: (id) => openFormKnowledgeBase((state.kbBases || []).find((x) => x.id === id)),
    removeBase: (id) => openConfirmDelete('删除知识库会同时删除其文档与分块，确认？', () => api(`/knowledge/bases/${id}`, { method: 'DELETE' })),
    createDoc: () => openFormKnowledgeDoc(state.kbSelected, null),
    editDoc: async (id) => {
      try {
        const { document } = await api(`/knowledge/documents/${id}`);
        openFormKnowledgeDoc(document.kb_id, document);
      } catch (err) { toast(err.message, 'error'); }
    },
    removeDoc: (id) => openConfirmDelete('确认删除该文档？', () => api(`/knowledge/documents/${id}`, { method: 'DELETE' })),
    search: async () => {
      const query = $('#kb-search-q').value.trim();
      if (!query) return toast('请输入检索内容', 'error');
      try {
        const r = await api('/knowledge/search', { method: 'POST', body: {
          query, kb_id: Number($('#kb-search-base').value) || null, limit: 5,
        }});
        if (!r.hits.length) { $('#kb-results').innerHTML = '<div class="badge amber">没有命中分块</div>'; return; }
        $('#kb-results').innerHTML = r.hits.map((h) => `<div class="card card-pad" style="margin-bottom:8px;background:var(--panel-2)">
          <div class="row"><b>${esc(h.title)}</b><span class="badge teal">score ${h.score}</span></div>
          <div class="small" style="margin-top:6px;white-space:pre-wrap">${esc(h.content.slice(0, 400))}</div></div>`).join('');
      } catch (err) { toast(err.message, 'error'); }
    },
  },
  notify: {
    create: () => openFormChannel(null),
    edit: (id) => openFormChannel((state.notifyChannels || []).find((c) => c.id === id)),
    remove: (id) => openConfirmDelete('确认删除该通知渠道？', () => api(`/notifications/channels/${id}`, { method: 'DELETE' })),
    test: async (id) => {
      try { await api(`/notifications/channels/${id}/test`, { method: 'POST' }); toast('测试消息已发送', 'ok'); route(); }
      catch (err) { toast(err.message, 'error'); route(); }
    },
  },
  maintenance: {
    prune: async () => {
      if (!window.confirm('清理审计、通知、任务、交付、发布、补货日志中 30 天前的记录？')) return;
      try {
        const r = await api('/system/prune', { method: 'POST', body: { days: 30 } });
        toast(`已清理 ${r.result.total} 条旧日志`, 'ok'); route();
      } catch (err) { toast(err.message, 'error'); }
    },
  },
  backup: {
    create: async () => {
      try { await api('/backups', { method: 'POST' }); toast('备份已创建', 'ok'); route(); }
      catch (err) { toast(err.message, 'error'); }
    },
    remove: (name) => openConfirmDelete('确认删除该备份？', () => api(`/backups/${encodeURIComponent(name)}`, { method: 'DELETE' })),
    restore: async () => {
      const el = $('#restore-file');
      const file = el && el.files && el.files[0];
      if (!file) return toast('请选择备份文件', 'error');
      const fd = new FormData();
      fd.append('file', file);
      try {
        const res = await fetch('/api/backups/restore', { method: 'POST', body: fd, credentials: 'same-origin' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.ok === false) throw new Error(data.error || '恢复失败');
        toast(data.result?.note || '已安排恢复，请重启服务', 'ok');
        route();
      } catch (err) { toast(err.message, 'error'); }
    },
  },
  sim: {
    message: async () => {
      try {
        const r = await api('/sim/message', { method: 'POST', body: {
          account_id: Number($('#sim-msg-account').value), goods_id: Number($('#sim-msg-goods').value) || null,
          buyer: $('#sim-msg-buyer').value, text: $('#sim-msg-text').value,
        }});
        $('#sim-output').textContent = JSON.stringify(r, null, 2);
        toast(r.replied ? '已触发回复' : '消息已接收，无匹配回复', r.replied ? 'ok' : '');
      } catch (err) { toast(err.message, 'error'); }
    },
    order: async () => {
      try {
        const r = await api('/sim/order', { method: 'POST', body: {
          goods_id: Number($('#sim-order-goods').value), quantity: Number($('#sim-order-qty').value) || 1,
          buyer: $('#sim-order-buyer').value,
        }});
        $('#sim-output').textContent = JSON.stringify(r, null, 2);
        toast(r.delivery?.ok ? '订单已自动发货' : '订单已创建，发货失败', r.delivery?.ok ? 'ok' : 'error');
      } catch (err) { toast(err.message, 'error'); }
    },
    seed: async () => {
      try { const r = await api('/sim/seed-demo', { method: 'POST' }); $('#sim-output').textContent = JSON.stringify(r, null, 2); toast('演示数据已载入', 'ok'); }
      catch (err) { toast(err.message, 'error'); }
    },
  },
  users: {
    create: () => openFormUser(null),
    edit: (id) => openFormUser((state.users || []).find((u) => u.id === id)),
    toggle: async (id, active) => {
      try { await api(`/users/${id}`, { method: 'PATCH', body: { is_active: !!active } }); toast('已更新', 'ok'); route(); }
      catch (err) { toast(err.message, 'error'); }
    },
    remove: (id) => openConfirmDelete('删除用户前请确认其数据已清理，继续？', () => api(`/users/${id}`, { method: 'DELETE' })),
  },
  settings: {
    rotateToken: async () => {
      try {
        const r = await api('/integrations/token/rotate', { method: 'POST' });
        toast('新令牌已生成', 'ok'); route();
      } catch (err) { toast(err.message, 'error'); }
    },
    copyToken: async (token) => {
      if (!token) return toast('请先生成令牌', 'error');
      try { await navigator.clipboard.writeText(token); toast('已复制到剪贴板', 'ok'); }
      catch (e) { toast('复制失败，请手动选择', 'error'); }
    },
    save: async () => {
      const body = {
        ai_enabled: $('#set-ai-enabled').checked,
        ai_base_url: $('#set-ai-base').value.trim(),
        ai_model: $('#set-ai-model').value.trim(),
        ai_system_prompt: $('#set-ai-prompt').value,
        ai_kb_id: Number($('#set-ai-kb').value) || 0,
      };
      if ($('#set-ai-key').value.trim()) body.ai_api_key = $('#set-ai-key').value.trim();
      try { await api('/settings', { method: 'PUT', body }); toast('设置已保存', 'ok'); route(); }
      catch (err) { toast(err.message, 'error'); }
    },
    test: async () => {
      const el = $('#ai-test-result');
      el.textContent = '测试中…';
      try { const r = await api('/ai/test', { method: 'POST' }); el.textContent = `连通正常：${r.result.answer}`; }
      catch (err) { el.textContent = err.message; }
    },
  },
};
window.App = App;
window.route = route;

/* ------------------------------------------------------------------ form builders */
function openFormAccount(a) {
  modalForm(a ? '编辑账号' : '新建账号', [
    { name: 'name', label: '账号名称' },
    { name: 'cookie', label: 'Cookie', type: 'textarea', rows: 3, help: 'Mock 模式可填 demo-cookie；真实 Cookie 请妥善保管' },
    { name: 'proxy', label: '代理（可选）', placeholder: 'http://127.0.0.1:7890' },
    { name: 'note', label: '备注' },
    { name: 'ai_enabled', label: 'AI 回复', type: 'checkbox', checkboxLabel: '允许该账号使用 AI 兜底回复' },
    { name: 'auto_comment', label: '自动好评', type: 'checkbox', checkboxLabel: '订单发货成功后自动评价买家' },
    { name: 'comment_template', label: '好评内容', type: 'textarea', rows: 2, help: '留空使用默认文案；发货成功后调用 mtop 评价接口' },
  ], a || { ai_enabled: 1 }, async (data) => {
    if (a) await api(`/accounts/${a.id}`, { method: 'PATCH', body: data });
    else await api('/accounts', { method: 'POST', body: data });
    toast('已保存', 'ok'); route();
  });
}

function openFormGoods(g) {
  const accounts = state.accounts || [];
  modalForm(g ? '编辑商品' : '新建商品', [
    { name: 'title', label: '标题' },
    { name: 'price', label: '价格', type: 'number', step: '0.01' },
    { name: 'stock', label: '库存', type: 'number' },
    { name: 'account_id', label: '所属账号', type: 'select', options: accounts.map((a) => ({ value: a.id, label: a.name })), },
    { name: 'status', label: '状态', type: 'select', options: [{ value: 'on_sale', label: '在售' }, { value: 'off_shelf', label: '下架' }] },
    { name: 'image_url', label: '主图', type: 'image' },
    { name: 'description', label: '描述', type: 'textarea', rows: 3 },
  ], g || { status: 'on_sale', stock: 0, price: 0 }, async (data) => {
    if (g) await api(`/goods/${g.id}`, { method: 'PATCH', body: data });
    else await api('/goods', { method: 'POST', body: data });
    toast('已保存', 'ok'); route();
  });
}

function openFormReply(r) {
  const accounts = state.accounts || [];
  const goods = state.goods || [];
  modalForm(r ? '编辑回复规则' : '新建回复规则', [
    { name: 'name', label: '规则名称' },
    { name: 'account_id', label: '适用账号', type: 'select', options: accounts.map((a) => ({ value: a.id, label: a.name })), },
    { name: 'scope', label: '商品范围', type: 'select', options: [{ value: 'all', label: '全部商品' }, { value: 'goods', label: '指定商品' }] },
    { name: 'goods_id', label: '指定商品', type: 'select', options: goods.map((g) => ({ value: g.id, label: g.title })) },
    { name: 'match_type', label: '匹配方式', type: 'select', options: [{ value: 'keyword', label: '关键词' }, { value: 'exact', label: '精确' }, { value: 'regex', label: '正则' }] },
    { name: 'pattern', label: '匹配内容', help: '关键词用逗号分隔；正则需合法' },
    { name: 'reply_type', label: '回复类型', type: 'select', options: [{ value: 'text', label: '文本' }, { value: 'image', label: '图片' }, { value: 'ai', label: 'AI（兜底）' }] },
    { name: 'content', label: '回复内容', type: 'textarea', rows: 3, help: '支持 {{buyer}} {{goods_title}} 等变量' },
    { name: 'image_url', label: '回复图片（图片类型）', type: 'image' },
    { name: 'priority', label: '优先级', type: 'number', value: 0 },
    { name: 'enabled', label: '状态', type: 'checkbox', checkboxLabel: '启用' },
  ], r || { scope: 'all', match_type: 'keyword', reply_type: 'text', priority: 10, enabled: 1 }, async (data) => {
    data.enabled = !!data.enabled;
    if (r) await api(`/autoreply/rules/${r.id}`, { method: 'PATCH', body: data });
    else await api('/autoreply/rules', { method: 'POST', body: data });
    toast('已保存', 'ok'); route();
  });
}

function openFormSell(r) {
  const goods = state.goods || [];
  const workflows = state.workflows || [];
  modalForm(r ? '编辑发货规则' : '新建发货规则', [
    { name: 'name', label: '规则名称' },
    { name: 'goods_id', label: '绑定商品', type: 'select', options: goods.map((g) => ({ value: g.id, label: g.title })) },
    { name: 'delivery_type', label: '发货类型', type: 'select', options: [{ value: 'fixed', label: '固定内容' }, { value: 'stock', label: '库存卡密' }, { value: 'api', label: 'API 取货' }, { value: 'workflow', label: '流程发货' }] },
    { name: 'content', label: '固定内容 / 模板', type: 'textarea', rows: 3, help: '支持 {{order_no}} {{buyer}} {{quantity}}' },
    { name: 'multi_quantity', label: '多数量', type: 'checkbox', checkboxLabel: '按订单数量交付多份（库存/API）' },
    { name: 'workflow_id', label: '关联流程（流程发货）', type: 'select', options: workflows.map((w) => ({ value: w.id, label: w.name })) },
    { name: 'enabled', label: '状态', type: 'checkbox', checkboxLabel: '启用' },
  ], r || { delivery_type: 'fixed', enabled: 1, multi_quantity: 0 }, async (data) => {
    data.enabled = !!data.enabled;
    data.multi_quantity = !!data.multi_quantity;
    if (r) await api(`/autosell/rules/${r.id}`, { method: 'PATCH', body: data });
    else await api('/autosell/rules', { method: 'POST', body: data });
    toast('已保存', 'ok'); route();
  });
}

function openFormMonitor(t) {
  const accounts = state.accounts || [];
  modalForm(t ? '编辑监控任务' : '新建监控任务', [
    { name: 'name', label: '任务名称' },
    { name: 'keyword', label: '关键词' },
    { name: 'min_price', label: '最低价', type: 'number' },
    { name: 'max_price', label: '最高价', type: 'number' },
    { name: 'account_id', label: '执行账号', type: 'select', options: accounts.map((a) => ({ value: a.id, label: a.name })) },
    { name: 'interval_seconds', label: '间隔（秒）', type: 'number', value: 60 },
    { name: 'action', label: '命中动作', type: 'select', options: [{ value: 'notify', label: '通知' }, { value: 'dm', label: '自动私信' }, { value: 'order', label: '自动下单' }] },
    { name: 'enabled', label: '状态', type: 'checkbox', checkboxLabel: '启用' },
  ], t || { interval_seconds: 60, action: 'notify', enabled: 1 }, async (data) => {
    data.enabled = !!data.enabled;
    if (t) await api(`/monitor/tasks/${t.id}`, { method: 'PATCH', body: data });
    else await api('/monitor/tasks', { method: 'POST', body: data });
    toast('已保存', 'ok'); route();
  });
}

async function openStockModal(ruleId) {
  const data = await api(`/autosell/rules/${ruleId}/stock`);
  const rows = data.stock.map((s) => `<tr><td class="mono small">${esc(s.content)}</td><td>${badgeForStatus(s.status)}</td>
    <td class="small muted">${fmtTime(s.used_at)}</td><td class="actions">${s.status === 'available' ? `<button class="btn sm danger" onclick="App.sell.removeStock(${s.id})">删除</button>` : ''}</td></tr>`).join('');
  openModal('库存卡密', `
    <div class="row" style="margin-bottom:12px">
      <span class="badge green">可用 ${data.counts.available || 0}</span>
      <span class="badge">已用 ${data.counts.used || 0}</span>
    </div>
    <div class="field"><label>批量添加（每行一条）</label>
      <textarea class="input" id="stock-input" rows="4" placeholder="CARD-0001&#10;CARD-0002"></textarea></div>
    <button class="btn primary" onclick="App.sell.addStock(${ruleId})">添加</button>
    <div class="table-wrap" style="margin-top:12px;max-height:240px"><table class="tbl"><thead><tr><th>内容</th><th>状态</th><th>使用时间</th><th></th></tr></thead>
    <tbody>${rows || emptyRow(4)}</tbody></table></div>`, {});
}

App.sell.addStock = async (ruleId) => {
  const items = $('#stock-input').value.split('\n').map((s) => s.trim()).filter(Boolean);
  if (!items.length) return toast('请输入卡密', 'error');
  await api(`/autosell/rules/${ruleId}/stock`, { method: 'POST', body: { items } });
  toast('已添加', 'ok');
  openStockModal(ruleId);
};
App.sell.removeStock = async (id) => {
  await api(`/autosell/stock/${id}`, { method: 'DELETE' });
  toast('已删除', 'ok');
  closeModal();
};

function openWorkflowEditor(w) {
  const nodes = JSON.stringify(w ? w.nodes : [
    { id: 'start', type: 'trigger' },
    { id: 'deliver', type: 'deliver', content: '你好 {{buyer}}，这是你的内容：{{order_no}}' },
  ], null, 2);
  const edges = JSON.stringify(w ? w.edges : [{ from: 'start', to: 'deliver' }], null, 2);
  openModal(w ? '编辑流程' : '新建流程', `
    <div class="field"><label>流程名称</label><input class="input" id="wf-name" value="${esc(w?.name || '未命名流程')}"></div>
    <div class="grid cols-2">
      <div class="field"><label>节点 JSON</label><textarea class="input" id="wf-nodes" rows="14">${esc(nodes)}</textarea></div>
      <div class="field"><label>连线 JSON</label><textarea class="input" id="wf-edges" rows="14">${esc(edges)}</textarea></div>
    </div>`, {
    wide: true, submitText: '保存',
    onSubmit: async () => {
      let n, e;
      try { n = JSON.parse($('#wf-nodes').value); e = JSON.parse($('#wf-edges').value); }
      catch (err) { throw new Error('JSON 格式错误：' + err.message); }
      const payload = { name: $('#wf-name').value, nodes: n, edges: e };
      if (w) await api(`/workflows/${w.id}`, { method: 'PATCH', body: payload });
      else await api('/workflows', { method: 'POST', body: payload });
      toast('已保存', 'ok'); route();
    },
  });
}

async function openFormJob(job) {
  const [{ accounts }, { tasks }, { rules }] = await Promise.all([
    api('/accounts'), api('/monitor/tasks'), api('/auto-relist/rules'),
  ]);
  const cfg = job ? JSON.parse(job.config_json || '{}') : {};
  const types = { order_sync: '订单同步', monitor: '商品监控', relist: '自动补货', polish: '自动擦亮', backup: '自动备份', prune: '日志清理', report: '经营报表' };
  const sel = (a, b) => String(a) === String(b) ? 'selected' : '';
  const accountOpts = accounts.map((a) => `<option value="${a.id}" ${sel(a.id, cfg.account_id)}>${esc(a.name)}</option>`).join('');
  const taskOpts = tasks.map((t) => `<option value="${t.id}" ${sel(t.id, cfg.task_id)}>${esc(t.keyword)}</option>`).join('');
  const ruleOpts = rules.map((r) => `<option value="${r.id}" ${sel(r.id, cfg.rule_id)}>${esc(r.goods_title || ('规则 ' + r.id))}</option>`).join('');
  const html = `
    <div class="field"><label>任务名称</label><input class="input" id="job-name" value="${esc(job?.name || '')}" placeholder="例如 每小时同步订单"></div>
    <div class="grid-2">
      <div class="field"><label>类型</label><select class="input" id="job-type" onchange="App.jobs.formType()" ${job ? 'disabled' : ''}>
        ${Object.entries(types).map(([k, v]) => `<option value="${k}" ${sel(k, job?.type || 'order_sync')}>${v}</option>`).join('')}
      </select></div>
      <div class="field"><label>间隔（秒）</label><input class="input" id="job-interval" type="number" min="60" value="${job?.interval_seconds || 600}"></div>
    </div>
    <div class="job-sec" data-type="order_sync">
      <div class="field"><label>账号</label><select class="input" id="job-account">${accountOpts || '<option value="">（请先创建账号）</option>'}</select></div>
      <div class="field"><label>平台订单号</label><input class="input" id="job-order" value="${esc(cfg.order_id || '')}" placeholder="留空 = 同步订单列表"></div>
      <label class="check"><input type="checkbox" id="job-auto" ${cfg.auto_deliver ? 'checked' : ''}> 同步后自动发货</label>
      <div class="field"><label>列表模式页数</label><input class="input" id="job-pages" type="number" min="1" max="10" value="${cfg.pages || 1}"></div>
    </div>
    <div class="job-sec" data-type="monitor">
      <div class="field"><label>监控规则</label><select class="input" id="job-task">${taskOpts || '<option value="">（请先创建监控任务）</option>'}</select></div>
    </div>
    <div class="job-sec" data-type="relist">
      <div class="field"><label>补货规则</label><select class="input" id="job-rule">${ruleOpts || '<option value="">（请先创建补货规则）</option>'}</select></div>
    </div>
    <div class="job-sec" data-type="polish">
      <div class="field"><label>账号</label><select class="input" id="job-polish-account">${accountOpts || '<option value="">（请先创建账号）</option>'}</select></div>
      <div class="field"><label>商品 ID（每行一个）</label><textarea class="input" id="job-polish-items" rows="4">${esc((cfg.item_ids || []).join('\n'))}</textarea></div>
    </div>
    <div class="job-sec" data-type="backup"><p class="muted small">自动备份会创建完整 ZIP 备份，仅管理员可建。</p></div>
    <div class="job-sec" data-type="prune">
      <div class="field"><label>保留天数</label><input class="input" id="job-days" type="number" min="1" max="3650" value="${cfg.days || 30}"></div>
      <label class="check"><input type="checkbox" id="job-vacuum" ${cfg.vacuum ? 'checked' : ''}> 清理后执行 VACUUM</label>
      <p class="muted small">仅管理员可建；清理审计/通知/任务/交付/发布/补货日志。</p>
    </div>
    <div class="job-sec" data-type="report">
      <div class="field"><label>统计天数</label><select class="input" id="job-report-days">
        <option value="1" ${cfg.days == 1 ? 'selected' : ''}>近 1 天</option>
        <option value="7" ${cfg.days == 7 ? 'selected' : ''}>近 7 天</option>
        <option value="30" ${cfg.days == 30 ? 'selected' : ''}>近 30 天</option></select></div>
      <p class="muted small">统计订单/收入/退款/未读/在售，发送到当前用户自己的通知渠道。</p>
    </div>`;
  openModal(job ? '编辑任务' : '新建任务', html, {
    submitText: '保存',
    onSubmit: async () => {
      const type = $('#job-type').value;
      const name = ($('#job-name').value || '').trim();
      if (!name) throw new Error('任务名称不能为空');
      const config = {};
      if (type === 'order_sync') {
        config.account_id = Number($('#job-account').value);
        config.order_id = ($('#job-order').value || '').trim();
        config.auto_deliver = $('#job-auto').checked;
        config.pages = Number($('#job-pages').value || 1);
        if (!config.account_id) throw new Error('请选择账号');
      } else if (type === 'monitor') {
        config.task_id = Number($('#job-task').value);
      } else if (type === 'relist') {
        config.rule_id = Number($('#job-rule').value);
      } else if (type === 'polish') {
        config.account_id = Number($('#job-polish-account').value);
        config.item_ids = $('#job-polish-items').value;
        if (!config.account_id || !config.item_ids.trim()) throw new Error('请选择账号并填写商品 ID');
      } else if (type === 'prune') {
        config.days = Number($('#job-days').value || 30);
        config.vacuum = $('#job-vacuum').checked;
      } else if (type === 'report') {
        config.days = Number($('#job-report-days').value || 1);
      }
      const body = { name, type, interval_seconds: Number($('#job-interval').value || 600), config };
      if (job) await api(`/jobs/${job.id}`, { method: 'PATCH', body });
      else await api('/jobs', { method: 'POST', body });
      toast('已保存', 'ok'); route();
    },
  });
  App.jobs.formType();
}

function openFormUser(user) {
  const fields = user ? [
    { name: 'role', label: '角色', type: 'select', options: [{ value: 'operator', label: '运营' }, { value: 'admin', label: '管理员' }] },
    { name: 'is_active', label: '状态', type: 'checkbox', checkboxLabel: '启用账号' },
    { name: 'password', label: '重置密码（留空不修改）', type: 'password' },
  ] : [
    { name: 'username', label: '用户名' },
    { name: 'password', label: '密码（至少 6 位）', type: 'password' },
    { name: 'role', label: '角色', type: 'select', options: [{ value: 'operator', label: '运营' }, { value: 'admin', label: '管理员' }] },
  ];
  modalForm(user ? '编辑用户' : '新建用户', fields, user || { role: 'operator' }, async (data) => {
    if (user) {
      const payload = { role: data.role, is_active: !!data.is_active };
      if (data.password) payload.password = data.password;
      await api(`/users/${user.id}`, { method: 'PATCH', body: payload });
    } else {
      await api('/users', { method: 'POST', body: data });
    }
    toast('已保存', 'ok'); route();
  });
}

function openFormMaterial(m) {
  const accounts = state.accounts || [];
  modalForm(m ? '编辑素材' : '新建素材', [
    { name: 'name', label: '素材名称' },
    { name: 'title', label: '商品标题' },
    { name: 'price', label: '价格', type: 'number', step: '0.01' },
    { name: 'stock', label: '库存', type: 'number' },
    { name: 'account_id', label: '发布账号', type: 'select', options: accounts.map((a) => ({ value: a.id, label: a.name })) },
    { name: 'description', label: '描述', type: 'textarea', rows: 3 },
    { name: 'image_url', label: '主图', type: 'image' },
  ], m || { price: 0, stock: 0 }, async (data) => {
    if (m) await api(`/materials/${m.id}`, { method: 'PATCH', body: data });
    else await api('/materials', { method: 'POST', body: data });
    toast('已保存', 'ok'); route();
  });
}

function openFormRelist(rule) {
  const goods = state.goods || [];
  const materials = state.materials || [];
  modalForm(rule ? '编辑补货规则' : '新建补货规则', [
    { name: 'goods_id', label: '需要补货的商品', type: 'select', options: goods.map((g) => ({ value: g.id, label: g.title })) },
    { name: 'material_id', label: '使用素材', type: 'select', options: materials.map((m) => ({ value: m.id, label: m.name })) },
    { name: 'interval_seconds', label: '检查间隔（秒）', type: 'number', value: 600 },
    { name: 'enabled', label: '状态', type: 'checkbox', checkboxLabel: '启用' },
  ], rule || { interval_seconds: 600, enabled: 1 }, async (data) => {
    data.enabled = !!data.enabled;
    if (rule) await api(`/auto-relist/rules/${rule.id}`, { method: 'PATCH', body: data });
    else await api('/auto-relist/rules', { method: 'POST', body: data });
    toast('已保存', 'ok'); route();
  });
}

function openFormKnowledgeBase(kb) {
  modalForm(kb ? '编辑知识库' : '新建知识库', [
    { name: 'name', label: '名称' },
    { name: 'description', label: '描述', type: 'textarea', rows: 2 },
    { name: 'enabled', label: '状态', type: 'checkbox', checkboxLabel: '启用' },
  ], kb || { enabled: 1 }, async (data) => {
    data.enabled = !!data.enabled;
    if (kb) await api(`/knowledge/bases/${kb.id}`, { method: 'PATCH', body: data });
    else {
      const r = await api('/knowledge/bases', { method: 'POST', body: data });
      state.kbSelected = r.id;
    }
    toast('已保存', 'ok'); route();
  });
}

function openFormKnowledgeDoc(kbId, doc) {
  modalForm(doc ? '编辑文档' : '新建文档', [
    { name: 'title', label: '标题' },
    { name: 'content', label: '内容', type: 'textarea', rows: 14, help: '保存后自动按 400 字分块并建立检索索引' },
  ], doc || { title: '', content: '' }, async (data) => {
    if (doc) await api(`/knowledge/documents/${doc.id}`, { method: 'PATCH', body: data });
    else await api('/knowledge/documents', { method: 'POST', body: { ...data, kb_id: kbId } });
    toast('已保存', 'ok'); route();
  }, { wide: true });
}

function openFormChannel(ch) {
  const types = state.notifyTypes || {};
  const accounts = state.accounts || [];
  const typeOptions = Object.entries(types).map(([value, meta]) => ({ value, label: meta.label }));
  const firstType = typeOptions[0]?.value || 'bark';
  const example = types[firstType]?.example || {};
  const examples = Object.entries(types).map(([key, meta]) => `${key}: ${JSON.stringify(meta.example)}`).join('\n');
  const initial = ch || { enabled: 1, type: firstType, account_ids: [], config: JSON.stringify(example, null, 2) };
  modalForm(ch ? '编辑通知渠道' : '新建通知渠道', [
    { name: 'name', label: '渠道名称' },
    { name: 'type', label: '类型', type: 'select', options: typeOptions },
    { name: 'account_ids', label: '绑定账号', type: 'checks', options: accounts.map((a) => ({ value: a.id, label: a.name })), help: '不绑定则为全局渠道，所有账号事件都会发送' },
    { name: 'config', label: '配置 JSON', type: 'textarea', rows: 8, help: '示例：\n' + examples },
    { name: 'enabled', label: '状态', type: 'checkbox', checkboxLabel: '启用' },
  ], { ...initial, config: typeof initial.config === 'string' ? initial.config : JSON.stringify(initial.config, null, 2) }, async (data) => {
    let cfg;
    try { cfg = JSON.parse(data.config); } catch (e) { throw new Error('配置 JSON 格式错误'); }
    const payload = { name: data.name, type: data.type, config: cfg, enabled: !!data.enabled, account_ids: data.account_ids };
    if (ch) await api(`/notifications/channels/${ch.id}`, { method: 'PATCH', body: payload });
    else await api('/notifications/channels', { method: 'POST', body: payload });
    toast('已保存', 'ok'); route();
  });
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  try {
    const st = await fetch('/api/setup/status').then((r) => r.json());
    if (st.needs_setup) { renderSetup(); return; }
    const res = await fetch('/api/auth/me', { credentials: 'same-origin' });
    if (!res.ok) { renderLogin(); return; }
    const data = await res.json();
    state.user = data.user;
    renderShell();
    if (!location.hash) location.hash = '#/dashboard';
    route();
  } catch (err) {
    console.error(err);
    $('#boot').innerHTML = '<div class="boot-text">加载失败，请刷新页面</div>';
  }
}

window.addEventListener('hashchange', () => route());
boot();




































































