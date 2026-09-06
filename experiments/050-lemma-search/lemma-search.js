const DATA_FILE = 'https://raw.githubusercontent.com/theologia165/torah-hebrew-html/main/experiments/050-lemma-search/050-genesis-32-4.json';
const MORPHHB_COMMIT = '3d15126fb1ef74867fc1434be1942e837932691f';
const RAW_BASE = `https://raw.githubusercontent.com/openscriptures/morphhb/${MORPHHB_COMMIT}/wlc/`;
const MAX_RENDER_TOTAL = 2200;
const MAX_RENDER_PER_BOOK = 140;

const BOOKS = [
  {id:'Gen',ja:'創世記',group:'torah'},{id:'Exod',ja:'出エジプト記',group:'torah'},{id:'Lev',ja:'レビ記',group:'torah'},{id:'Num',ja:'民数記',group:'torah'},{id:'Deut',ja:'申命記',group:'torah'},
  {id:'Josh',ja:'ヨシュア記',group:'former'},{id:'Judg',ja:'士師記',group:'former'},{id:'1Sam',ja:'サムエル記第一',group:'former'},{id:'2Sam',ja:'サムエル記第二',group:'former'},{id:'1Kgs',ja:'列王記第一',group:'former'},{id:'2Kgs',ja:'列王記第二',group:'former'},
  {id:'Isa',ja:'イザヤ書',group:'latter'},{id:'Jer',ja:'エレミヤ書',group:'latter'},{id:'Ezek',ja:'エゼキエル書',group:'latter'},{id:'Hos',ja:'ホセア書',group:'latter'},{id:'Joel',ja:'ヨエル書',group:'latter'},{id:'Amos',ja:'アモス書',group:'latter'},{id:'Obad',ja:'オバデヤ書',group:'latter'},{id:'Jonah',ja:'ヨナ書',group:'latter'},{id:'Mic',ja:'ミカ書',group:'latter'},{id:'Nah',ja:'ナホム書',group:'latter'},{id:'Hab',ja:'ハバクク書',group:'latter'},{id:'Zeph',ja:'ゼパニヤ書',group:'latter'},{id:'Hag',ja:'ハガイ書',group:'latter'},{id:'Zech',ja:'ゼカリヤ書',group:'latter'},{id:'Mal',ja:'マラキ書',group:'latter'},
  {id:'Ps',ja:'詩篇',group:'writings'},{id:'Job',ja:'ヨブ記',group:'writings'},{id:'Prov',ja:'箴言',group:'writings'},{id:'Ruth',ja:'ルツ記',group:'writings'},{id:'Song',ja:'雅歌',group:'writings'},{id:'Eccl',ja:'伝道者の書',group:'writings'},{id:'Lam',ja:'哀歌',group:'writings'},{id:'Esth',ja:'エステル記',group:'writings'},{id:'Dan',ja:'ダニエル書',group:'writings'},{id:'Ezra',ja:'エズラ記',group:'writings'},{id:'Neh',ja:'ネヘミヤ記',group:'writings'},{id:'1Chr',ja:'歴代誌第一',group:'writings'},{id:'2Chr',ja:'歴代誌第二',group:'writings'}
];

const STEMS = {
  q:'Qal', N:'Niphal', p:'Piel', P:'Pual', h:'Hiphil', H:'Hophal', t:'Hithpael',
  o:'Polel', O:'Polal', r:'Hithpolel', m:'Poel', M:'Poal', k:'Palel', K:'Pulal', Q:'Qal passive'
};
const ASPECTS = {
  p:'完了形', q:'weqatal（連続完了形）', i:'未完了形', w:'wayyiqtol', h:'コホルタティブ系',
  v:'命令形', r:'分詞', a:'不定詞絶対形', c:'不定詞連語形'
};
const SCOPE_LABELS = {all:'全ヘブライ語聖書',torah:'トーラー',former:'前預言者',latter:'後預言者',writings:'諸書',current:'この書（創世記）',custom:'個別選択'};

let data = null;
let activeToken = null;
let searchToken = null;
let scopeMode = 'all';
let searchSerial = 0;
const bookCache = new Map();

function esc(s='') {
  return String(s).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function numericStrong(strong) {
  return String(strong || '').replace(/^H0*/, '').replace(/^0+/, '');
}

function lemmaMatches(code, strong) {
  const target = numericStrong(strong);
  return String(code || '').split('/').some(part => {
    const m = part.trim().match(/^(\d+)/);
    return m && String(parseInt(m[1], 10)) === target;
  });
}

function surfaceOf(w) {
  return (w.textContent || '').replaceAll('/', '');
}

function normalizeForm(value) {
  return String(value || '')
    .replaceAll('/', '')
    .normalize('NFD')
    .replace(/[\u0591-\u05AF\u05BD]/g, '')
    .replace(/[\u200E\u200F]/g, '');
}

function verbFeatures(morphCode) {
  let code = String(morphCode || '');
  if (code.startsWith('H')) code = code.slice(1);
  const component = code.split('/').find(x => x.startsWith('V')) || '';
  return {
    stem: component.length > 1 ? component[1] : '',
    aspect: component.length > 2 ? component[2] : '',
    component
  };
}

function morphologyLabel(record) {
  const parts = [];
  if (record.stem) parts.push(STEMS[record.stem] || record.stem);
  if (record.aspect) parts.push(ASPECTS[record.aspect] || record.aspect);
  return parts.length ? `${parts.join(' · ')} / ${record.morphCode}` : record.morphCode;
}

function verseRef(osisID, book) {
  const bits = String(osisID || '').split('.');
  if (bits.length >= 3) return `${book.ja} ${bits[1]}:${bits[2]}`;
  return `${book.ja} (${osisID || book.id})`;
}

function renderVerse() {
  const verse = document.getElementById('verse');
  verse.innerHTML = '';
  for (const w of data.words) {
    const wrap = document.createElement('span');
    wrap.className = 'word';
    const token = document.createElement('span');
    token.className = 'tok';
    token.tabIndex = 0;
    token.dir = 'rtl';
    token.textContent = w.surface;
    Object.assign(token.dataset, {lemma:w.lemma,strong:w.strong,pos:w.pos,morph:w.morph});
    const gloss = document.createElement('span');
    gloss.className = 'gloss';
    gloss.textContent = w.gloss;
    wrap.append(token, gloss);
    verse.append(wrap);
    if (w.separator_after) {
      const sep = document.createElement('span');
      sep.className = 'sep';
      sep.setAttribute('aria-hidden', 'true');
      sep.textContent = w.separator_after;
      verse.append(sep);
    }
  }
}

function showHover(token) {
  const popup = document.getElementById('hoverPopup');
  activeToken?.classList.remove('active');
  activeToken = token;
  token.classList.add('active');
  popup.innerHTML = `<b>lemma：</b><span dir="rtl">${esc(token.dataset.lemma)}</span><br>` +
    `<b>品詞：</b>${esc(token.dataset.pos)}<br>` +
    `<b>形態：</b>${esc(token.dataset.morph)}<br>` +
    `<span class="hint">右クリック：lemma / Form / Qal / wayyiqtol などを検索</span>`;
  popup.classList.add('open');
  requestAnimationFrame(() => positionFloating(popup, token.getBoundingClientRect()));
}

function positionFloating(el, anchorRect) {
  const p = el.getBoundingClientRect();
  const gap = 8, margin = 8;
  let left = anchorRect.left + anchorRect.width / 2 - p.width / 2;
  left = Math.max(margin, Math.min(left, innerWidth - p.width - margin));
  let top = anchorRect.bottom + gap;
  if (top + p.height > innerHeight - margin) top = anchorRect.top - p.height - gap;
  top = Math.max(margin, Math.min(top, innerHeight - p.height - margin));
  el.style.left = `${left}px`;
  el.style.top = `${top}px`;
}

function closeHover() {
  document.getElementById('hoverPopup').classList.remove('open');
  activeToken?.classList.remove('active');
  activeToken = null;
}

function showContextMenu(token, x, y) {
  closeHover();
  const menu = document.getElementById('contextMenu');
  menu.innerHTML = `
    <div class="context-head">
      <span class="context-surface" dir="rtl">${esc(token.textContent)}</span>
      <span>lemma: <b dir="rtl">${esc(token.dataset.lemma)}</b></span>
    </div>
    <button data-quick="lemma" type="button">同じ lemma を検索</button>
    <button data-quick="form" type="button">同じ Form（語形）を検索</button>
    <button data-quick="advanced" class="advanced" type="button">詳細検索：Qal / wayyiqtol / 範囲指定…</button>
  `;
  menu.classList.add('open');
  const margin = 8;
  requestAnimationFrame(() => {
    const r = menu.getBoundingClientRect();
    menu.style.left = `${Math.max(margin, Math.min(x, innerWidth - r.width - margin))}px`;
    menu.style.top = `${Math.max(margin, Math.min(y, innerHeight - r.height - margin))}px`;
  });
  menu.querySelectorAll('[data-quick]').forEach(btn => {
    btn.onclick = () => {
      menu.classList.remove('open');
      const mode = btn.dataset.quick;
      openSearchPanel(token, mode === 'advanced' ? null : mode, mode !== 'advanced');
    };
  });
}

async function fetchBookRecords(book) {
  if (bookCache.has(book.id)) return bookCache.get(book.id);
  const promise = fetch(`${RAW_BASE}${book.id}.xml`, {cache:'force-cache'})
    .then(r => {
      if (!r.ok) throw new Error(`${book.ja}: HTTP ${r.status}`);
      return r.text();
    })
    .then(text => {
      const xml = new DOMParser().parseFromString(text, 'application/xml');
      if (xml.querySelector('parsererror')) throw new Error(`${book.ja}: XML解析エラー`);
      const records = [];
      for (const verse of Array.from(xml.getElementsByTagNameNS('*', 'verse'))) {
        const osis = verse.getAttribute('osisID') || '';
        const ref = verseRef(osis, book);
        for (const w of Array.from(verse.getElementsByTagNameNS('*', 'w'))) {
          const morphCode = w.getAttribute('morph') || '';
          const vf = verbFeatures(morphCode);
          const surface = surfaceOf(w);
          records.push({
            bookId:book.id, bookJa:book.ja, osis, ref, surface,
            form:normalizeForm(surface), lemmaCode:w.getAttribute('lemma') || '', morphCode,
            stem:vf.stem, aspect:vf.aspect
          });
        }
      }
      return records;
    });
  bookCache.set(book.id, promise);
  return promise;
}

function booksForMode(mode) {
  if (mode === 'all') return BOOKS;
  if (mode === 'current') return BOOKS.filter(b => b.id === 'Gen');
  if (['torah','former','latter','writings'].includes(mode)) return BOOKS.filter(b => b.group === mode);
  if (mode === 'custom') {
    const checked = new Set(Array.from(document.querySelectorAll('.book-check input:checked')).map(x => x.value));
    return BOOKS.filter(b => checked.has(b.id));
  }
  return BOOKS;
}

function stemOptions() {
  return `<option value="">指定なし</option>` + Object.entries(STEMS).map(([code,label]) => `<option value="${code}">${esc(label)}</option>`).join('');
}

function aspectOptions() {
  return `<option value="">指定なし</option>` + Object.entries(ASPECTS).map(([code,label]) => `<option value="${code}">${esc(label)}</option>`).join('');
}

function renderSearchControls(token) {
  const controls = document.getElementById('searchControls');
  controls.innerHTML = `
    <div class="search-controls">
      <div class="control-card">
        <div class="control-title">よく使う検索</div>
        <div class="preset-row">
          <button class="preset" data-preset="lemma" type="button">lemma</button>
          <button class="preset" data-preset="form" type="button">Form</button>
          <button class="preset morph" data-preset="qal" type="button">Qalだけ</button>
          <button class="preset morph" data-preset="wayyiqtol" type="button">wayyiqtolだけ</button>
          <button class="preset morph" data-preset="qalway" type="button">Qal + wayyiqtol</button>
          <button class="preset morph" data-preset="lemmaqalway" type="button">lemma + Qal + wayyiqtol</button>
        </div>
      </div>

      <div class="control-card">
        <div class="control-title">検索条件</div>
        <div class="target-preview">
          <span class="heb" dir="rtl">${esc(token.textContent)}</span>
          <span>lemma <b dir="rtl">${esc(token.dataset.lemma)}</b></span>
          <code>${esc(token.dataset.strong)}</code>
        </div>
        <div class="query-grid">
          <div class="field">
            <label for="baseMode">語彙・語形</label>
            <select id="baseMode">
              <option value="lemma">同じ lemma</option>
              <option value="form">同じ Form</option>
              <option value="any">指定しない（形態だけで検索）</option>
            </select>
          </div>
          <div class="field">
            <label for="stemMode">語幹</label>
            <select id="stemMode">${stemOptions()}</select>
          </div>
          <div class="field">
            <label for="aspectMode">活用形</label>
            <select id="aspectMode">${aspectOptions()}</select>
          </div>
        </div>
        <div class="control-help">条件はAND検索です。Formは母音を保持し、朗読アクセントとメテグだけを無視して一致判定します。「Qalだけ」ではlemmaを限定せず、指定範囲内のQal動詞を検索します。</div>
      </div>

      <div class="control-card">
        <div class="control-title">検索範囲</div>
        <div class="scope-row">
          ${['all','torah','former','latter','writings','current','custom'].map(mode => `<button class="scope-btn${scopeMode===mode?' active':''}" data-scope="${mode}" type="button">${SCOPE_LABELS[mode]}</button>`).join('')}
        </div>
        <details id="customBooks" class="custom-books"${scopeMode==='custom'?' open':''}>
          <summary>書を個別に選択</summary>
          <div class="book-select-actions"><button id="allBooks" class="mini" type="button">すべて選択</button><button id="noBooks" class="mini" type="button">すべて解除</button></div>
          <div class="book-check-grid">
            ${BOOKS.map(b => `<label class="book-check"><input type="checkbox" value="${b.id}" checked>${esc(b.ja)}</label>`).join('')}
          </div>
        </details>
      </div>

      <div class="search-action-row">
        <button id="runSearch" class="run-search" type="button">この条件で検索</button>
        <span id="criteriaPreview" class="criteria-preview"></span>
      </div>
    </div>`;

  controls.querySelectorAll('[data-preset]').forEach(btn => btn.onclick = () => applyPreset(btn.dataset.preset));
  controls.querySelectorAll('[data-scope]').forEach(btn => btn.onclick = () => setScope(btn.dataset.scope));
  ['baseMode','stemMode','aspectMode'].forEach(id => document.getElementById(id).onchange = updateCriteriaPreview);
  document.querySelectorAll('.book-check input').forEach(cb => cb.onchange = () => { scopeMode='custom'; syncScopeButtons(); updateCriteriaPreview(); });
  document.getElementById('allBooks').onclick = () => { document.querySelectorAll('.book-check input').forEach(x => x.checked=true); scopeMode='custom'; syncScopeButtons(); updateCriteriaPreview(); };
  document.getElementById('noBooks').onclick = () => { document.querySelectorAll('.book-check input').forEach(x => x.checked=false); scopeMode='custom'; syncScopeButtons(); updateCriteriaPreview(); };
  document.getElementById('runSearch').onclick = runSearch;
  updateCriteriaPreview();
}

function applyPreset(name) {
  const base = document.getElementById('baseMode');
  const stem = document.getElementById('stemMode');
  const aspect = document.getElementById('aspectMode');
  const presets = {
    lemma:['lemma','',''], form:['form','',''], qal:['any','q',''], wayyiqtol:['any','','w'],
    qalway:['any','q','w'], lemmaqalway:['lemma','q','w']
  };
  const values = presets[name] || presets.lemma;
  [base.value,stem.value,aspect.value] = values;
  document.querySelectorAll('.preset').forEach(x => x.classList.toggle('active', x.dataset.preset === name));
  updateCriteriaPreview();
}

function setScope(mode) {
  scopeMode = mode;
  if (mode === 'custom') document.getElementById('customBooks').open = true;
  syncScopeButtons();
  updateCriteriaPreview();
}

function syncScopeButtons() {
  document.querySelectorAll('.scope-btn').forEach(x => x.classList.toggle('active', x.dataset.scope === scopeMode));
}

function readCriteria() {
  return {
    base:document.getElementById('baseMode').value,
    stem:document.getElementById('stemMode').value,
    aspect:document.getElementById('aspectMode').value,
    books:booksForMode(scopeMode)
  };
}

function criteriaParts(criteria) {
  const parts = [];
  if (criteria.base === 'lemma') parts.push(`lemma=${searchToken?.dataset.lemma || ''}`);
  if (criteria.base === 'form') parts.push(`Form=${normalizeForm(searchToken?.textContent || '')}`);
  if (criteria.stem) parts.push(`語幹=${STEMS[criteria.stem] || criteria.stem}`);
  if (criteria.aspect) parts.push(`活用=${ASPECTS[criteria.aspect] || criteria.aspect}`);
  return parts;
}

function updateCriteriaPreview() {
  if (!document.getElementById('baseMode')) return;
  const c = readCriteria();
  const parts = criteriaParts(c);
  const scope = scopeMode === 'custom' ? `個別 ${c.books.length}書` : SCOPE_LABELS[scopeMode];
  document.getElementById('criteriaPreview').innerHTML = `<b>${esc(parts.join(' ＋ ') || '条件未指定')}</b> ／ ${esc(scope)}`;
}

function openSearchPanel(token, preset=null, autoRun=false) {
  searchToken = token;
  const panel = document.getElementById('resultsPanel');
  panel.hidden = false;
  document.getElementById('resultsTitle').textContent = '語形・形態検索';
  document.getElementById('selectedWordLabel').innerHTML = `選択語：<span dir="rtl">${esc(token.textContent)}</span> / lemma <span dir="rtl">${esc(token.dataset.lemma)}</span>`;
  document.getElementById('resultsBody').innerHTML = '';
  renderSearchControls(token);
  if (preset) applyPreset(preset);
  panel.scrollIntoView({behavior:'smooth',block:'start'});
  if (autoRun) runSearch();
}

function matchesCriteria(record, criteria) {
  if (criteria.base === 'lemma' && !lemmaMatches(record.lemmaCode, searchToken.dataset.strong)) return false;
  if (criteria.base === 'form' && record.form !== normalizeForm(searchToken.textContent)) return false;
  if (criteria.stem && record.stem !== criteria.stem) return false;
  if (criteria.aspect && record.aspect !== criteria.aspect) return false;
  return true;
}

async function mapLimit(items, limit, fn) {
  const results = new Array(items.length);
  let next = 0;
  async function worker() {
    while (true) {
      const i = next++;
      if (i >= items.length) return;
      results[i] = await fn(items[i], i);
    }
  }
  await Promise.all(Array.from({length:Math.min(limit,items.length)}, worker));
  return results;
}

async function runSearch() {
  const criteria = readCriteria();
  const body = document.getElementById('resultsBody');
  if (!criteria.books.length) {
    body.innerHTML = `<div class="warning">検索する書が選択されていません。</div>`;
    return;
  }
  if (criteria.base === 'any' && !criteria.stem && !criteria.aspect) {
    body.innerHTML = `<div class="warning">形態だけで検索する場合は、語幹または活用形を一つ以上指定してください。</div>`;
    return;
  }

  const serial = ++searchSerial;
  const parts = criteriaParts(criteria);
  const scopeLabel = scopeMode === 'custom' ? `個別 ${criteria.books.length}書` : SCOPE_LABELS[scopeMode];
  body.innerHTML = `<div class="loading">固定MorphHB（${esc(MORPHHB_COMMIT.slice(0,12))}…）を検索中… <span id="progress">0/${criteria.books.length}</span><div class="progress-bar"><span id="progressBar"></span></div></div>`;
  let done = 0;
  const failures = [];
  const perBook = new Map();

  await mapLimit(criteria.books, 5, async book => {
    try {
      const records = await fetchBookRecords(book);
      if (serial !== searchSerial) return;
      const hits = records.filter(r => matchesCriteria(r, criteria));
      if (hits.length) perBook.set(book.id, {book,hits});
    } catch (e) {
      failures.push(String(e.message || e));
    } finally {
      done += 1;
      if (serial === searchSerial) {
        const progress = document.getElementById('progress');
        const bar = document.getElementById('progressBar');
        if (progress) progress.textContent = `${done}/${criteria.books.length}`;
        if (bar) bar.style.width = `${Math.round(done / criteria.books.length * 100)}%`;
      }
    }
  });
  if (serial !== searchSerial) return;

  const total = Array.from(perBook.values()).reduce((n,x) => n + x.hits.length, 0);
  let renderedTotal = 0;
  let html = `<div class="result-summary"><b>${total}</b>件 <span>${esc(scopeLabel)}</span>` + parts.map(x => `<span class="result-filter">${esc(x)}</span>`).join('') + `</div>`;

  for (const book of criteria.books) {
    const group = perBook.get(book.id);
    if (!group) continue;
    const capacity = Math.max(0, MAX_RENDER_TOTAL - renderedTotal);
    const showCount = Math.min(group.hits.length, MAX_RENDER_PER_BOOK, capacity);
    if (showCount <= 0) break;
    renderedTotal += showCount;
    html += `<details class="book-group"><summary>${esc(book.ja)} <b>${group.hits.length}</b>件</summary><div class="hit-list">`;
    for (const hit of group.hits.slice(0,showCount)) {
      html += `<div class="hit"><span class="hit-ref">${esc(hit.ref)}</span><span class="hit-main"><span class="hit-word" dir="rtl">${esc(hit.surface)}</span><span class="hit-morph">${esc(morphologyLabel(hit))}</span></span></div>`;
    }
    if (showCount < group.hits.length) html += `<div class="more-note">この書は ${showCount}/${group.hits.length}件を表示。条件を絞ると全件を確認しやすくなります。</div>`;
    html += `</div></details>`;
  }

  if (total > renderedTotal) html += `<div class="warning">該当件数が多いため、画面負荷を避けて ${renderedTotal}/${total}件を表示しています。lemma・語幹・活用形・検索範囲を組み合わせると絞り込めます。</div>`;
  if (!total) html += `<div class="warning">この条件に一致する語は見つかりませんでした。</div>`;
  if (failures.length) html += `<div class="warning">取得できなかった書：${esc(failures.join(' / '))}</div>`;
  html += `<div class="source-note">検索元：Open Scriptures Hebrew Bible / MorphHB (WLC), CC BY 4.0。形態判定はMorphHBの形態コードを使用しています。Form検索では母音を保持し、朗読アクセントとメテグを除いて比較します。データはブラウザ内でGitHubから取得し、初回取得後は書ごとにキャッシュします。</div>`;
  body.innerHTML = html;
}

function wireEvents() {
  document.querySelectorAll('.tok').forEach(token => {
    token.addEventListener('mouseenter', () => { if (matchMedia('(pointer:fine)').matches) showHover(token); });
    token.addEventListener('mouseleave', () => { if (matchMedia('(pointer:fine)').matches && !token.matches(':focus')) closeHover(); });
    token.addEventListener('focus', () => showHover(token));
    token.addEventListener('blur', () => { if (matchMedia('(pointer:fine)').matches) closeHover(); });
    token.addEventListener('click', e => { e.stopPropagation(); if (!matchMedia('(pointer:fine)').matches) showHover(token); });
    token.addEventListener('contextmenu', e => { e.preventDefault(); e.stopPropagation(); showContextMenu(token,e.clientX,e.clientY); });
  });
  document.addEventListener('click', e => { if (!e.target.closest('#contextMenu')) document.getElementById('contextMenu').classList.remove('open'); });
  document.getElementById('closeResults').onclick = () => { searchSerial += 1; document.getElementById('resultsPanel').hidden = true; };
  addEventListener('resize', closeHover);
  addEventListener('scroll', closeHover, {passive:true});
}

async function init() {
  try {
    const r = await fetch(DATA_FILE, {cache:'no-store'});
    if (!r.ok) throw new Error(`JSON HTTP ${r.status}`);
    data = await r.json();
    document.getElementById('translation').textContent = data.translation;
    document.getElementById('shortCommentary').textContent = data.short_commentary;
    document.getElementById('detailText').textContent = data.detailed_commentary;
    renderVerse();
    wireEvents();
  } catch (e) {
    document.getElementById('app').innerHTML = `<div class="fatal">実験データを読み込めませんでした：${esc(e.message || e)}</div>`;
  }
}
init();
