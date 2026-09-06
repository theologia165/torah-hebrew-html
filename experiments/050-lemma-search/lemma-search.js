const DATA_FILE = 'https://raw.githubusercontent.com/theologia165/torah-hebrew-html/main/experiments/050-lemma-search/050-genesis-32-4.json';
const MORPHHB_COMMIT = '3d15126fb1ef74867fc1434be1942e837932691f';
const RAW_BASE = `https://raw.githubusercontent.com/openscriptures/morphhb/${MORPHHB_COMMIT}/wlc/`;

const BOOKS = [
  ['Gen','創世記'],['Exod','出エジプト記'],['Lev','レビ記'],['Num','民数記'],['Deut','申命記'],
  ['Josh','ヨシュア記'],['Judg','士師記'],['Ruth','ルツ記'],['1Sam','サムエル記第一'],['2Sam','サムエル記第二'],
  ['1Kgs','列王記第一'],['2Kgs','列王記第二'],['1Chr','歴代誌第一'],['2Chr','歴代誌第二'],
  ['Ezra','エズラ記'],['Neh','ネヘミヤ記'],['Esth','エステル記'],['Job','ヨブ記'],['Ps','詩篇'],
  ['Prov','箴言'],['Eccl','伝道者の書'],['Song','雅歌'],['Isa','イザヤ書'],['Jer','エレミヤ書'],
  ['Lam','哀歌'],['Ezek','エゼキエル書'],['Dan','ダニエル書'],['Hos','ホセア書'],['Joel','ヨエル書'],
  ['Amos','アモス書'],['Obad','オバデヤ書'],['Jonah','ヨナ書'],['Mic','ミカ書'],['Nah','ナホム書'],
  ['Hab','ハバクク書'],['Zeph','ゼパニヤ書'],['Hag','ハガイ書'],['Zech','ゼカリヤ書'],['Mal','マラキ書']
];

let data = null;
let activeToken = null;
const cache = new Map();

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
    Object.assign(token.dataset, {
      lemma: w.lemma,
      strong: w.strong,
      pos: w.pos,
      morph: w.morph
    });

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
    `<span class="hint">右クリック：同じlemmaを検索</span>`;
  popup.classList.add('open');

  requestAnimationFrame(() => {
    const r = token.getBoundingClientRect();
    const p = popup.getBoundingClientRect();
    const gap = 8, margin = 8;
    let left = r.left + r.width / 2 - p.width / 2;
    left = Math.max(margin, Math.min(left, innerWidth - p.width - margin));
    let top = r.bottom + gap;
    if (top + p.height > innerHeight - margin) top = r.top - p.height - gap;
    top = Math.max(margin, Math.min(top, innerHeight - p.height - margin));
    popup.style.left = `${left}px`;
    popup.style.top = `${top}px`;
  });
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
    <button id="searchLemmaBtn" type="button">同じlemmaをヘブライ語聖書全体から検索</button>
  `;
  menu.classList.add('open');
  const margin = 8;
  requestAnimationFrame(() => {
    const r = menu.getBoundingClientRect();
    menu.style.left = `${Math.max(margin, Math.min(x, innerWidth - r.width - margin))}px`;
    menu.style.top = `${Math.max(margin, Math.min(y, innerHeight - r.height - margin))}px`;
  });
  document.getElementById('searchLemmaBtn').onclick = () => {
    menu.classList.remove('open');
    searchLemma(token.dataset.lemma, token.dataset.strong);
  };
}

async function fetchBook(bookId) {
  if (cache.has(bookId)) return cache.get(bookId);
  const promise = fetch(`${RAW_BASE}${bookId}.xml`, {cache:'force-cache'})
    .then(r => {
      if (!r.ok) throw new Error(`${bookId}: HTTP ${r.status}`);
      return r.text();
    })
    .then(text => new DOMParser().parseFromString(text, 'application/xml'));
  cache.set(bookId, promise);
  return promise;
}

function verseRef(osisID, bookId, bookJa) {
  const bits = String(osisID || '').split('.');
  if (bits.length >= 3) return `${bookJa} ${bits[1]}:${bits[2]}`;
  return `${bookJa} (${osisID || bookId})`;
}

async function searchLemma(lemma, strong) {
  const panel = document.getElementById('resultsPanel');
  const title = document.getElementById('resultsTitle');
  const body = document.getElementById('resultsBody');
  panel.hidden = false;
  title.innerHTML = `<span dir="rtl">${esc(lemma)}</span> <small>${esc(strong)}</small>`;
  body.innerHTML = `<div class="loading">固定MorphHB（${esc(MORPHHB_COMMIT.slice(0,12))}…）をGitHubから検索中… <span id="progress">0/${BOOKS.length}</span></div>`;
  panel.scrollIntoView({behavior:'smooth', block:'start'});

  const progress = document.getElementById('progress');
  let done = 0;
  const perBook = new Map();
  const failures = [];

  await Promise.all(BOOKS.map(async ([bookId, bookJa]) => {
    try {
      const xml = await fetchBook(bookId);
      const hits = [];
      const verses = Array.from(xml.getElementsByTagNameNS('*', 'verse'));
      for (const verse of verses) {
        const words = Array.from(verse.getElementsByTagNameNS('*', 'w'));
        for (const w of words) {
          if (lemmaMatches(w.getAttribute('lemma'), strong)) {
            hits.push({
              ref: verseRef(verse.getAttribute('osisID'), bookId, bookJa),
              osis: verse.getAttribute('osisID') || '',
              surface: surfaceOf(w)
            });
          }
        }
      }
      if (hits.length) perBook.set(bookId, {bookJa, hits});
    } catch (e) {
      failures.push(String(e.message || e));
    } finally {
      done += 1;
      if (progress) progress.textContent = `${done}/${BOOKS.length}`;
    }
  }));

  const total = Array.from(perBook.values()).reduce((n, x) => n + x.hits.length, 0);
  let html = `<div class="result-summary"><b>${total}</b>件の語形を検出しました。` +
    `<span>検索キー：${esc(strong)} / <span dir="rtl">${esc(lemma)}</span></span></div>`;

  for (const [bookId, bookJa] of BOOKS) {
    const group = perBook.get(bookId);
    if (!group) continue;
    html += `<details class="book-group"><summary>${esc(bookJa)} <b>${group.hits.length}</b>件</summary><div class="hit-list">`;
    for (const hit of group.hits) {
      html += `<div class="hit"><span class="hit-ref">${esc(hit.ref)}</span><span class="hit-word" dir="rtl">${esc(hit.surface)}</span></div>`;
    }
    html += `</div></details>`;
  }

  if (failures.length) {
    html += `<div class="warning">取得できなかった書：${esc(failures.join(' / '))}</div>`;
  }
  html += `<div class="source-note">検索元：Open Scriptures Hebrew Bible / MorphHB (WLC), CC BY 4.0。この実験はブラウザ内でGitHub上の固定データを読み込み、PostgreSQL等のDBはまだ使用していません。</div>`;
  body.innerHTML = html;
}

function wireEvents() {
  document.querySelectorAll('.tok').forEach(token => {
    token.addEventListener('mouseenter', () => {
      if (matchMedia('(pointer:fine)').matches) showHover(token);
    });
    token.addEventListener('mouseleave', () => {
      if (matchMedia('(pointer:fine)').matches && !token.matches(':focus')) closeHover();
    });
    token.addEventListener('focus', () => showHover(token));
    token.addEventListener('blur', () => {
      if (matchMedia('(pointer:fine)').matches) closeHover();
    });
    token.addEventListener('click', e => {
      e.stopPropagation();
      if (!matchMedia('(pointer:fine)').matches) showHover(token);
    });
    token.addEventListener('contextmenu', e => {
      e.preventDefault();
      e.stopPropagation();
      showContextMenu(token, e.clientX, e.clientY);
    });
  });
  document.addEventListener('click', e => {
    if (!e.target.closest('#contextMenu')) document.getElementById('contextMenu').classList.remove('open');
  });
  document.getElementById('closeResults').onclick = () => {
    document.getElementById('resultsPanel').hidden = true;
  };
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
