/* ================= غفون — مینی‌اپ تلگرام (بهینه شده) ================= */
const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
if (tg) {
  try {
    tg.ready(); tg.expand();
    tg.setHeaderColor('#070a14'); tg.setBackgroundColor('#070a14');
    tg.MainButton.setText('شروع بازی'); tg.MainButton.hide();
  } catch (e) {}
}
const INIT = tg ? (tg.initData || '') : '';

const SYM = ['♠','♥','♦','♣'];
const SUIT_FA = ['پیک','دل','خشت','گشنیز'];
const FA = {'0':'۰','1':'۱','2':'۲','3':'۳','4':'۴','5':'۵','6':'۶','7':'۷','8':'۸','9':'۹'};
const fa = s => String(s).replace(/[0-9]/g, d => FA[d]);

let state = null, seq = 0, uid = null, roomId = null, isHost = false, isNew = true;
let events = [], tab = 'game', menuOpen = false, timer = null, shareUrl = '';
let pendingSwap = null, lastSeq = 0;

const screen = document.getElementById('screen');
const scorebar = document.getElementById('scorebar');
const tabbar = document.getElementById('tabbar');
const feedEl = document.getElementById('feed');
const floatMenu = document.getElementById('floatMenu');
const menuBtn = document.getElementById('menuBtn');

/* ---------------- API ---------------- */
async function apiGet(path, params) {
  let url = path;
  if (params) {
    const qs = Object.entries(params).map(([k,v]) => `${k}=${encodeURIComponent(v)}`).join('&');
    url += (url.includes('?') ? '&' : '?') + qs;
  }
  url += (url.includes('?') ? '&' : '?') + 'initData=' + encodeURIComponent(INIT);
  const r = await fetch(url);
  return r.json();
}
async function apiAction(action, payload, rid) {
  const body = { initData: INIT, action, payload: payload || {} };
  if (rid) body.room_id = rid;
  const r = await fetch('/api/action', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
  });
  return r.json();
}

/* ---------------- راه‌اندازی ---------------- */
async function boot() {
  try {
    const r = await apiGet('/api/init');
    if (!r.ok) { renderJoin(); return; }
    uid = r.uid; roomId = r.room_id; isHost = r.is_host; isNew = r.is_new;
    shareUrl = r.share_url || '';
    state = r.state; seq = r.seq; lastSeq = seq; events = r.events || [];
    render();
    timer = setInterval(poll, 400);
    if (tg && isHost) {
      tg.MainButton.setText('شروع بازی');
      tg.MainButton.onClick(() => doAction('start', {}));
      tg.MainButton.show();
    }
  } catch (e) { renderJoin(); }
}
async function poll() {
  try {
    const r = await apiGet('/api/state', { seq: lastSeq, room_id: roomId });
    if (!r.ok) return;
    state = r.state; seq = r.seq; lastSeq = seq;
    if (r.events && r.events.length) events = events.concat(r.events);
    render();
  } catch (e) {}
}
async function doAction(action, payload) {
  try {
    const r = await apiAction(action, payload, roomId);
    if (!r.ok) {
      if (r.error) alert(r.error);
      return;
    }
    state = r.state; seq = r.seq; lastSeq = seq;
    if (r.events) events = events.concat(r.events);
    render();
  } catch (e) { alert('خطا در ارتباط با سرور'); }
}

/* ---------------- ابزارها ---------------- */
function esc(s) {
  return String(s).replace(/[&<>"]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
}
function seatOf(i) { return state && state.names ? (state.names[i] || '؟') : '؟'; }
function teamName(s) { return s % 2 === 0 ? 'تیم آبی' : 'تیم قرمز'; }
function isMe(s) { return s === (state && state.seat != null ? state.seat : -1); }
function myTurn() { return state && state.state === 'play' && state.turn === state.seat; }
function legalSet() { return new Set(state && state.legal ? state.legal : []); }

const RANK = {14:'A',13:'K',12:'Q',11:'J',10:'10',9:'9',8:'8',7:'7',6:'6',5:'5',4:'4',3:'3',2:'2'};

function cardHtml(c, cls, onclick) {
  const suit = Math.floor(c / 13), rank = c % 13 + 2;
  const red = (suit === 1 || suit === 2);
  const on = (cls && cls.includes('playable')) ? `onclick="${onclick}"` : '';
  return `<div class="card ${red ? 'red' : ''} ${cls || ''}" ${on}>
    <div class="top">${RANK[rank]}<br>${SYM[suit]}</div><div class="big">${SYM[suit]}</div></div>`;
}

/* ---------------- رندر ---------------- */
function render() {
  if (!state) return;
  renderScorebar();
  if (state.state === 'finished') { renderFinished(); return; }
  if (state.state === 'lobby') { renderLobby(); return; }
  renderGame();
  renderFeed();
  updateMainButton();
}

function renderScorebar() {
  if (!state) return;
  scorebar.innerHTML = `
    <span class="pill b">${fa(state.scores[0] || 0)}</span>
    <span class="pill ghost">دور ${fa(state.round || 0)}</span>
    <span class="pill r">${fa(state.scores[1] || 0)}</span>`;
  tabbar.classList.toggle('hidden', !(state.state !== 'lobby'));
}

function renderFeed() {
  const last = events.slice(-5);
  feedEl.innerHTML = last.map(e => `<div>${esc(e.text)}</div>`).join('');
}

/* ================= لابی ================= */
function renderLobby() {
  const meSeat = state.seat != null ? state.seat : -1;
  const playersHtml = (state.names || []).map((name, i) => {
    const isMeSeat = i === meSeat;
    return `<div class="player-tag ${isMeSeat ? 'me' : ''} ${!isMeSeat && (state.names[i]||'').includes('ربات') ? 'bot' : ''}">
      ${isMeSeat ? '👤' : '🎭'} ${esc(name)}
    </div>`;
  }).join('');

  const settings = isHost ? `
    <div class="panel">
      <h3>⚙️ تنظیمات بازی</h3>
      <div class="setting">
        <span class="lbl">امتیاز هدف</span>
        <span class="val" id="targetVal">${fa(state.target || 100)}</span>
      </div>
      <div class="row" style="margin-top:8px">
        <button class="btn small" onclick="setTarget(-1)">−</button>
        <button class="btn small gold" onclick="setTarget(1)">+</button>
      </div>
    </div>
  ` : '';

  const startBtn = isHost ? `
    <button class="card-btn" onclick="doAction('start', {})">
      ▶️ شروع بازی (${(state.names||[]).length}/۴ بازیکن)
    </button>
  ` : `<button class="card-btn secondary">منتظر شروع بازی توسط میزبان…</button>`;

  const inviteBtn = `
    <button class="card-btn ghost small invite-btn" onclick="shareGame()">🔗 لینک دعوت دوست‌ها</button>
  `;

  screen.innerHTML = `
    <div class="hero">
      <div class="icon">🎴</div>
      <h1>لابی غفون</h1>
      <p>${isHost ? 'شما میزبان بازی هستید. دوستان را دعوت کنید و سپس شروع بزنید.' : 'به بازی پیوستید. منتظر شروع توسط میزبانی…'}</p>
      <div class="players">${playersHtml}</div>
      ${settings}
      ${startBtn}
      ${inviteBtn}
    </div>`;
}

function setTarget(delta) {
  if (!isHost) return;
  const el = document.getElementById('targetVal');
  const cur = parseInt(el.innerText.replace(/[۰-۹]/g, d => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d)) || 100);
  const next = Math.min(200, Math.max(50, cur + delta * 25));
  el.innerText = fa(next);
  doAction('create-room', { target: next });
}

/* ================= بازی ================= */
function renderGame() {
  const me = state.seat != null ? state.seat : -1;
  const order = [(me + 2) % 4, (me + 3) % 4, (me + 1) % 4, me];
  const posNames = ['top','left','right','bottom'];
  const playedBy = {};
  (state.played || []).forEach(p => { playedBy[p.seat] = p.card; });

  let seatsHtml = '';
  order.forEach((s, idx) => {
    const pos = posNames[idx];
    const c = playedBy[s];
    const isTurn = state.state === 'play' && state.turn === s;
    seatsHtml += `<div class="seat ${pos} ${isTurn ? 'turn' : ''} ${s === me ? 'me' : ''}">
      <div class="nm">${esc(seatOf(s))}</div>
      <div class="team">${teamName(s)}</div>
      ${c != null ? `<div class="played ${Math.floor(c/13)===1||Math.floor(c/13)===2?'red':''}">${SYM[Math.floor(c/13)]}</div>` : `<div class="cnt">${fa((state.hand || []).length)} کارت</div>`}
    </div>`;
  });

  let centerHtml = '';
  if (state.trump != null) {
    const t = state.trump;
    const red = (t === 1 || t === 2);
    centerHtml = `<div class="trump" style="color:${red ? '#ff8a8a' : '#fff'}">${SYM[t]}</div>
      <div class="lbl">حکم: ${SUIT_FA[t]}</div>
      <div class="bid">اعتماد: ${fa(state.bid_value || 0)} دست</div>`;
  } else if (state.state === 'bid') {
    centerHtml = `<div class="lbl">مرحله اعتماد</div>
      <div class="bid">بیشترین اعتماد: ${fa(state.bid_max || 0)}</div>`;
  } else {
    centerHtml = `<div class="lbl">در حال آمادگی…</div>`;
  }

  let handHtml = '';
  if (state.state === 'play' && state.hand) {
    const legal = legalSet();
    const mt = myTurn();
    handHtml = `<div class="hand">${(state.hand).map(c =>
      cardHtml(c, (mt && legal.has(c) ? 'playable' : 'off'), (mt && legal.has(c) ? `doAction('play',{card:${c}})` : ''))
    ).join('')}</div>
    <div class="turn-banner">${mt ? '🟢 نوبت شماست — کارت بازی کنید' : 'نوبت: ' + esc(seatOf(state.turn))}</div>`;
  }

  let panelHtml = '';
  if (state.state === 'bid' && state.current_bidder === state.seat) {
    const vals = [];
    for (let v = (state.bid_max || 0) + 1; v <= 13; v++) vals.push(v);
    panelHtml = `<div class="panel"><h3>🔊 نوبت شماست — اعتماد بزنید</h3>
      <div class="row">${vals.map(v => `<button class="btn gold" onclick="doAction('bid',{value:${v}})">${fa(v)}</button>`).join('')}</div>
      <div class="row" style="margin-top:8px"><button class="btn pass" onclick="doAction('bid',{value:0})">پاس</button></div></div>`;
  }
  if (state.state === 'trump' && state.ruler === state.seat) {
    panelHtml = `<div class="panel"><h3>👑 شما حاکم هستید — خال حکم را انتخاب کنید</h3>
      <div class="row">${[0,1,2,3].map(s => `<button class="btn suit ${s===1||s===2?'red':''}" onclick="doAction('trump',{suit:${s}})">${SYM[s]} ${SUIT_FA[s]}</button>`).join('')}</div></div>`;
  }

  screen.innerHTML = `
    <div class="table-wrap">${seatsHtml}<div class="center">${centerHtml}</div></div>
    ${panelHtml}
    ${handHtml}`;
}

/* ================= پایان ================= */
function renderFinished() {
  const win = state.scores[0] >= state.scores[1] ? 0 : 1;
  const meWon = win === (state.seat % 2);
  screen.innerHTML = `
    <div class="hero">
      <div class="icon" style="font-size:80px">${meWon ? '🏆' : '😔'}</div>
      <h1>${meWon ? 'برنده‌اید!' : 'باختید'}</h1>
      <p>امتیاز نهایی: ${fa(state.scores[0])} — ${fa(state.scores[1])}</p>
      <button class="card-btn" onclick="doAction('again', {})">🔄 بازی دوباره</button>
      <button class="card-btn secondary" onclick="switchTab('help')">📋 راهنما</button>
    </div>`;
}

/* ================= صندلی‌ها ================= */
function renderSeats() {
  const rows = [];
  for (let s = 0; s < 4; s++) {
    rows.push(`<div class="seatrow" style="display:flex;align-items:center;justify-content:space-between;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px;margin:8px 0 ${pendingSwap === s ? '0' : '8px'}">
      <div>
        <div class="who" style="font-weight:900">صندلی ${fa(s+1)}: ${esc(seatOf(s))}</div>
        <div class="team" style="font-size:12px;color:var(--muted)">${teamName(s)} ${s === (state.seat || -1) ? '(شما)' : ''}</div>
      </div>
      <button class="btn ${pendingSwap === s ? 'gold' : ''}" onclick="pickSeat(${s})">${pendingSwap === s ? '✓ انتخاب' : 'انتخاب'}</button>
    </div>`);
  }
  screen.innerHTML = `
    <div class="panel"><h3>🪑 چیدن صندلی</h3>
      <div style="display:flex;flex-direction:column;gap:8px">${rows.join('')}</div>
      <div class="note">دو صندلی را پشت سر هم انتخاب کنید تا جابه‌جا شوند. (فقط میزبان، قبل از شروع)</div>
    </div>
    <button class="card-btn secondary" onclick="switchTab('game')">بازگشت به بازی</button>`;
}
function pickSeat(s) {
  if (!isHost) return;
  if (pendingSwap === null) { pendingSwap = s; renderSeats(); return; }
  if (pendingSwap === s) { pendingSwap = null; renderSeats(); return; }
  doAction('swap', { a: pendingSwap, b: s }); pendingSwap = null;
}

/* ================= راهنما ================= */
function renderHelp() {
  screen.innerHTML = `<div class="panel">
    <h3>📋 راهنمای غفون</h3>
    <div class="help">
      <b>اعتماد:</b> هر نفر عدد بالاتر می‌زند یا پاس؛ بالاترین-dependent <b>حاکم</b> می‌شود و حکم را انتخاب می‌کند.<br>
      <b>بازی:</b> برنده‌ی دست، دست بعد را آغاز می‌کند. اگر خال زمینه دارید، باید دنبالش بزنید. حکم بر همه می‌برد.<br>
      <b>امتیاز:</b> اگر تیم حکومت به اعتماد X برسد → Y امتیاز؛ اگر نفـکند → حریف ۲X می‌گیرد.<br>
      <b>پایان:</b> تیمی که اول به هدف برسد.<br>
      <b>تیم‌ها:</b> صندلی‌های ۱ و ۳ در برابر ۲ و ۴.
    </div>
  </div>
  <button class="card-btn secondary" onclick="switchTab('game')">بازگشت</button>`;
}

/* ================= صفحه بدء ================= */
function renderJoin() {
  screen.innerHTML = `
    <div class="join-box">
      <div class="icon">🎴</div>
      <h1>غفون</h1>
      <p>کلمة با اعلام دست — ۴ نفره، تیمی، زیبا</p>
      <div class="linkbox">
        <input id="roomInput" placeholder="کد اتاق (اختیاری)">
        <button class="btn copy" onclick="joinByCode()">ورود</button>
      </div>
      <button class="card-btn" onclick="createNewRoom()">✨ ساخت اتاق جدید</button>
      <div class="note">لینک اتاق را به دوستان بفرستید تا با هم بازی کنید.</div>
    </div>`;
  tabbar.classList.add('hidden');
  scorebar.innerHTML = '';
}

/* ---------------- akcje ---------------- */
function createNewRoom() {
  doAction('create-room', {});
}
function joinByCode() {
  const code = document.getElementById('roomInput').value.trim();
  if (!code) { alert('کد اتاق را وارد کنید'); return; }
  doAction('join-room', {}, code);
}
function shareGame() {
  const url = shareUrl || (location.origin + location.pathname + '?room_id=' + (roomId || ''));
  if (tg && tg.share) { tg.share({ text: 'بازی غفون را بزنیم!', url }); }
  else { navigator.clipboard.writeText(url).then(() => alert('لینک کپی شد: ' + url)); }
}
function endGame() {
  if (!isHost) { alert('فقط میزبان می‌تواند بازی را پایان دهد.'); return; }
  if (!confirm('مطمئن هستید؟')) return;
  doAction('end', {});
}
function switchTab(t) {
  tab = t;
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('on', b.dataset.tab === t));
  if (t === 'seats') renderSeats();
  else if (t === 'help') renderHelp();
  else renderGame();
}
function toggleMenu() {
  menuOpen = !menuOpen;
  floatMenu.classList.toggle('on', menuOpen);
}
function closeMenu() { menuOpen = false; floatMenu.classList.remove('on'); }
function updateMainButton() {
  if (!tg || !isHost) return;
  if (state.state === 'lobby') {
    tg.MainButton.setText('شروع بازی');
    tg.MainButton.show();
  } else {
    tg.MainButton.hide();
  }
}

document.getElementById('app').addEventListener('click', (e) => {
  if (menuOpen && !floatMenu.contains(e.target) && e.target !== menuBtn) closeMenu();
});

boot();
