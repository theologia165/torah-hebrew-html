const API = 'https://dtworks-hebrew-search.nishiharat.workers.dev';
const SOURCE = 'morphhb-wlc';
const REF = 'Gen.32.4';

const el = (id) => document.getElementById(id);
let passage = null;
let editorial = null;
let activeToken = null;

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#39;'}[c]));
}
function firstVerse(){return Array.isArray(passage?.verses)?passage.verses[0]:passage?.verse??passage}
function tokenList(){const v=firstVerse();return Array.isArray(v?.tokens)?v.tokens:[]}
function tokenIndex(t){return Number(t.index ?? t.token_index ?? t.i)}

const POS={V:'動詞',N:'名詞',A:'形容詞',P:'代名詞',R:'前置詞',C:'接続詞',D:'副詞',T:'冠詞・指示要素',S:'接尾辞'};
const STEM={q:'Qal',N:'Niphal',p:'Piel',P:'Pual',h:'Hiphil',H:'Hophal',t:'Hithpael'};
const CONJ={w:'wayyiqtol',q:'完了形',i:'未完了形',p:'命令形',r:'分詞',s:'受動分詞',a:'不定詞絶対形',c:'不定詞連語形'};
const GENDER={m:'男性',f:'女性',b:'共通'};
const NUMBER={s:'単数',p:'複数',d:'双数'};
const STATE={a:'絶対形',c:'連語形',d:'定形'};

function lemmaDisplay(t){
  return t.lemma_display || String(t.lemma_raw??t.lemma??'').split('/').pop()?.trim() || `Strong ${t.primary_strong??t.strong??'—'}`;
}
function morphologyJa(t){
  const person=t.person ?? t.person_code;
  const gender=t.gender ?? t.gender_code;
  const number=t.number ?? t.number_code;
  const state=t.state ?? t.state_code;
  const parts=[];
  if(person) parts.push(`${person}人称`);
  if(gender&&GENDER[gender]) parts.push(GENDER[gender]);
  if(number&&NUMBER[number]) parts.push(NUMBER[number]);
  if(state&&STATE[state]) parts.push(STATE[state]);
  return parts.join('・')||'—';
}
function hoverRows(t){
  const pos=t.pos ?? t.main_pos_code;
  const stem=t.stem ?? t.main_stem_code;
  const conjugation=t.conjugation ?? t.main_conjugation_code;
  const rows=[['レンマ',lemmaDisplay(t)],['Strong',t.primary_strong??t.strong??'—'],['品詞',POS[pos]??pos??'—']];
  if(stem) rows.push(['語幹',STEM[stem]??stem]);
  if(conjugation) rows.push(['活用',CONJ[conjugation]??conjugation]);
  const morph=morphologyJa(t); if(morph!=='—') rows.push(['形態',morph]);
  return rows;
}
function showHoverForNode(node,t){
  if(!t)return;
  document.querySelectorAll('.token.active').forEach(n=>n.classList.remove('active'));
  node.classList.add('active'); activeToken=node;
  const box=el('hover');
  box.innerHTML=`<div class="head" dir="rtl">${escapeHtml(t.surface)}</div>`+hoverRows(t).map(([k,v])=>`<div class="row"><span class="label">${escapeHtml(k)}</span><span>${escapeHtml(v)}</span></div>`).join('');
  box.hidden=false; placeHover(node);
}
function placeHover(node){
  const box=el('hover'),r=node.getBoundingClientRect(),pad=12;
  const w=box.offsetWidth||260,h=box.offsetHeight||150;
  let left=r.left+r.width/2-w/2,top=r.bottom+8;
  if(left<pad)left=pad;if(left+w+pad>innerWidth)left=innerWidth-w-pad;
  if(top+h+pad>innerHeight)top=r.top-h-8;
  box.style.left=`${Math.max(pad,left)}px`;box.style.top=`${Math.max(pad,top)}px`;
}
function hideHover(){el('hover').hidden=true;if(activeToken)activeToken.classList.remove('active');activeToken=null}

function render(){
  const tokens=tokenList();
  if(!tokens.length){el('status').textContent='本文データを取得できませんでした。';return;}
  const literal = editorial?.literal_translation ?? [];
  const gloss=new Map(literal.map(x=>[Number(x.token_index),x.ja]));
  el('verse').innerHTML=tokens.map(t=>{const i=tokenIndex(t);return `<button class="token" type="button" data-index="${i}"><span class="he">${escapeHtml(t.surface)}</span><span class="gloss">${escapeHtml(gloss.get(i)??'')}</span></button>`}).join('');
  el('status').textContent=`${REF}｜Neon /passage から ${tokens.length} 語を取得`;
  document.querySelectorAll('.token').forEach(node=>{
    const i=Number(node.dataset.index);const t=tokens.find(x=>tokenIndex(x)===i);
    node.addEventListener('mouseenter',()=>showHoverForNode(node,t));
    node.addEventListener('mouseleave',()=>{if(!node.matches(':focus'))hideHover()});
    node.addEventListener('focus',()=>showHoverForNode(node,t));
    node.addEventListener('blur',()=>hideHover());
    node.addEventListener('click',e=>{e.preventDefault();showHoverForNode(node,t)});
    node.addEventListener('contextmenu',e=>{e.preventDefault();hideHover();searchToken(t)});
  });
}

async function searchToken(token){
  if(!token)return;
  const strong=token.primary_strong??token.strong;if(!strong)return;
  const url=`${API}/search?strong=${encodeURIComponent(strong)}&books=Gen&limit=100`;
  const res=await fetch(url);if(!res.ok)throw new Error(`search ${res.status}`);const data=await res.json();
  el('resultsCard').hidden=false;el('resultsTitle').textContent=`${token.surface}｜Strong ${strong}`;el('resultsMeta').textContent=`Genesis内 ${data.total}件`;
  el('results').innerHTML=(data.results??[]).map(r=>`<div class="result"><b>${escapeHtml(r.display_ref??r.osis_wlc)}</b>　<span class="rhe" dir="rtl">${escapeHtml(r.surface)}</span></div>`).join('');
  el('resultsCard').scrollIntoView({behavior:'smooth',block:'nearest'});
}

async function boot(){
  try{
    const pRes=await fetch(`${API}/passage?source=${encodeURIComponent(SOURCE)}&ref=${encodeURIComponent(REF)}`);
    if(!pRes.ok)throw new Error(`/passage ${pRes.status}`);
    passage=await pRes.json();
    try{const eRes=await fetch('./editorial.json');if(eRes.ok)editorial=await eRes.json();}catch(e){console.warn('editorial unavailable',e)}
    render();
  }catch(error){console.error(error);el('status').textContent=`読み込みエラー: ${error.message}`}
}

document.addEventListener('click',e=>{if(!e.target.closest('.token'))hideHover()});
window.addEventListener('resize',()=>{if(activeToken&&!el('hover').hidden)placeHover(activeToken)});
el('closeResults').addEventListener('click',()=>{el('resultsCard').hidden=true});
boot();
