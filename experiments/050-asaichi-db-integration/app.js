const API = 'https://dtworks-hebrew-search.nishiharat.workers.dev';
const SOURCE = 'morphhb-wlc';
const REF = 'Gen.32.4';

const el = (id) => document.getElementById(id);
let passage = null;
let editorial = null;

function setPill(id, text, ok) {
  const node = el(id);
  node.textContent = text;
  node.className = `pill ${ok ? 'pass' : 'fail'}`;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function firstVerse() {
  if (!passage) return null;
  if (Array.isArray(passage.verses)) return passage.verses[0] ?? null;
  if (passage.verse) return passage.verse;
  return passage;
}

function tokenList() {
  const verse = firstVerse();
  return Array.isArray(verse?.tokens) ? verse.tokens : [];
}

function mappedRefs() {
  const verse = firstVerse();
  return verse?.mappings ?? verse?.mapped_refs ?? passage?.mappings ?? passage?.mapped_refs ?? [];
}

function render() {
  const verse = firstVerse();
  const tokens = tokenList();
  if (!verse || !tokens.length || !editorial) return;

  el('translation').textContent = editorial.translation;
  el('summary').textContent = editorial.summary;

  const literalMap = new Map(editorial.literal_translation.map((x) => [Number(x.token_index), x.ja]));
  el('literal').innerHTML = tokens.map((t) => {
    const i = Number(t.token_index ?? t.i);
    return `<div class="literal-row"><span class="literal-he" dir="rtl">${escapeHtml(t.surface)}</span><span class="literal-ja">${escapeHtml(literalMap.get(i) ?? '')}</span></div>`;
  }).join('');

  el('verse').innerHTML = tokens.map((t) => {
    const i = Number(t.token_index ?? t.i);
    return `<button class="word" type="button" data-index="${i}">${escapeHtml(t.surface)}</button>`;
  }).join(' ');

  el('commentary').innerHTML = [
    ['本文の骨格', editorial.commentary.structure],
    ['文法', editorial.commentary.grammar],
    ['語彙', editorial.commentary.lexical],
    ['文脈', editorial.commentary.context],
    ['デボーショナルな受けとめ', editorial.commentary.devotional]
  ].map(([h, p]) => `<h3>${escapeHtml(h)}</h3><p>${escapeHtml(p)}</p>`).join('');

  document.querySelectorAll('.word').forEach((node) => {
    const index = Number(node.dataset.index);
    const token = tokens.find((t) => Number(t.token_index ?? t.i) === index);
    node.addEventListener('mouseenter', (event) => showHover(event, token));
    node.addEventListener('mousemove', moveHover);
    node.addEventListener('mouseleave', () => { el('hover').hidden = true; });
    node.addEventListener('click', () => searchToken(token));
  });
}

function showHover(event, token) {
  const box = el('hover');
  const strong = token.primary_strong ?? token.strong ?? '—';
  const lemma = token.lemma_raw ?? token.lemma ?? '—';
  const morph = token.morph_raw ?? token.morph ?? '—';
  box.innerHTML = `<b>${escapeHtml(token.surface)}</b><br>Strong: ${escapeHtml(strong)}<br>lemma: ${escapeHtml(lemma)}<br>MorphHB: ${escapeHtml(morph)}`;
  box.hidden = false;
  moveHover(event);
}

function moveHover(event) {
  const box = el('hover');
  const pad = 14;
  const width = box.offsetWidth || 220;
  const height = box.offsetHeight || 100;
  let left = event.clientX + 12;
  let top = event.clientY + 12;
  if (left + width + pad > window.innerWidth) left = event.clientX - width - 12;
  if (top + height + pad > window.innerHeight) top = event.clientY - height - 12;
  box.style.left = `${Math.max(pad, left)}px`;
  box.style.top = `${Math.max(pad, top)}px`;
}

async function searchToken(token) {
  const strong = token.primary_strong ?? token.strong;
  if (!strong) return;
  const url = `${API}/search?strong=${encodeURIComponent(strong)}&books=Gen&limit=100`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`search ${res.status}`);
  const data = await res.json();
  el('resultsCard').hidden = false;
  el('resultsTitle').textContent = `${token.surface}｜Strong ${strong}`;
  el('resultsMeta').textContent = `Genesis内 ${data.total}件`;
  el('results').innerHTML = (data.results ?? []).map((r) =>
    `<div class="result"><b>${escapeHtml(r.display_ref ?? r.osis_wlc)}</b>　<span dir="rtl">${escapeHtml(r.surface)}</span><br><small>${escapeHtml(r.morph_raw ?? '')}</small></div>`
  ).join('');
  el('resultsCard').scrollIntoView({behavior:'smooth', block:'start'});
}

async function boot() {
  try {
    const [pRes, eRes] = await Promise.all([
      fetch(`${API}/passage?source=${encodeURIComponent(SOURCE)}&ref=${encodeURIComponent(REF)}`),
      fetch('./editorial.json')
    ]);
    if (!pRes.ok) throw new Error(`/passage ${pRes.status}`);
    if (!eRes.ok) throw new Error(`editorial ${eRes.status}`);
    passage = await pRes.json();
    editorial = await eRes.json();

    const tokens = tokenList();
    setPill('passageStatus', `本文DB: PASS (${tokens.length} tokens)`, tokens.length > 0);
    setPill('editorialStatus', 'Editorial JSON: PASS', editorial.reference?.osis === REF);
    const maps = mappedRefs();
    const kjv = maps.find((m) => String(m.system ?? m.reference_system ?? '').toUpperCase() === 'KJV');
    setPill('mappingStatus', kjv ? `参照対応: ${REF} → ${kjv.ref ?? kjv.osis ?? 'KJV'}` : '参照対応: WLC', true);
    render();
  } catch (error) {
    console.error(error);
    setPill('passageStatus', `本文DB: ERROR (${error.message})`, false);
    setPill('editorialStatus', 'Editorial JSON: 未確認', false);
    setPill('mappingStatus', '参照対応: 未確認', false);
    el('translation').textContent = 'データを取得できませんでした。GitHub Pages / Cloudflare Worker の反映後に再読み込みしてください。';
  }
}

el('closeResults').addEventListener('click', () => { el('resultsCard').hidden = true; });
boot();
