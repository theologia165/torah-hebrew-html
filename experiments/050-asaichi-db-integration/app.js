const API = 'https://dtworks-hebrew-search.nishiharat.workers.dev';
const SOURCE = 'morphhb-wlc';
const REF = 'Gen.32.4';

const el = (id) => document.getElementById(id);
let passage = null;
let editorial = null;
let activeTokenNode = null;
let activeTokenData = null;
let hideTimer = null;
let searchTokenData = null;
let searchMode = 'lemma';
let searchHasRun = false;

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
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

function fallbackTokens(){
  return [...document.querySelectorAll('#verse .token')].map(node=>({
    index:Number(node.dataset.index),
    surface:node.dataset.surface,
    lemma_hebrew:node.dataset.lemma,
    lexeme_key:node.dataset.lexemeKey||null,
    pos:node.dataset.pos||null,
    stem:node.dataset.stem||null,
    conjugation:node.dataset.conjugation||null,
    person:node.dataset.person||null,
    gender:node.dataset.gender||null,
    number:node.dataset.number||null,
    state:node.dataset.state||null
  }));
}

function mergeLiveWithSnapshot(liveTokens,snapshot){
  const byIndex=new Map(snapshot.map(t=>[tokenIndex(t),t]));
  return liveTokens.map(t=>{
    const fallback=byIndex.get(tokenIndex(t))??{};
    return {
      ...t,
      lemma_hebrew:t?.lexeme?.lemma??t?.lexeme_lemma??t?.lemma_display??fallback.lemma_hebrew??null,
      lexeme_key:t?.lexeme?.key??t?.lexeme_key??fallback.lexeme_key??null,
      pos:t.pos??t.main_pos_code??fallback.pos??null,
      stem:t.stem??t.main_stem_code??fallback.stem??null,
      conjugation:t.conjugation??t.main_conjugation_code??fallback.conjugation??null,
      person:t.person??t.person_code??fallback.person??null,
      gender:t.gender??t.gender_code??fallback.gender??null,
      number:t.number??t.number_code??fallback.number??null,
      state:t.state??t.state_code??fallback.state??null
    };
  });
}

function hebrewLemma(t){
  const candidate=t?.lexeme?.lemma||t?.lexeme_lemma||t?.lemma_hebrew||t?.lemma_display||'';
  return /[\u0590-\u05FF]/.test(candidate)?candidate:'—';
}
function lexemeKey(t){return t?.lexeme?.key??t?.lexeme_key??null}
function isVerb(t){return (t?.pos??t?.main_pos_code)==='V'||String(t?.morph_raw??'').includes('/V')||String(t?.morph_raw??'').startsWith('HV')}
function partLabel(segment){
  const s=String(segment||'').replace(/^H/,'');
  if(s==='C')return '接続詞';
  if(s==='R'||s==='Rd')return '前置詞';
  if(s==='Np')return '固有名詞';
  if(/^Sp/.test(s))return '接尾代名詞';
  if(s==='Sd')return '方向の ה';
  if(/^V/.test(s))return '動詞';
  if(/^N/.test(s))return '名詞';
  if(/^A/.test(s))return '形容詞';
  if(/^P/.test(s))return '代名詞';
  return '';
}
function posLabel(t){
  const raw=String(t?.morph_raw??'');
  if(raw.includes('/')){
    const labels=[...new Set(raw.split('/').map(partLabel).filter(Boolean))];
    if(labels.length)return labels.join('＋');
  }
  const s=raw.replace(/^H/,'');
  const rawLabel=partLabel(s);
  if(rawLabel)return rawLabel;
  const pos=t?.pos??t?.main_pos_code;
  return POS[pos]??pos??'—';
}
function morphologyJa(t){
  const parts=[];
  const stem=t?.stem??t?.main_stem_code;
  const conjugation=t?.conjugation??t?.main_conjugation_code;
  const person=t?.person??t?.person_code;
  const gender=t?.gender??t?.gender_code;
  const number=t?.number??t?.number_code;
  const state=t?.state??t?.state_code;
  if(stem&&STEM[stem])parts.push(STEM[stem]);
  if(conjugation&&CONJ[conjugation])parts.push(CONJ[conjugation]);
  if(person)parts.push(`${person}人称`);
  if(gender&&GENDER[gender])parts.push(GENDER[gender]);
  if(number&&NUMBER[number])parts.push(NUMBER[number]);
  if(state&&STATE[state])parts.push(STATE[state]);
  return parts.join('・')||'—';
}
function hoverRows(t){
  const stem=t?.stem??t?.main_stem_code;
  const conjugation=t?.conjugation??t?.main_conjugation_code;
  const rows=[['Lemma',hebrewLemma(t),'lemma-value'],['品詞',posLabel(t),'']];
  if(stem)rows.push(['語幹',STEM[stem]??stem,'']);
  if(conjugation)rows.push(['活用',CONJ[conjugation]??conjugation,'']);
  const morph=morphologyJa(t);if(morph!=='—')rows.push(['形態',morph,'']);
  return rows;
}

function cancelHide(){if(hideTimer){clearTimeout(hideTimer);hideTimer=null}}
function scheduleHide(){cancelHide();hideTimer=setTimeout(hideHover,220)}
function showHoverForNode(node,t){
  if(!t)return;
  cancelHide();
  document.querySelectorAll('.token.active').forEach(n=>n.classList.remove('active'));
  node.classList.add('active');activeTokenNode=node;activeTokenData=t;
  const box=el('hover');
  const rows=hoverRows(t).map(([k,v,cls])=>`<div class="row"><span class="label">${escapeHtml(k)}</span><span class="${cls}">${escapeHtml(v)}</span></div>`).join('');
  box.innerHTML=`<div class="head" dir="rtl">${escapeHtml(t.surface)}</div>${rows}<div class="hover-actions"><button type="button" data-search-mode="lemma">レーマ検索</button><button type="button" data-search-mode="form">フォーム検索</button></div>`;
  box.hidden=false;placeHover(node);
}
function placeHover(node){
  const box=el('hover'),r=node.getBoundingClientRect(),pad=12;
  const w=box.offsetWidth||280,h=box.offsetHeight||180;
  let left=r.left+r.width/2-w/2,top=r.bottom+7;
  if(left<pad)left=pad;if(left+w+pad>innerWidth)left=innerWidth-w-pad;
  if(top+h+pad>innerHeight)top=r.top-h-7;
  box.style.left=`${Math.max(pad,left)}px`;box.style.top=`${Math.max(pad,top)}px`;
}
function hideHover(){
  cancelHide();
  el('hover').hidden=true;
  if(activeTokenNode)activeTokenNode.classList.remove('active');
  activeTokenNode=null;activeTokenData=null;
}

function bindTokens(tokens){
  document.querySelectorAll('#verse .token').forEach(node=>{
    const i=Number(node.dataset.index);const t=tokens.find(x=>tokenIndex(x)===i);
    node.onmouseenter=()=>showHoverForNode(node,t);
    node.onmouseleave=()=>{if(!node.matches(':focus'))scheduleHide()};
    node.onfocus=()=>showHoverForNode(node,t);
    node.onblur=()=>scheduleHide();
    node.onclick=e=>{e.preventDefault();showHoverForNode(node,t)};
    node.oncontextmenu=null;
  });
}
function renderLive(tokens,snapshot){
  if(!tokens.length)return false;
  const literal=editorial?.literal_translation??[];
  const gloss=new Map(literal.map(x=>[Number(x.token_index),x.ja]));
  const fallbackGloss=new Map([...document.querySelectorAll('#verse .token')].map(n=>[Number(n.dataset.index),n.querySelector('.gloss')?.textContent??'']));
  const snapshotByIndex=new Map(snapshot.map(t=>[tokenIndex(t),t]));
  el('verse').innerHTML=tokens.map(t=>{
    const i=tokenIndex(t),fallback=snapshotByIndex.get(i)??{},ja=gloss.get(i)??fallbackGloss.get(i)??'';
    return `<button class="token" type="button" data-index="${i}" data-surface="${escapeHtml(t.surface)}" data-lemma="${escapeHtml(hebrewLemma(t))}" data-lexeme-key="${escapeHtml(lexemeKey(t)??'')}" data-pos="${escapeHtml(t.pos??'')}" data-stem="${escapeHtml(t.stem??'')}" data-conjugation="${escapeHtml(t.conjugation??'')}" data-person="${escapeHtml(t.person??'')}" data-gender="${escapeHtml(t.gender??'')}" data-number="${escapeHtml(t.number??'')}" data-state="${escapeHtml(t.state??'')}"><span class="he">${escapeHtml(t.surface)}</span><span class="gloss">${escapeHtml(ja)}</span></button>`;
  }).join('');
  el('verse').dataset.fallback='false';
  bindTokens(tokens);
  el('status').textContent=`DB接続確認済み｜${REF}｜Neon /passage ${tokens.length}語｜OSHB Lexeme`;
  return true;
}

function setMode(mode){
  searchMode=mode==='form'?'form':'lemma';
  el('modeLemma').classList.toggle('active',searchMode==='lemma');
  el('modeForm').classList.toggle('active',searchMode==='form');
  if(searchTokenData){
    el('resultsTitle').textContent=searchMode==='lemma'?'レーマ検索':'フォーム検索';
    updateConditionLabel();
  }
}
function updateConditionAvailability(){
  const verb=isVerb(searchTokenData);
  const conj=searchTokenData?.conjugation??searchTokenData?.main_conjugation_code;
  el('qalOnly').disabled=!verb;
  el('sameConjugation').disabled=!verb||!conj;
  if(!verb){el('qalOnly').checked=false;el('sameConjugation').checked=false}
  if(!conj)el('sameConjugation').checked=false;
}
function conditionText(){
  if(!searchTokenData)return '';
  const bits=['Genesis全体',searchMode==='lemma'?'レーマ':'フォーム'];
  if(el('qalOnly').checked)bits.push('Qalのみ');
  if(el('sameConjugation').checked){
    const c=searchTokenData.conjugation??searchTokenData.main_conjugation_code;
    bits.push(`活用=${CONJ[c]??c}`);
  }
  return bits.join('｜');
}
function updateConditionLabel(){el('searchCondition').textContent=conditionText()}
function openSearchPanel(mode,t){
  if(!t)return;
  searchTokenData=t;searchHasRun=false;
  el('resultsCard').hidden=false;
  el('searchTarget').textContent=`${t.surface}　Lemma: ${hebrewLemma(t)}`;
  el('resultsMeta').textContent='条件を選んで検索してください。';
  el('results').innerHTML='';
  el('qalOnly').checked=false;
  el('sameConjugation').checked=false;
  el('limitSelect').value='100';
  updateConditionAvailability();setMode(mode);updateConditionLabel();
  el('runSearch').textContent='検索を実行';
  el('resultsCard').scrollIntoView({behavior:'smooth',block:'nearest'});
}
function buildSearchUrl(){
  if(!searchTokenData)throw new Error('検索対象がありません');
  const p=new URLSearchParams();
  if(searchMode==='lemma'){
    const key=lexemeKey(searchTokenData);
    if(!key)throw new Error('この語のレーマ検索キーを取得できません');
    p.set('lexeme',String(key));
  }else{
    if(!searchTokenData.surface)throw new Error('この語のフォームを取得できません');
    p.set('form',searchTokenData.surface);
  }
  p.set('books','Gen');
  p.set('limit',el('limitSelect').value);
  if(el('qalOnly').checked)p.set('stem','q');
  if(el('sameConjugation').checked){
    const c=searchTokenData.conjugation??searchTokenData.main_conjugation_code;
    if(c)p.set('conjugation',c);
  }
  return `${API}/search?${p.toString()}`;
}
async function runSearch(){
  if(!searchTokenData)return;
  const button=el('runSearch');button.disabled=true;button.textContent='検索中…';
  el('resultsMeta').textContent=`${conditionText()} を検索しています…`;el('results').innerHTML='';
  try{
    const res=await fetch(buildSearchUrl());if(!res.ok)throw new Error(`search ${res.status}`);const data=await res.json();
    searchHasRun=true;
    el('resultsMeta').textContent=`${conditionText()}｜${data.total}件`;
    const rows=data.results??[];
    el('results').innerHTML=rows.length?rows.map(r=>{
      const morph=r.morph_raw?`<span class="rmorph">${escapeHtml(r.morph_raw)}</span>`:'';
      return `<div class="result"><b>${escapeHtml(r.display_ref??r.osis_wlc)}</b>　<span class="rhe" dir="rtl">${escapeHtml(r.surface)}</span>${morph}</div>`;
    }).join(''):'<div class="results-empty">該当する語はありません。</div>';
  }catch(error){
    el('resultsMeta').textContent=`検索APIエラー: ${error.message}`;el('results').innerHTML='';
  }finally{
    button.disabled=false;button.textContent=searchHasRun?'この条件で再検索':'検索を実行';
  }
}
function closeSearch(){el('resultsCard').hidden=true;searchTokenData=null;searchHasRun=false}

async function boot(){
  const snapshot=fallbackTokens();
  passage={verses:[{tokens:snapshot}]};bindTokens(snapshot);
  try{const eRes=await fetch('./editorial.json');if(eRes.ok)editorial=await eRes.json();}catch(e){console.warn('editorial unavailable',e)}
  try{
    const pRes=await fetch(`${API}/passage?source=${encodeURIComponent(SOURCE)}&ref=${encodeURIComponent(REF)}`);
    if(!pRes.ok)throw new Error(`/passage ${pRes.status}`);
    const live=await pRes.json();
    const liveTokens=Array.isArray(live?.verses?.[0]?.tokens)?live.verses[0].tokens:[];
    if(liveTokens.length!==11)throw new Error(`/passage token count ${liveTokens.length}`);
    const merged=mergeLiveWithSnapshot(liveTokens,snapshot);
    if(merged.some(t=>!lexemeKey(t)||hebrewLemma(t)==='—'))throw new Error('/passage lexeme data incomplete');
    passage={...live,verses:[{...live.verses[0],tokens:merged}]};renderLive(merged,snapshot);
  }catch(error){
    console.error(error);passage={verses:[{tokens:snapshot}]};bindTokens(snapshot);
    el('status').textContent=`検証済みスナップショット表示｜live API確認失敗: ${error.message}`;
  }
}

el('hover').addEventListener('mouseenter',cancelHide);
el('hover').addEventListener('mouseleave',scheduleHide);
el('hover').addEventListener('click',e=>{
  const button=e.target.closest('[data-search-mode]');if(!button)return;
  e.stopPropagation();cancelHide();openSearchPanel(button.dataset.searchMode,activeTokenData);
});
el('modeLemma').addEventListener('click',()=>setMode('lemma'));
el('modeForm').addEventListener('click',()=>setMode('form'));
el('qalOnly').addEventListener('change',updateConditionLabel);
el('sameConjugation').addEventListener('change',updateConditionLabel);
el('scopeSelect').addEventListener('change',updateConditionLabel);
el('limitSelect').addEventListener('change',updateConditionLabel);
el('runSearch').addEventListener('click',runSearch);
el('closeResults').addEventListener('click',closeSearch);
document.addEventListener('click',e=>{
  if(!e.target.closest('.token')&&!e.target.closest('#hover')&&!e.target.closest('#resultsCard'))scheduleHide();
});
window.addEventListener('resize',()=>{if(activeTokenNode&&!el('hover').hidden)placeHover(activeTokenNode)});
boot();
