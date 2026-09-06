const API = 'https://dtworks-hebrew-search.nishiharat.workers.dev';
const DATA = '../050-lemma-search/050-genesis-32-4.json';

const $ = (id) => document.getElementById(id);

function setStatus(el, ok, text) {
  el.textContent = text;
  el.classList.remove('pass','fail');
  el.classList.add(ok ? 'pass' : 'fail');
}

function strongNumber(value) {
  const m = String(value || '').match(/\d+/);
  return m ? Number(m[0]) : null;
}

async function getJson(url) {
  const res = await fetch(url, { cache: 'no-store' });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail || `${res.status} ${res.statusText}`);
  return body;
}

function renderVerse(data) {
  const verse = $('verse');
  verse.textContent = '';
  data.words.forEach((word, index) => {
    const span = document.createElement('span');
    span.className = 'word';
    span.tabIndex = 0;
    span.textContent = word.surface;
    span.title = `${word.gloss}｜${word.lemma}｜${word.strong}｜${word.morph}`;
    span.addEventListener('click', () => runWordSearch(word, index));
    span.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') runWordSearch(word, index);
    });
    verse.appendChild(span);
    const sep = document.createTextNode(word.separator_after === '־' ? '־' : ' ');
    verse.appendChild(sep);
  });
}

function buildQuery(word, index) {
  const strong = strongNumber(word.strong);
  if (!strong) throw new Error('この語にはStrong番号がありません。');
  const p = new URLSearchParams({ strong: String(strong), books: 'Gen', limit: '100' });
  if (index === 0 && strong === 7971) {
    p.set('stem', 'q');
    p.set('conjugation', 'w');
  }
  return p;
}

async function runWordSearch(word, index) {
  const results = $('results');
  $('resultsTitle').textContent = `${word.surface} のDB検索`;
  const p = buildQuery(word, index);
  $('queryLabel').textContent = p.toString();
  results.textContent = '検索中…';
  try {
    const data = await getJson(`${API}/search?${p}`);
    renderResults(data);
  } catch (err) {
    results.innerHTML = `<div class="error">検索失敗：${escapeHtml(err.message)}</div>`;
  }
}

function renderResults(data) {
  const results = $('results');
  results.textContent = '';
  const summary = document.createElement('div');
  summary.innerHTML = `<strong>${data.total}件</strong>（Genesis）`;
  results.appendChild(summary);
  data.results.forEach((r) => {
    const div = document.createElement('div');
    div.className = 'result';
    div.innerHTML = `
      <div class="ref">${escapeHtml(r.display_ref || r.osis_wlc || '')}</div>
      <div class="heb">${escapeHtml(r.surface || '')}</div>
      <div class="meta">Strong ${escapeHtml(r.primary_strong ?? '')}｜morph ${escapeHtml(r.morph_raw || '')}｜stem ${escapeHtml(r.main_stem_code || '—')}｜conjugation ${escapeHtml(r.main_conjugation_code || '—')}</div>`;
    results.appendChild(div);
  });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

async function boot() {
  try {
    const [health, source, benchmark] = await Promise.all([
      getJson(`${API}/health`),
      getJson(DATA),
      getJson(`${API}/search?strong=7971&stem=q&conjugation=w&books=Gen&limit=100`)
    ]);
    setStatus($('health'), health.status === 'ok', health.status === 'ok' ? 'PASS' : 'FAIL');
    $('tokenCount').textContent = Number(health.tokens).toLocaleString('ja-JP');
    setStatus($('benchmark'), benchmark.total === 15, benchmark.total === 15 ? 'PASS（15件）' : `FAIL（${benchmark.total}件）`);
    renderVerse(source);
    $('resultsTitle').textContent = '基準検索結果';
    $('queryLabel').textContent = 'Strong 7971 + Qal + wayyiqtol + Genesis';
    renderResults(benchmark);
  } catch (err) {
    setStatus($('health'), false, 'FAIL');
    setStatus($('benchmark'), false, 'FAIL');
    $('results').innerHTML = `<div class="error">初期化失敗：${escapeHtml(err.message)}</div>`;
    $('verse').textContent = '読み込みに失敗しました。';
  }
}

boot();
