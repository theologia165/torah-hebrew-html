const API = 'https://dtworks-hebrew-search.nishiharat.workers.dev';
const SOURCE = 'morphhb-wlc';
const REF = 'Gen.32.4';

const el = (id) => document.getElementById(id);
let passage = null;
let editorial = null;
let activeToken = null;

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function firstVerse(){return Array.isArray(passage?.verses)?passage.verses[0]:passage?.verse??passage}
function tokenList(){const v=firstVerse();return Array.isArray(v?.tokens)?v.tokens:[]}

const POS={V:'動詞',N:'名詞',A:'形容詞',P:'代名詞',R:'前置詞',C:'接続詞',D:'副詞',T:'冠詞・指示要素',S:'接尾辞'};
const STEM={q:'Qal',N:'Niphal',p:'Piel',P:'Pual',h:'Hiphil',H:'Hophal',t:'Hithpael'};
const CONJ={w:'wayyiqtol',q:'完了形',i:'未完了形',p:'命令形',r:'分詞',s:'受動分詞',a:'不定詞絶対形',c:'不定詞連語形'};
const GENDER={m:'男性',f:'女性',b:'共通'};
const NUMBER={s:'単数',p:'複数',d:'双数'};
const STATE={a:'絶対形',c:'連語形',d:'定形'};

function lemmaDisplay(t){
  const raw=String(t.lemma_raw??t.lemma??'').split('/').pop()?.trim()??'';
  return raw.replace(/^\d+\s*/, '') || `Strong ${t.primary_strong??t.strong??'—'}`;
}
function morphologyJa(t){
  const parts=[];
  if(t.person_code) parts.push(`${t.person_code}人称`);
  if(t.gender_code&&GENDER[t.gender_code]) parts.push(GENDER[t.gender_code]);
  if(t.number_code&&NUMBER[t.number_code]) parts.push(NUMBER[t.number_code]);
  if(t.state_code&&STATE[t.state_code]) parts.push(STATE[t.state_code]);
  return parts.join('・')||'—';
}
function hoverRows(t){
  const rows=[
    ['レンマ',lemmaDisplay(t)],
    ['Strong',t.primary_strong??t.strong??'—'],
    ['品詞',POS[t.main_pos_code]??'—']
  ];
  if(t.main_stem_code) rows.push(['語幹',STEM[t.main_stem_code]??t.main_stem_code]);
  if(t.main_conjugation_code) rows.push(['活用',CONJ[t.main_conjugation_code]??t.main_conjugation_code]);
  const morph=morphologyJa(t); if(morph!=='—') rows.push(['形態',morph]);
  return rows;
}
function showHoverForNode(node,t){
  document.querySelectorAll('.token.active').forEach(n=>n.classList.remove('active'));
  node.classList.add('active'); activeToken=node;
  const box=el('hover');
  box.innerHTML=`<div class="head" dir="rtl">${escapeHtml(t.surface)}</div>`+hoverRows(t).map(([k,v])=>`<div class="row"><span class="label">${escapeHtml(k)}</span><span>${escapeHtml(v)}</span></div>`).join('');
  box.hidden=false;
  placeHover(node);
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
  const tokens=tokenList(); if(!tokens.length||!editorial)return;
  const gloss=new Map(editorial.literal_translation.map(x=>[Number(x.token_index),x.ja]));
  el('verse').innerHTML=tokens.map(t=>{const i=Number(t.token_index??t.i);return `<button class="token" type="button" data-index="${i}"><span class="he">${escapeHtml(t.surface)}</span><span class="gloss">${escapeHtml(gloss.get(i)??'')}</span></button>`}).join('');
  el('status').textContent=`${REF}｜Neon /passage から ${tokens.length} 語を取得`;
  document.querySelectorAll('.token').forEach(node=>{
    const i=Number(node.dataset.index);const t=tokens.find(x=>Number(x.token_index??x.i)===i);
    node.addEventListener('mouseenter',()=>showHoverForNode(node,t));
    node.addEventListener('mouseleave',()=>{if(!node.matches(':focus'))hideHover()});
    node.addEventListener('focus',()=>showHoverForNode(node,t));
    node.addEventListener('blur',()=>hideHover());
    node.addEventListener('click',e=>{e.preventDefault();showHoverForNode(node,t)});
    node.addEventListener('contextmenu',e=>{e.preventDefault();hideHover();searchToken(t)});
  });
}

async function searchToken(token){
  const strong=token.primary_strong??token.strong;if(!strong)return;
  const url=`${API}/search?strong=${encodeURIComponent(strong)}&books=Gen&limit=100`;
  const res=await fetch(url);if(!res.ok)throw new Error(`search ${res.status}`);const data=await res.json();
  el('resultsCard').hidden=false;el('resultsTitle').textContent=`${token.surface}｜Strong ${strong}`;el('resultsMeta').textContent=`Genesis内 ${data.total}件`;
  el('results').innerHTML=(data.results??[]).map(r=>`<div class="result"><b>${escapeHtml(r.display_ref??r.osis_wlc)}</b>　<span class="rhe" dir="rtl">${escapeHtml(r.surface)}</span></div>`).join('');
  el('resultsCard').scrollIntoView({behavior:'smooth',block:'nearest'});
}

async function boot(){
  try{
    const[pRes,eRes]=await Promise.all([fetch(`${API}/passage?source=${encodeURIComponent(SOURCE)}&ref=${encodeURIComponent(REF)}`),fetch('./editorial.json')]);
    if(!pRes.ok)throw new Error(`/passage ${pRes.status}`);if(!eRes.ok)throw new Error(`editorial ${eRes.status}`);
    passage=await pRes.json();editorial=await eRes.json();render();
  }catch(error){console.error(error);el('status').textContent=`読み込みエラー: ${error.message}`}
}

document.addEventListener('click',e=>{if(!e.target.closest('.token'))hideHover()});
window.addEventListener('resize',()=>{if(activeToken&&!el('hover').hidden)placeHover(activeToken)});
el('closeResults').addEventListener('click',()=>{el('resultsCard').hidden=true});
boot();
